# Auth module — JWT, 2FA, CAPTCHA, password management, security middleware
import os
import re
import io
import time
import random
import base64
import hashlib
import secrets
import asyncio
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Depends, Request, APIRouter
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
import pyotp
from PIL import Image, ImageDraw, ImageFont

from config import PREFIX

router = APIRouter()

# ── JWT config ────────────────────────────────────────
JWT_SECRET = os.getenv("KEY", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
ADMIN_2FA_SECRET = os.getenv("ADMIN_2FA_SECRET", "")

# ── Password hashing (PBKDF2) ─────────────────────────
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

# ── JWT token helpers ─────────────────────────────────
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

# ── XSS input validation ──────────────────────────────
_XSS_PATTERN = re.compile(r"<script|javascript:|on\w+\s*=", re.IGNORECASE)

def _validate_no_xss(value: str) -> str:
    if value and _XSS_PATTERN.search(value):
        raise HTTPException(status_code=400, detail="输入包含非法内容")
    return value

# ── Security headers middleware ───────────────────────
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# ── Login rate limiter ────────────────────────────────
_login_attempts = {}  # IP → [timestamps]

async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.endswith("/login") and request.method == "POST":
        ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        if ip not in _login_attempts:
            _login_attempts[ip] = []
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < 60]
        if len(_login_attempts[ip]) >= 10:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请 60 秒后再试"})
        _login_attempts[ip].append(now)
    return await call_next(request)

# ── CAPTCHA — 4-char distorted image ──────────────────
_captchas = {}  # captcha_id → {"answer": "AB12", "expires": timestamp}

def _generate_captcha_image(code: str) -> str:
    w, h = 140, 52
    img = Image.new("RGB", (w, h), (245, 247, 250))
    draw = ImageDraw.Draw(img)
    # noise lines
    for _ in range(5):
        x1 = random.randint(0, w); y1 = random.randint(0, h)
        x2 = random.randint(0, w); y2 = random.randint(0, h)
        draw.line([(x1, y1), (x2, y2)],
                  fill=(random.randint(120, 200), random.randint(120, 200), random.randint(120, 200)), width=2)
    # noise dots
    for _ in range(80):
        draw.point((random.randint(0, w), random.randint(0, h)),
                    fill=(random.randint(60, 180), random.randint(60, 180), random.randint(60, 180)))
    # draw characters with random offset
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    except Exception:
        font = ImageFont.load_default()
    for i, ch in enumerate(code):
        x = 14 + i * 30 + random.randint(-3, 3)
        y = 10 + random.randint(-4, 4)
        draw.text((x, y), ch,
                  fill=(random.randint(10, 100), random.randint(10, 100), random.randint(10, 100)), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def _generate_captcha() -> dict:
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(random.choices(chars, k=4))
    cid = secrets.token_hex(8)
    _captchas[cid] = {"answer": code, "expires": time.time() + 300}
    img_b64 = _generate_captcha_image(code)
    return {"captcha_id": cid, "image": f"data:image/png;base64,{img_b64}", "expires_in": 300}

def _verify_captcha(captcha_id: str, captcha_answer: str) -> bool:
    entry = _captchas.pop(captcha_id, None)
    if not entry or time.time() > entry["expires"]:
        return False
    return entry["answer"].upper() == str(captcha_answer).strip().upper()

# ── .env persistence ──────────────────────────────────
def save_env(key: str, value: str):
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

# ══════════════════════════════════════════════════════
#  Auth API Routes
# ══════════════════════════════════════════════════════

from models import LoginRequest, PasswordChangeRequest, UsernameChangeRequest, TwoFAResetRequest

# ── CAPTCHA ───────────────────────────────────────────
@router.post("/captcha")
async def api_get_captcha():
    return _generate_captcha()

# ── Login ─────────────────────────────────────────────
@router.post("/login")
async def api_login(req: LoginRequest):
    if not req.captcha_id or not req.captcha_answer:
        raise HTTPException(status_code=400, detail="请输入验证码")
    if not _verify_captcha(req.captcha_id, req.captcha_answer):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    if req.username != ADMIN_USER:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(req.password, _admin_salt, _admin_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not req.totp_code:
        raise HTTPException(status_code=400, detail="请输入 Google 验证码")
    if not _totp.verify(req.totp_code):
        raise HTTPException(status_code=401, detail="Google 验证码错误")

    token = create_access_token({"sub": req.username, "role": "admin"})
    must_change = (ADMIN_PASS == "admin123")
    return {"access_token": token, "token_type": "bearer", "admin": req.username, "must_change_password": must_change}

# ── Change password ───────────────────────────────────
@router.post("/change-password")
async def change_password(req: PasswordChangeRequest, admin=Depends(get_current_admin)):
    global _admin_salt, _admin_hash
    if not verify_password(req.old_password, _admin_salt, _admin_hash):
        raise HTTPException(status_code=401, detail="原密码错误")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    if req.new_password == "admin123":
        raise HTTPException(status_code=400, detail="不能使用默认密码")
    _admin_salt, _admin_hash = _hash_password(req.new_password)
    save_env("ADMIN_PASS", req.new_password)
    os.environ["ADMIN_PASS"] = req.new_password
    return {"ok": True}

# ── Change username ───────────────────────────────────
@router.post("/change-username")
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
    save_env("ADMIN_USER", new_name)
    os.environ["ADMIN_USER"] = new_name
    return {"ok": True, "username": new_name}

# ── 2FA setup QR code ─────────────────────────────────
@router.get("/2fa-setup")
async def get_2fa_setup(confirm: bool = False, admin=Depends(get_current_admin)):
    if not confirm:
        return {"require_confirm": True, "hint": "传 confirm=true 确认查看"}
    import qrcode as _qrcode
    secret = _current_2fa_secret
    uri = _totp.provisioning_uri(name=ADMIN_USER, issuer_name="GouerAdmin")
    img = _qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return {"secret": secret, "qr_code": f"data:image/png;base64,{qr_b64}", "uri": uri}

# ── Reset 2FA ─────────────────────────────────────────
@router.post("/2fa-reset")
async def reset_2fa(req: TwoFAResetRequest, admin=Depends(get_current_admin)):
    global _totp, _current_2fa_secret
    if not verify_password(req.password, _admin_salt, _admin_hash):
        raise HTTPException(status_code=401, detail="密码错误")
    if not _totp.verify(req.totp_code):
        raise HTTPException(status_code=401, detail="Google 验证码错误")

    _current_2fa_secret = pyotp.random_base32()
    _totp = pyotp.TOTP(_current_2fa_secret)
    save_env("ADMIN_2FA_SECRET", _current_2fa_secret)
    os.environ["ADMIN_2FA_SECRET"] = _current_2fa_secret

    import qrcode as _qrcode
    uri = _totp.provisioning_uri(name=ADMIN_USER, issuer_name="GouerAdmin")
    img = _qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return {"secret": _current_2fa_secret, "qr_code": f"data:image/png;base64,{qr_b64}", "uri": uri}
