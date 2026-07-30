import os
import sys
import logging
import hashlib
import asyncio

logger = logging.getLogger("gouer_admin")
import secrets
import re
import json
import base64
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

def generate_obfuscated_paths(secret_key: str = "") -> dict:
    if not secret_key:
        secret_key = os.getenv("KEY", secrets.token_hex(16))
    h = hashlib.sha256(f"admin_panel_v5_{secret_key}".encode()).hexdigest()
    return {
        "api_prefix": f"/api/{h[:12]}",
        "login_path": f"/{h[12:24]}",
        "admin_path": f"/{h[24:36]}",
        "health_path": f"/_health_{h[8:16]}",
    }

OBF = generate_obfuscated_paths(os.getenv("KEY", ""))

# ── FastAPI App ─────────────────────────────────────────
app = FastAPI(
    title="GouerAdmin",
    docs_url=None, redoc_url=None, openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── JWT / Auth ──────────────────────────────────────────
from jose import jwt, JWTError
import pyotp

JWT_SECRET = os.getenv("KEY", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
ADMIN_2FA_SECRET = os.getenv("ADMIN_2FA_SECRET", "")

def _hash_password(password: str, salt: str = "") -> tuple:
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200000)
    return salt, dk.hex()

def verify_password(plain: str, stored_salt: str, stored_hash: str) -> bool:
    _, computed = _hash_password(plain, stored_salt)
    return computed == stored_hash

_admin_salt = None
_admin_hash = None
_totp = None

def init_auth():
    global _admin_salt, _admin_hash, _totp
    _admin_salt, _admin_hash = _hash_password(ADMIN_PASS)
    secret = ADMIN_2FA_SECRET or pyotp.random_base32()
    _totp = pyotp.TOTP(secret)
    return secret

_current_2fa_secret = init_auth()

def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=8)):
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + expires_delta
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_admin(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="登录已过期")

# ── Security Headers (CSP + XSS protection) ────────────────
import re as _re

_XSS_PATTERN = _re.compile(r"<script|javascript:|on\w+\s*=", _re.IGNORECASE)

def _validate_no_xss(value: str) -> str:
    if value and _XSS_PATTERN.search(value):
        raise HTTPException(status_code=400, detail="输入包含非法内容")
    return value

@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# ── Rate Limiter (登录限流中间件) ──────────────────────────
import time as _time
import random as _random

_login_attempts = {}  # IP → [timestamps]

@app.middleware("http")
async def _rate_limit_middleware(request: Request, call_next):
    """对 /login 接口限流：每 IP 每分钟最多 10 次"""
    if request.url.path.endswith("/login") and request.method == "POST":
        ip = request.client.host if request.client else "127.0.0.1"
        now = _time.time()
        if ip not in _login_attempts:
            _login_attempts[ip] = []
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < 60]
        if len(_login_attempts[ip]) >= 10:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请 60 秒后再试"})
        _login_attempts[ip].append(now)
    return await call_next(request)

from fastapi.responses import JSONResponse

# ── CAPTCHA (image-based, 4-char distorted text) ──────────
import time as _time
import random as _random
import io as _io

_captchas = {}  # captcha_id → {"answer": "AB12", "expires": timestamp}

def _generate_captcha_image(code: str) -> str:
    from PIL import Image, ImageDraw, ImageFont
    w, h = 140, 52
    img = Image.new("RGB", (w, h), (245, 247, 250))
    draw = ImageDraw.Draw(img)
    # 随机噪线
    for _ in range(5):
        x1 = _random.randint(0, w); y1 = _random.randint(0, h)
        x2 = _random.randint(0, w); y2 = _random.randint(0, h)
        draw.line([(x1, y1), (x2, y2)], fill=(_random.randint(120, 200), _random.randint(120, 200), _random.randint(120, 200)), width=2)
    # 随机噪点
    for _ in range(80):
        draw.point((_random.randint(0, w), _random.randint(0, h)), fill=(_random.randint(60, 180), _random.randint(60, 180), _random.randint(60, 180)))
    # 绘制文字（每个字符独立偏移）
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    except Exception:
        font = ImageFont.load_default()
    for i, ch in enumerate(code):
        x = 14 + i * 30 + _random.randint(-3, 3)
        y = 10 + _random.randint(-4, 4)
        draw.text((x, y), ch, fill=(_random.randint(10, 100), _random.randint(10, 100), _random.randint(10, 100)), font=font)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def _generate_captcha() -> dict:
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(_random.choices(chars, k=4))
    cid = secrets.token_hex(8)
    _captchas[cid] = {"answer": code, "expires": _time.time() + 300}
    img_b64 = _generate_captcha_image(code)
    return {"captcha_id": cid, "image": f"data:image/png;base64,{img_b64}", "expires_in": 300}

def _verify_captcha(captcha_id: str, captcha_answer: str) -> bool:
    entry = _captchas.pop(captcha_id, None)
    if not entry or _time.time() > entry["expires"]:
        return False
    return entry["answer"].upper() == str(captcha_answer).strip().upper()

# ── Database ────────────────────────────────────────────
import aiomysql

_db_pool = None

async def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = await aiomysql.create_pool(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            db=os.getenv("DB", "test"),
            autocommit=True,
            minsize=2, maxsize=10,
        )
    return _db_pool

# ── SQL Validation ──────────────────────────────────────
_VALID_COLUMN_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def validate_column_name(col: str) -> str:
    if not _VALID_COLUMN_RE.match(col):
        raise ValueError(f"Invalid column name: {col}")
    return col

def validate_table_name(name: str) -> str:
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Invalid table name: {name}")
    return name

# ── Pydantic Models ─────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str = ""
    captcha_id: str = ""
    captcha_answer: str = ""

class GroupInfoUpdate(BaseModel):
    title: Optional[str] = None
    username: Optional[str] = None
    type: Optional[str] = None

class GroupVerifyUpdate(BaseModel):
    verify_status: Optional[bool] = None
    verify_mode: Optional[str] = None
    verify_duration: Optional[int] = None
    verify_penalty: Optional[str] = None

class WelcomeSettingsUpdate(BaseModel):
    status: Optional[bool] = None
    delete_time: Optional[int] = None
    delete_last: Optional[bool] = None
    welcome_text: Optional[str] = None
    buttons_text: Optional[str] = None

class NightSettingsUpdate(BaseModel):
    status: Optional[bool] = None
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None
    notify: Optional[bool] = None

class AntispamUpdate(BaseModel):
    enabled: Optional[bool] = None
    block_contact: Optional[bool] = None
    block_location: Optional[bool] = None
    block_channel_send: Optional[bool] = None
    block_channel_fwd: Optional[bool] = None
    block_external_ref: Optional[bool] = None
    block_exe: Optional[bool] = None
    block_mention: Optional[bool] = None
    block_links: Optional[bool] = None
    block_long_links: Optional[bool] = None
    block_visitor_bots: Optional[bool] = None
    block_flood: Optional[bool] = None
    flood_timeout: Optional[int] = None
    flood_count: Optional[int] = None
    penalty: Optional[str] = None
    mute_duration: Optional[int] = None
    whitelist: Optional[str] = None
    warn_delete: Optional[int] = None

class ChatAISettings(BaseModel):
    chat_enabled: Optional[bool] = None
    chat_prompt: Optional[str] = None
    chat_trigger: Optional[str] = None
    audit_enabled: Optional[bool] = None
    audit_penalty: Optional[str] = None

class ToggleSettings(BaseModel):
    enabled: Optional[bool] = None
    open_keyword: Optional[str] = None
    open_text: Optional[str] = None
    close_keyword: Optional[str] = None
    close_text: Optional[str] = None

class PointsSettings(BaseModel):
    status: Optional[bool] = None
    msg_points: Optional[int] = None
    ignore_stickers: Optional[bool] = None
    delete_time: Optional[int] = None

class SpeakCheckSettings(BaseModel):
    enabled: Optional[bool] = None
    require_last_name: Optional[bool] = None
    require_username: Optional[bool] = None
    require_photo: Optional[bool] = None
    require_premium: Optional[bool] = None
    require_channel: Optional[bool] = None
    channel_username: Optional[str] = None
    penalty: Optional[str] = None
    mute_duration: Optional[int] = None
    warn_delete: Optional[int] = None

class AutodeleteUpdate(BaseModel):
    pin: Optional[bool] = None
    photo: Optional[bool] = None
    title: Optional[bool] = None

class CardSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    template: Optional[str] = None

class PermissionUpdate(BaseModel):
    permissions: str = "all"

class DingshiCreate(BaseModel):
    chat_id: int
    schedule_time: str
    schedule_days: str = "*"
    interval_minutes: int = 0
    content_text: str = ""
    buttons_text: str = ""
    status: bool = True

class KeywordCreate(BaseModel):
    chat_id: int
    word: str
    penalty: str = "delete"
    mute_duration: int = 3600
    status: bool = True

class QuickPublishCreate(BaseModel):
    creator_id: int = 0
    name: str
    keyword: str
    content_text: str = ""
    buttons_text: str = ""
    status: bool = True

class SubscriptionUpdate(BaseModel):
    chat_id: int
    feature: str
    days: int = 30

class BotTokenCreate(BaseModel):
    owner_id: int
    bot_token: str
    bot_username: str = ""

class UserUpdate(BaseModel):
    username: Optional[str] = None
    first_name: Optional[str] = None
    bio: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None

class DBQueryRequest(BaseModel):
    sql: str
    limit: int = 100

# ══════════════════════════════════════════════════════════
#  API Routes
# ══════════════════════════════════════════════════════════

PREFIX = OBF["api_prefix"]

# ── Auth ─────────────────────────────────────────────────
@app.post(f"{PREFIX}/captcha")
async def api_get_captcha():
    return _generate_captcha()

@app.post(f"{PREFIX}/login")
async def api_login(req: LoginRequest):
    # 验证码
    if not req.captcha_id or not req.captcha_answer:
        raise HTTPException(status_code=400, detail="请输入验证码")
    if not _verify_captcha(req.captcha_id, req.captcha_answer):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    # 账号密码
    if req.username != ADMIN_USER:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(req.password, _admin_salt, _admin_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # Google 2FA
    if not req.totp_code:
        raise HTTPException(status_code=400, detail="请输入 Google 验证码")
    if not _totp.verify(req.totp_code):
        raise HTTPException(status_code=401, detail="Google 验证码错误")

    token = create_access_token({"sub": req.username, "role": "admin"})
    must_change = (ADMIN_PASS == "admin123")
    return {"access_token": token, "token_type": "bearer", "admin": req.username, "must_change_password": must_change}


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str

@app.post(f"{PREFIX}/change-password")
async def change_password(req: PasswordChangeRequest, admin=Depends(get_current_admin)):
    global _admin_salt, _admin_hash
    if not verify_password(req.old_password, _admin_salt, _admin_hash):
        raise HTTPException(status_code=401, detail="原密码错误")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    if req.new_password == "admin123":
        raise HTTPException(status_code=400, detail="不能使用默认密码")
    _admin_salt, _admin_hash = _hash_password(req.new_password)
    _save_env("ADMIN_PASS", req.new_password)
    os.environ["ADMIN_PASS"] = req.new_password
    return {"ok": True}


class UsernameChangeRequest(BaseModel):
    password: str
    totp_code: str
    new_username: str

@app.post(f"{PREFIX}/change-username")
async def change_username(req: UsernameChangeRequest, admin=Depends(get_current_admin)):
    global ADMIN_USER, _totp
    if not verify_password(req.password, _admin_salt, _admin_hash):
        raise HTTPException(status_code=401, detail="密码错误")
    if not _totp.verify(req.totp_code):
        raise HTTPException(status_code=401, detail="Google 验证码错误")
    new_name = req.new_username.strip()
    if len(new_name) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 位")
    if not new_name.isalnum():
        raise HTTPException(status_code=400, detail="用户名只能包含字母和数字")
    ADMIN_USER = new_name
    _save_env("ADMIN_USER", new_name)
    os.environ["ADMIN_USER"] = new_name
    return {"ok": True, "username": new_name}
@app.get(f"{PREFIX}/2fa-setup")
async def get_2fa_setup(confirm: bool = False, admin=Depends(get_current_admin)):
    if not confirm:
        return {"require_confirm": True, "hint": "传 confirm=true 确认查看"}
    import qrcode, io, base64
    secret = _current_2fa_secret
    uri = _totp.provisioning_uri(name=ADMIN_USER, issuer_name="GouerAdmin")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()
    return {"secret": secret, "qr_code": f"data:image/png;base64,{qr_base64}", "uri": uri}

class TwoFAResetRequest(BaseModel):
    password: str
    totp_code: str

@app.post(f"{PREFIX}/2fa-reset")
async def reset_2fa(req: TwoFAResetRequest, admin=Depends(get_current_admin)):
    global _totp, _current_2fa_secret
    if not verify_password(req.password, _admin_salt, _admin_hash):
        raise HTTPException(status_code=401, detail="密码错误")
    if not _totp.verify(req.totp_code):
        raise HTTPException(status_code=401, detail="Google 验证码错误")

    _current_2fa_secret = pyotp.random_base32()
    _totp = pyotp.TOTP(_current_2fa_secret)
    _save_env("ADMIN_2FA_SECRET", _current_2fa_secret)
    os.environ["ADMIN_2FA_SECRET"] = _current_2fa_secret

    import qrcode, io, base64
    uri = _totp.provisioning_uri(name=ADMIN_USER, issuer_name="GouerAdmin")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()
    return {"secret": _current_2fa_secret, "qr_code": f"data:image/png;base64,{qr_base64}", "uri": uri}

# ── Dashboard ────────────────────────────────────────────
@app.get(f"{PREFIX}/dashboard")
async def api_dashboard(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM qunzu"); groups = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM pindao"); channels = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM users"); users = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM group_choujiang WHERE status='active'"); active_lotteries = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM bot_tokens WHERE status='active'"); active_clones = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM group_subscriptions WHERE expires_at > NOW()"); active_subs = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM group_dingshi WHERE status=TRUE"); scheduled_msgs = (await cur.fetchone())[0]
    return {"groups": groups, "channels": channels, "users": users, "active_lotteries": active_lotteries, "active_clones": active_clones, "active_subscriptions": active_subs, "scheduled_messages": scheduled_msgs}

# ── Groups ───────────────────────────────────────────────
@app.get(f"{PREFIX}/groups")
async def list_groups(search: str = "", admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if search:
                await cur.execute("SELECT chat_id, title, username, type, created_at FROM qunzu WHERE title LIKE %s OR username LIKE %s OR CAST(chat_id AS CHAR) LIKE %s ORDER BY created_at DESC", (f"%{search}%", f"%{search}%", f"%{search}%"))
            else:
                await cur.execute("SELECT chat_id, title, username, type, created_at FROM qunzu ORDER BY created_at DESC")
            rows = await cur.fetchall()
    return [{"chat_id": r[0], "title": r[1], "username": r[2], "type": r[3], "created_at": str(r[4])} for r in rows]

@app.get(f"{PREFIX}/groups/{{chat_id}}")
async def get_group_detail(chat_id: int, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    result = {"chat_id": chat_id}
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT title, username, type, created_at FROM qunzu WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if not row: raise HTTPException(status_code=404, detail="群组不存在")
            result["title"], result["username"], result["type"], result["created_at"] = row[0], row[1], row[2], str(row[3])

            await cur.execute("SELECT verify_status, verify_mode, verify_duration, verify_penalty FROM group_settings WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["verify"] = {"status": bool(row[0]), "mode": row[1], "duration": row[2], "penalty": row[3]} if row else {"status": False, "mode": "button", "duration": 1, "penalty": "mute"}

            await cur.execute("SELECT status, delete_time, delete_last, media_type, welcome_text, buttons_text FROM group_welcome WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["welcome"] = {"status": bool(row[0]) if row else False, "delete_time": row[1] if row else 0, "delete_last": bool(row[2]) if row else False, "media_type": row[3] if row else None, "welcome_text": row[4] if row else "", "buttons_text": row[5] if row else ""}

            await cur.execute("SELECT status, msg_points, ignore_stickers, delete_time FROM group_points_settings WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["points"] = {"status": bool(row[0]) if row else False, "msg_points": row[1] if row else 0, "ignore_stickers": bool(row[2]) if row else True, "delete_time": row[3] if row else 0}

            await cur.execute("SELECT status, start_hour, end_hour, notify FROM group_night WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["night"] = {"status": bool(row[0]) if row else False, "start_hour": row[1] if row else 0, "end_hour": row[2] if row else 6, "notify": bool(row[3]) if row else True}

            await cur.execute("SELECT chat_enabled, chat_prompt, chat_trigger, audit_enabled, audit_penalty FROM group_ai WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["ai"] = {"chat_enabled": bool(row[0]) if row else False, "chat_prompt": row[1] if row else "", "chat_trigger": row[2] if row else "", "audit_enabled": bool(row[3]) if row else False, "audit_penalty": row[4] if row else "delete"}

            await cur.execute("SELECT * FROM group_toggle WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if row:
                tcols = [d[0] for d in cur.description]
                result["toggle"] = {tcols[i]: row[i] for i in range(len(tcols))}
            else:
                result["toggle"] = {"enabled": False}

            await cur.execute("SELECT * FROM group_message_check WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if row:
                mcols = [d[0] for d in cur.description]
                result["speak_check"] = {mcols[i]: row[i] for i in range(len(mcols))}
            else:
                result["speak_check"] = {"enabled": False}

            await cur.execute("SELECT enabled, template FROM group_card WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["card"] = {"enabled": bool(row[0]) if row else False, "template": row[1] if row else "default"}

            await cur.execute("SELECT pin, photo, title FROM group_autodelete WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["autodelete"] = {"pin": bool(row[0]) if row else False, "photo": bool(row[1]) if row else False, "title": bool(row[2]) if row else False}

            await cur.execute("SELECT permissions FROM group_permission WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["permission"] = row[0] if row else "all"

            await cur.execute("SELECT * FROM group_antispam WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                result["antispam"] = {cols[i]: row[i] for i in range(len(cols))}
            else:
                result["antispam"] = {"enabled": False}

            await cur.execute("SELECT feature, expires_at FROM group_subscriptions WHERE chat_id=%s AND expires_at > NOW()", (chat_id,))
            subs = await cur.fetchall()
            result["subscriptions"] = [{"feature": s[0], "expires_at": str(s[1])} for s in subs]

            await cur.execute("SELECT COUNT(*) FROM group_dingshi WHERE chat_id=%s AND status=TRUE", (chat_id,))
            result["dingshi_count"] = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM group_weijinci WHERE chat_id=%s AND status=TRUE", (chat_id,))
            result["weijinci_count"] = (await cur.fetchone())[0]

            clean_id = str(chat_id).replace("-", "")
            try:
                await cur.execute(f"SELECT COUNT(*) FROM `{{validate_table_name(f'qunzu_{{clean_id}}')}}`")
                result["action_count"] = (await cur.fetchone())[0]
            except Exception:
                result["action_count"] = 0
    return result

def _update_generic(chat_id, table, data: dict):
    updates = {k: v for k, v in data.items() if v is not None}
    if not updates: return False
    async def do(conn):
        async with conn.cursor() as cur:
            await cur.execute(f"INSERT IGNORE INTO {validate_table_name(table)} (chat_id) VALUES (%s)", (chat_id,))
            parts, vals = [], []
            for k, v in updates.items():
                parts.append(f"{validate_column_name(k)}=%s")
                vals.append(v)
            vals.append(chat_id)
            await cur.execute(f"UPDATE {validate_table_name(table)} SET {', '.join(parts)} WHERE chat_id=%s", vals)
    return do

@app.put(f"{PREFIX}/groups/{{chat_id}}")
async def update_group_info(chat_id: int, data: GroupInfoUpdate, admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates: return {"ok": True}
    parts, vals = [], []
    for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
    vals.append(chat_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE qunzu SET {', '.join(parts)} WHERE chat_id=%s", vals)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/verify")
async def update_group_verify(chat_id: int, data: GroupVerifyUpdate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""INSERT INTO group_settings (chat_id, verify_status, verify_mode, verify_duration, verify_penalty)
                VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE verify_status=VALUES(verify_status),
                verify_mode=VALUES(verify_mode), verify_duration=VALUES(verify_duration), verify_penalty=VALUES(verify_penalty)""",
                (chat_id, data.verify_status, data.verify_mode, data.verify_duration, data.verify_penalty))
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/welcome")
async def update_group_welcome(chat_id: int, data: WelcomeSettingsUpdate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _update_generic(chat_id, "group_welcome", data.model_dump())(conn)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/night")
async def update_group_night(chat_id: int, data: NightSettingsUpdate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _update_generic(chat_id, "group_night", data.model_dump())(conn)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/antispam")
async def update_group_antispam(chat_id: int, data: AntispamUpdate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _update_generic(chat_id, "group_antispam", data.model_dump())(conn)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/ai")
async def update_group_ai(chat_id: int, data: ChatAISettings, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _update_generic(chat_id, "group_ai", data.model_dump())(conn)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/toggle")
async def update_group_toggle(chat_id: int, data: ToggleSettings, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _update_generic(chat_id, "group_toggle", data.model_dump())(conn)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/points")
async def update_group_points(chat_id: int, data: PointsSettings, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _update_generic(chat_id, "group_points_settings", data.model_dump())(conn)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/speak-check")
async def update_speak_check(chat_id: int, data: SpeakCheckSettings, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _update_generic(chat_id, "group_message_check", data.model_dump())(conn)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/card")
async def update_group_card(chat_id: int, data: CardSettingsUpdate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _update_generic(chat_id, "group_card", data.model_dump())(conn)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/autodelete")
async def update_group_autodelete(chat_id: int, data: AutodeleteUpdate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _update_generic(chat_id, "group_autodelete", data.model_dump())(conn)
    return {"ok": True}

@app.put(f"{PREFIX}/groups/{{chat_id}}/permission")
async def update_group_permission(chat_id: int, data: PermissionUpdate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""INSERT INTO group_permission (chat_id, permissions) VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE permissions=VALUES(permissions)""", (chat_id, data.permissions))
    return {"ok": True}

# ── Dingshi ──────────────────────────────────────────────
@app.get(f"{PREFIX}/dingshi")
async def list_dingshi(chat_id: int = None, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if chat_id: await cur.execute("SELECT * FROM group_dingshi WHERE chat_id=%s ORDER BY created_at DESC", (chat_id,))
            else: await cur.execute("SELECT * FROM group_dingshi ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return [{cols[i]: (str(r[i]) if isinstance(r[i], datetime) else r[i]) for i in range(len(cols))} for r in rows]

@app.post(f"{PREFIX}/dingshi")
async def create_dingshi(data: DingshiCreate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO group_dingshi (chat_id,schedule_time,schedule_days,interval_minutes,content_text,buttons_text,status) VALUES (%s,%s,%s,%s,%s,%s,%s)", (data.chat_id, data.schedule_time, data.schedule_days, data.interval_minutes, data.content_text, data.buttons_text, data.status))
            return {"ok": True, "id": cur.lastrowid}

@app.put(f"{PREFIX}/dingshi/{{ding_id}}")
async def update_dingshi(ding_id: int, data: dict, admin=Depends(get_current_admin)):
    allowed = {"schedule_time","schedule_days","interval_minutes","content_text","buttons_text","status"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates: return {"ok": True}
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(ding_id)
            await cur.execute(f"UPDATE group_dingshi SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}

@app.delete(f"{PREFIX}/dingshi/{{ding_id}}")
async def delete_dingshi(ding_id: int, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_dingshi WHERE id=%s", (ding_id,))
    return {"ok": True}

# ── Weijinci ─────────────────────────────────────────────
@app.get(f"{PREFIX}/weijinci")
async def list_weijinci(chat_id: int = None, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if chat_id: await cur.execute("SELECT * FROM group_weijinci WHERE chat_id=%s ORDER BY created_at DESC", (chat_id,))
            else: await cur.execute("SELECT * FROM group_weijinci ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return [{cols[i]: (str(r[i]) if isinstance(r[i], datetime) else r[i]) for i in range(len(cols))} for r in rows]

@app.post(f"{PREFIX}/weijinci")
async def create_weijinci(data: KeywordCreate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO group_weijinci (chat_id, word, penalty, mute_duration, status) VALUES (%s,%s,%s,%s,%s)", (data.chat_id, data.word, data.penalty, data.mute_duration, data.status))
            return {"ok": True, "id": cur.lastrowid}

@app.delete(f"{PREFIX}/weijinci/{{word_id}}")
async def delete_weijinci(word_id: int, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_weijinci WHERE id=%s", (word_id,))
    return {"ok": True}

@app.put(f"{PREFIX}/weijinci/{{word_id}}")
async def update_weijinci(word_id: int, data: dict, admin=Depends(get_current_admin)):
    allowed = {"word", "penalty", "mute_duration", "status"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates: return {"ok": True}
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(word_id)
            await cur.execute(f"UPDATE group_weijinci SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}

# ── Quick Publish ────────────────────────────────────────
@app.get(f"{PREFIX}/kuaisufabu")
async def list_kuaisufabu(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM group_kuaisufabu ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return [{cols[i]: (str(r[i]) if isinstance(r[i], datetime) else r[i]) for i in range(len(cols))} for r in rows]

@app.post(f"{PREFIX}/kuaisufabu")
async def create_kuaisufabu(data: QuickPublishCreate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO group_kuaisufabu (creator_id,name,keyword,content_text,buttons_text,status) VALUES (%s,%s,%s,%s,%s,%s)", (data.creator_id, data.name, data.keyword, data.content_text, data.buttons_text, data.status))
            return {"ok": True, "id": cur.lastrowid}

@app.delete(f"{PREFIX}/kuaisufabu/{{pub_id}}")
async def delete_kuaisufabu(pub_id: int, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_kuaisufabu WHERE id=%s", (pub_id,))
    return {"ok": True}

@app.put(f"{PREFIX}/kuaisufabu/{{pub_id}}")
async def update_kuaisufabu(pub_id: int, data: dict, admin=Depends(get_current_admin)):
    allowed = {"name", "keyword", "content_text", "buttons_text", "status"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates: return {"ok": True}
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(pub_id)
            await cur.execute(f"UPDATE group_kuaisufabu SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}

# ── Lotteries ────────────────────────────────────────────
@app.get(f"{PREFIX}/lotteries")
async def list_lotteries(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM group_choujiang ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return [{cols[i]: (str(r[i]) if isinstance(r[i], datetime) else r[i]) for i in range(len(cols))} for r in rows]

# ── Users ────────────────────────────────────────────────
@app.get(f"{PREFIX}/users")
async def list_users(search: str = "", admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if search: await cur.execute("SELECT * FROM users WHERE username LIKE %s OR first_name LIKE %s OR CAST(user_id AS CHAR) LIKE %s ORDER BY created_at DESC", (f"%{search}%", f"%{search}%", f"%{search}%"))
            else: await cur.execute("SELECT * FROM users ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return [{cols[i]: (str(r[i]) if isinstance(r[i], datetime) else r[i]) for i in range(len(cols))} for r in rows]

@app.put(f"{PREFIX}/users/{{user_id}}")
async def update_user(user_id: int, data: UserUpdate, admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates: return {"ok": True}
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(user_id)
            await cur.execute(f"UPDATE users SET {', '.join(parts)} WHERE user_id=%s", vals)
    return {"ok": True}

# ── Channels ─────────────────────────────────────────────
@app.get(f"{PREFIX}/channels")
async def list_channels(search: str = "", admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if search: await cur.execute("SELECT * FROM pindao WHERE title LIKE %s OR username LIKE %s ORDER BY created_at DESC", (f"%{search}%", f"%{search}%"))
            else: await cur.execute("SELECT * FROM pindao ORDER BY created_at DESC")
            rows = await cur.fetchall()
    return [{"chat_id": r[0], "title": r[1], "username": r[2], "created_at": str(r[3])} for r in rows]

@app.put(f"{PREFIX}/channels/{{chat_id}}")
async def update_channel(chat_id: int, data: GroupInfoUpdate, admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates: return {"ok": True}
    parts, vals = [], []
    for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
    vals.append(chat_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE pindao SET {', '.join(parts)} WHERE chat_id=%s", vals)
    return {"ok": True}

# ── Bot Tokens ───────────────────────────────────────────
@app.get(f"{PREFIX}/bot-tokens")
async def list_bot_tokens(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, owner_id, bot_username, db_name, pid, status, created_at FROM bot_tokens ORDER BY id DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return [{cols[i]: (str(r[i]) if isinstance(r[i], datetime) else r[i]) for i in range(len(cols))} for r in rows]

@app.post(f"{PREFIX}/bot-tokens")
async def create_bot_token(data: BotTokenCreate, admin=Depends(get_current_admin)):
    from crypto_utils import encrypt_token
    pool = await get_db_pool()
    encrypted = encrypt_token(data.bot_token)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO bot_tokens (owner_id, bot_token, bot_username) VALUES (%s,%s,%s)", (data.owner_id, encrypted, data.bot_username))
            return {"ok": True, "id": cur.lastrowid}

@app.delete(f"{PREFIX}/bot-tokens/{{token_id}}")
async def delete_bot_token_api(token_id: int, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 先查出该 Bot 的 db_name 和 pid
            await cur.execute("SELECT db_name, pid FROM bot_tokens WHERE id=%s", (token_id,))
            row = await cur.fetchone()
            db_name, pid = row if row else (None, None)

            # 杀掉正在运行的 Bot 进程
            if pid:
                try:
                    os.kill(pid, 9)
                except Exception:
                    pass

            # 删除 bot_tokens 记录
            await cur.execute("DELETE FROM bot_tokens WHERE id=%s", (token_id,))

            # 删除对应的数据库
            if db_name:
                try:
                    await cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
                except Exception:
                    pass

    return {"ok": True}

# ── Subscriptions ────────────────────────────────────────
@app.get(f"{PREFIX}/subscriptions")
async def list_subscriptions(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM group_subscriptions ORDER BY expires_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return [{cols[i]: (str(r[i]) if isinstance(r[i], datetime) else r[i]) for i in range(len(cols))} for r in rows]

@app.post(f"{PREFIX}/subscriptions")
async def add_subscription(data: SubscriptionUpdate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""INSERT INTO group_subscriptions (chat_id, feature, expires_at)
                VALUES (%s,%s,DATE_ADD(NOW(), INTERVAL %s DAY))
                ON DUPLICATE KEY UPDATE expires_at = IF(expires_at > NOW(), DATE_ADD(expires_at, INTERVAL %s DAY), DATE_ADD(NOW(), INTERVAL %s DAY))""",
                (data.chat_id, data.feature, data.days, data.days, data.days))
    return {"ok": True}

@app.delete(f"{PREFIX}/subscriptions/{{sub_id}}")
async def delete_subscription(sub_id: int, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_subscriptions WHERE id=%s", (sub_id,))
    return {"ok": True}

class SubscriptionEditRequest(BaseModel):
    chat_id: Optional[int] = None
    feature: Optional[str] = None
    days: Optional[int] = None
    expires_at: Optional[str] = None

@app.put(f"{PREFIX}/subscriptions/{{sub_id}}")
async def update_subscription(sub_id: int, data: SubscriptionEditRequest, admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates: return {"ok": True}
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items():
                parts.append(f"{validate_column_name(k)}=%s")
                vals.append(v)
            vals.append(sub_id)
            await cur.execute(f"UPDATE group_subscriptions SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}

# ── DB Backup ─────────────────────────────────────────────
@app.get(f"{PREFIX}/db/backup")
async def db_backup(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    sql_lines = ["-- GouerAdmin Database Backup", f"-- {datetime.now()}", ""]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW TABLES")
            tables = [r[0] for r in await cur.fetchall()]
            for table in tables:
                await cur.execute(f"SELECT * FROM `{validate_table_name(table)}`")
                rows = await cur.fetchall()
                cols = [d[0] for d in cur.description]
                if not rows: continue
                sql_lines.append(f"\n-- Table: {table}")
                col_names = ", ".join(f"`{c}`" for c in cols)
                for row in rows:
                    vals = []
                    for v in row:
                        if v is None: vals.append("NULL")
                        elif isinstance(v, (int, float)): vals.append(str(v))
                        else: vals.append("'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'")
                    sql_lines.append(f"INSERT INTO `{table}` ({col_names}) VALUES ({', '.join(vals)});")
    sql = "\n".join(sql_lines)
    from fastapi.responses import Response
    return Response(content=sql, media_type="application/sql", headers={"Content-Disposition": f"attachment; filename=gouer_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"})

# ── Points ───────────────────────────────────────────────
@app.get(f"{PREFIX}/points")
async def list_points(chat_id: int = None, user_id: int = None, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if chat_id and user_id:
                await cur.execute("SELECT chat_id, user_id, points FROM user_points WHERE chat_id=%s AND user_id=%s", (chat_id, user_id))
            elif chat_id:
                await cur.execute("SELECT chat_id, user_id, points FROM user_points WHERE chat_id=%s ORDER BY points DESC", (chat_id,))
            else:
                await cur.execute("SELECT chat_id, user_id, points FROM user_points ORDER BY points DESC")
            rows = await cur.fetchall()
    return [{"chat_id": r[0], "user_id": r[1], "points": r[2]} for r in rows]

class PointsUpdate(BaseModel):
    points: int

@app.put(f"{PREFIX}/points/{{chat_id}}/{{user_id}}")
async def update_user_points_api(chat_id: int, user_id: int, data: PointsUpdate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO user_points (chat_id, user_id, points) VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE points = VALUES(points)
            """, (chat_id, user_id, data.points))
    return {"ok": True, "points": data.points}

# ── DB Manager ───────────────────────────────────────────
_db_pools = {}  # db_name -> pool

async def _get_pool_for(db_name: str = ""):
    if not db_name:
        return await get_db_pool()
    if db_name not in _db_pools:
        _db_pools[db_name] = await aiomysql.create_pool(
            host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"), password=os.getenv("DB_PASS", ""),
            db=db_name, autocommit=True, minsize=1, maxsize=5)
    return _db_pools[db_name]

@app.get(f"{PREFIX}/db/databases")
async def db_list_databases(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW DATABASES")
            dbs = [r[0] for r in await cur.fetchall()]
            # 过滤系统库
            return [d for d in dbs if d not in ("information_schema","mysql","performance_schema","sys","phpmyadmin")]

@app.get(f"{PREFIX}/db/tables")
async def db_list_tables(db: str = "", admin=Depends(get_current_admin)):
    pool = await _get_pool_for(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW TABLES")
            return {"tables": [r[0] for r in await cur.fetchall()], "db": db or os.getenv("DB","")}

@app.get(f"{PREFIX}/db/tables/{{table}}")
async def db_table_info(table: str, db: str = "", admin=Depends(get_current_admin)):
    table = validate_table_name(table)
    pool = await _get_pool_for(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"DESCRIBE `{table}`")
            columns = [{"field": r[0], "type": r[1], "null": r[2], "key": r[3], "default": str(r[4]), "extra": r[5]} for r in await cur.fetchall()]
            await cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            row_count = (await cur.fetchone())[0]
    return {"table": table, "columns": columns, "row_count": row_count, "db": db or os.getenv("DB","")}

@app.get(f"{PREFIX}/db/tables/{{table}}/rows")
async def db_table_rows(table: str, page: int = 1, limit: int = 50, db: str = "", admin=Depends(get_current_admin)):
    table = validate_table_name(table)
    offset = (page - 1) * limit
    pool = await _get_pool_for(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT COUNT(*) FROM `{table}`"); total = (await cur.fetchone())[0]
            await cur.execute(f"SELECT * FROM `{table}` LIMIT {int(limit)} OFFSET {int(offset)}")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    data = []
    for r in rows:
        row_dict = {}
        for i, c in enumerate(cols):
            v = r[i]
            if isinstance(v, datetime): v = str(v)
            elif isinstance(v, bytes): v = f"<BLOB {len(v)} bytes>"
            row_dict[c] = v
        data.append(row_dict)
    return {"total": total, "page": page, "limit": limit, "columns": cols, "rows": data, "db": db or os.getenv("DB","")}

@app.post(f"{PREFIX}/db/query")
async def db_query(req: DBQueryRequest, admin=Depends(get_current_admin)):
    sql_upper = req.sql.strip().upper()
    if not any(sql_upper.startswith(w) for w in ("SELECT","SHOW","DESCRIBE","EXPLAIN")):
        raise HTTPException(status_code=400, detail="仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN")
    for kw in ("DROP","DELETE","UPDATE","INSERT","ALTER","CREATE","TRUNCATE"):
        if kw in sql_upper:
            raise HTTPException(status_code=400, detail="不允许写操作")
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(req.sql[:req.limit * 10])
                rows = await cur.fetchmany(req.limit)
                cols = [d[0] for d in cur.description] if cur.description else []
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL 错误: {str(e)}")
    data = []
    for r in rows:
        row_dict = {}
        for i, c in enumerate(cols):
            v = r[i]
            if isinstance(v, datetime): v = str(v)
            elif isinstance(v, bytes): v = f"<BLOB {len(v)} bytes>"
            row_dict[c] = v
        data.append(row_dict)
    return {"columns": cols, "rows": data, "count": len(data)}

# ── Code Editor (with hot-reload) ────────────────────────
_PLUGINS_DIR = os.path.realpath(os.getenv("PLUGINS_DIR", os.path.join(os.path.dirname(__file__), "..", "plugins")))
_BOT_DIR = os.path.realpath(os.getenv("BOT_DIR", os.path.join(os.path.dirname(__file__), "..", "bot")))
_ALLOWED_EXT = {".py", ".json", ".env", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".md"}
_loaded_modules = {}

def _walk_files(base: str, scope: str) -> list:
    files = []
    if not os.path.isdir(base): return files
    for root, dirs, dnames in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "__MACOSX", ".uploads")]
        for fname in sorted(dnames):
            ext = os.path.splitext(fname)[1].lower()
            if ext in _ALLOWED_EXT and not fname.startswith("."):
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, base)
                files.append({"name": rel, "path": rel, "size": os.path.getsize(full), "scope": scope})
    return files

class FileSaveRequest(BaseModel):
    path: str
    content: str
    scope: str = "plugins"

@app.get(f"{PREFIX}/code/tree")
async def code_tree(admin=Depends(get_current_admin)):
    return _walk_files(_PLUGINS_DIR, "plugins") + _walk_files(_BOT_DIR, "bot")

@app.get(f"{PREFIX}/code/file")
async def code_read(path: str, scope: str = "plugins", admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if scope == "plugins" else _BOT_DIR
    full = os.path.realpath(os.path.join(base, path))
    if not full.startswith(base): raise HTTPException(status_code=403, detail="路径越权")
    if not os.path.isfile(full): raise HTTPException(status_code=404, detail="文件不存在")
    try:
        with open(full, "r", encoding="utf-8") as f: content = f.read()
    except Exception:
        with open(full, "r", encoding="latin-1") as f: content = f.read()
    return {"path": path, "content": content, "scope": scope}

@app.put(f"{PREFIX}/code/file")
async def code_save(req: FileSaveRequest, admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if req.scope == "plugins" else _BOT_DIR
    full = os.path.realpath(os.path.join(base, req.path))
    if not full.startswith(base): raise HTTPException(status_code=403, detail="路径越权")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f: f.write(req.content)
    if full.endswith(".py"):
        mod_name = os.path.splitext(req.path)[0].replace("/", ".").replace("\\", ".")
        try:
            if mod_name in sys.modules:
                import importlib; importlib.reload(sys.modules[mod_name])
        except: pass
    return {"ok": True, "path": req.path}

@app.delete(f"{PREFIX}/code/file")
async def code_delete(path: str, scope: str = "plugins", admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if scope == "plugins" else _BOT_DIR
    full = os.path.realpath(os.path.join(base, path))
    if not full.startswith(base): raise HTTPException(status_code=403)
    os.remove(full)
    return {"ok": True}

@app.post(f"{PREFIX}/code/create")
async def code_create(scope: str = "plugins", name: str = "", admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if scope == "plugins" else _BOT_DIR
    safe = name.replace("..", "").replace("/", "").replace("\\", "")
    if not safe.endswith(".py"): safe += ".py"
    full = os.path.join(base, safe)
    if os.path.exists(full): raise HTTPException(status_code=400, detail="文件已存在")
    with open(full, "w") as f: f.write("# New plugin\n")
    return {"ok": True, "path": safe}

@app.put(f"{PREFIX}/code/rename")
async def code_rename(old: str = "", new: str = "", scope: str = "plugins", admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if scope == "plugins" else _BOT_DIR
    old_full = os.path.realpath(os.path.join(base, old))
    if not old_full.startswith(base): raise HTTPException(status_code=403)
    safe = new.replace("..", "").replace("/", "").replace("\\", "")
    new_full = os.path.join(os.path.dirname(old_full), safe)
    if os.path.exists(new_full): raise HTTPException(status_code=400, detail="目标文件已存在")
    os.rename(old_full, new_full)
    return {"ok": True, "path": os.path.relpath(new_full, base)}

@app.post(f"{PREFIX}/code/reload")
async def code_reload(path: str = "", admin=Depends(get_current_admin)):
    if not path: return {"reloaded": []}
    mod_name = os.path.splitext(path)[0].replace("/", ".").replace("\\", ".")
    import importlib; reloaded = []
    for name, mod in list(sys.modules.items()):
        if name == mod_name or name.startswith(mod_name + "."):
            try: importlib.reload(mod); reloaded.append(name)
            except: pass
    return {"reloaded": reloaded}

# ── Child Bot Monitor ────────────────────────────────────
@app.get(f"{PREFIX}/bots/status")
async def bots_status(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    bots = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, bot_username, db_name, pid, status FROM bot_tokens ORDER BY id")
            for row in await cur.fetchall():
                bid, uname, db_name, pid, status = row
                running = False
                if pid:
                    try: os.kill(pid, 0); running = True
                    except: pass
                bots.append({"id": bid, "username": uname, "db": db_name, "pid": pid, "status": status, "running": running})
    return bots

@app.get(f"{PREFIX}/bots/main/status")
async def main_bot_status(admin=Depends(get_current_admin)):
    running = False; pid = 0
    for line in subprocess.run(["ps","aux"],capture_output=True,text=True).stdout.split("\n"):
        if "Admin/bot/main.py" in line and "grep" not in line:
            try: pid = int(line.split()[1]); running = True
            except: pass
    log_size = os.path.getsize("/var/log/gouer_main_bot.log") if os.path.exists("/var/log/gouer_main_bot.log") else 0
    return {"running": running, "pid": pid, "log_size": log_size}

@app.get(f"{PREFIX}/bots/main/log")
async def main_bot_log(tail: int = 100, admin=Depends(get_current_admin)):
    lf = "/var/log/gouer_main_bot.log"
    if not os.path.exists(lf): return {"lines": []}
    with open(lf) as f: return {"lines": [l.rstrip() for l in f.readlines()[-tail:]]}

@app.get(f"{PREFIX}/bots/{{bot_id}}/log")
async def bot_log(bot_id: int, tail: int = 100, admin=Depends(get_current_admin)):
    log_file = f"/var/log/gouer_child_{bot_id}.log"
    if not os.path.exists(log_file): return {"lines": []}
    with open(log_file, "r") as f:
        return {"lines": [l.rstrip() for l in f.readlines()[-tail:]]}

def _preload_plugins():
    import logging as _logging
    _log = _logging.getLogger("plugin_loader")
    if os.path.isdir(_PLUGINS_DIR):
        for fname in os.listdir(_PLUGINS_DIR):
            if fname.endswith(".py") and not fname.startswith("_"):
                try:
                    sys.path.insert(0, _PLUGINS_DIR)
                    __import__(fname[:-3])
                    _log.info(f"Plugin loaded: {fname}")
                except Exception as e:
                    _log.warning(f"Plugin load failed {fname}: {e}")

_preload_plugins()

# ── Bot Process Control ──────────────────────────────────
import subprocess, signal

_BOT_MAIN = os.path.join(_BOT_DIR, "main.py") if os.path.isdir(_BOT_DIR) else ""
_BOT_PYTHON = os.getenv("BOT_PYTHON", sys.executable)
_bot_processes = {}  # name → subprocess.Popen

@app.post(f"{PREFIX}/bots/start-all")
async def start_all_bots(admin=Depends(get_current_admin)):
    if not _BOT_MAIN or not os.path.isfile(_BOT_MAIN):
        raise HTTPException(status_code=400, detail="Bot 目录未配置")
    log_f = open("/var/log/gouer_main_bot.log", "a")
    p = subprocess.Popen([_BOT_PYTHON, _BOT_MAIN], cwd=_BOT_DIR, stdout=log_f, stderr=log_f, start_new_session=True)
    _bot_processes["main"] = p
    return {"started": [{"name": "main", "pid": p.pid}]}

@app.post(f"{PREFIX}/bots/stop-all")
async def stop_all_bots(admin=Depends(get_current_admin)):
    stopped = []
    for name, p in list(_bot_processes.items()):
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            stopped.append({"name": name, "pid": p.pid})
        except: pass
    _bot_processes.clear()
    # 也杀可能遗漏的
    try:
        subprocess.run(["pkill", "-f", f"{_BOT_DIR}/main.py"], timeout=5)
    except: pass
    return {"stopped": stopped}
#reboot
@app.post(f"{PREFIX}/bots/restart-all")
async def restart_all_bots(admin=Depends(get_current_admin)):
    await stop_all_bots(admin=admin)
    await asyncio.sleep(2)
    return await start_all_bots(admin=admin)

# ── System / Config ──────────────────────────────────────
@app.get(f"{PREFIX}/system/obfuscated-paths")
async def get_obfuscated_paths(admin=Depends(get_current_admin)):
    return {"paths": OBF}

@app.get(f"{PREFIX}/system/config")
async def get_system_config(admin=Depends(get_current_admin)):
    return {
        "db_host": os.getenv("DB_HOST", "127.0.0.1"),
        "db_port": os.getenv("DB_PORT", "3306"),
        "db_name": os.getenv("DB", ""),
        "bot_username": os.getenv("BOT_USERNAME", ""),
        "has_payment": bool(os.getenv("MYQB_APP_ID", "")),
        "has_encryption": bool(os.getenv("KEY", "")),
        "ai_price": os.getenv("AI_PRICE", "30"),
        "card_price": os.getenv("CARD_PRICE", "20"),
        "push_channel": os.getenv("PUSH", ""),
    }

@app.get(OBF["health_path"])
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}
import mimetypes
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

_static_dir = os.path.join(os.path.dirname(__file__), "..", "admin_frontend", "dist")
_admin_path = OBF["admin_path"]

def _fix_and_inject(html_content: str) -> str:
    html_content = html_content.replace(" crossorigin", "")
    base_tag = f'<base href="{_admin_path}/">'
    meta_tag = f'<meta name="api-prefix" content="{OBF["api_prefix"]}">'
    return html_content.replace("<head>", f"<head>{meta_tag}{base_tag}", 1)

def _serve_file_or_spa(rest: str = ""):
    if rest:
        fp = os.path.join(_static_dir, rest)
    else:
        fp = os.path.join(_static_dir, "index.html")
    # 防止路径穿越
    real = os.path.realpath(fp)
    if not real.startswith(os.path.realpath(_static_dir)):
        fp = os.path.join(_static_dir, "index.html")

    if os.path.isfile(fp) and rest:
        mt, _ = mimetypes.guess_type(fp)
        return FileResponse(fp, media_type=mt)

    html = _fix_and_inject(open(os.path.join(_static_dir, "index.html")).read())
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


if os.path.exists(_static_dir):
    @app.api_route(f"{_admin_path}", methods=["GET", "HEAD"])
    async def serve_admin_redirect(request: Request):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"{_admin_path}/")

    @app.api_route(f"{_admin_path}/", methods=["GET", "HEAD"])
    async def serve_admin(request: Request):
        return _serve_file_or_spa()

    @app.api_route(f"{_admin_path}/{{rest:path}}", methods=["GET", "HEAD"])
    async def serve_admin_spa(request: Request, rest: str):
        return _serve_file_or_spa(rest)


def _save_env(key: str, value: str):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r") as f:
        lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)


def _render_qr_ascii(data: str) -> str:
    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(data)
        qr.make(fit=True)
        # 用终端 ANSI 反转色输出
        matrix = qr.get_matrix()
        lines = []
        for row in matrix:
            line = ""
            for cell in row:
                if cell:
                    line += "\033[47m  \033[0m"
                else:
                    line += "\033[40m  \033[0m"
            lines.append(line)
        return "\n".join(lines)
    except Exception:
        return "(QR 码渲染失败，请通过 Web 管理面板查看二维码)"


async def _startup_clean():
    import signal as _sig
    killed = 0
    for proc in subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout.split("\n"):
        if "Admin/bot/main.py" in proc and "grep" not in proc:
            try:
                pid = int(proc.split()[1])
                os.kill(pid, _sig.SIGTERM)
                killed += 1
            except: pass
    logger.info(f"Startup: killed {killed} stale bot process(es)")
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE bot_tokens SET pid=0 WHERE pid>0")
                logger.info(f"Startup: cleared {cur.rowcount} bot_tokens PIDs")
    except Exception as e:
        logger.warning(f"Startup clean DB failed: {e}")

if __name__ == "__main__":
    import uvicorn, asyncio as _asyncio
    port = int(os.getenv("ADMIN_PORT", "8800"))

    if not ADMIN_2FA_SECRET:
        _save_env("ADMIN_2FA_SECRET", _current_2fa_secret)
        os.environ["ADMIN_2FA_SECRET"] = _current_2fa_secret

    print(f"""
  GouerAdmin v1.0  |  Port: {port}  |  2FA: {_current_2fa_secret}
    """)
    import subprocess as _sp, signal as _sig
    killed = 0
    for line in _sp.run(["ps", "aux"], capture_output=True, text=True).stdout.split("\n"):
        if "Admin/bot/main.py" in line and "grep" not in line:
            try: os.kill(int(line.split()[1]), _sig.SIGTERM); killed += 1
            except: pass
    if killed: print(f"  Cleaned: {killed} stale bot process(es)")
    try:
        import aiomysql as _am
        async def _clean_pids():
            p = await _am.create_pool(host=os.getenv("DB_HOST","127.0.0.1"),port=int(os.getenv("DB_PORT","3306")),user=os.getenv("DB_USER","root"),password=os.getenv("DB_PASS",""),db=os.getenv("DB","test"),autocommit=True)
            async with p.acquire() as c:
                async with c.cursor() as cur: await cur.execute("UPDATE bot_tokens SET pid=0 WHERE pid>0")
            p.close(); await p.wait_closed()
        _asyncio.get_event_loop().run_until_complete(_clean_pids())
    except Exception as e: print(f"  DB clean warning: {e}")
    uvicorn.run(app, host="0.0.0.0", port=port)
