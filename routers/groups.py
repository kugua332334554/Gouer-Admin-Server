# Group detail + CRUD router
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from models import (GroupInfoUpdate, GroupVerifyUpdate, WelcomeSettingsUpdate,
    NightSettingsUpdate, AntispamUpdate, ChatAISettings, ToggleSettings,
    PointsSettings, SpeakCheckSettings, AutodeleteUpdate, CardSettingsUpdate, PermissionUpdate)
from database import get_db_pool, resolve_data_pool, validate_table_name, update_generic
from auth import get_current_admin

router = APIRouter()

# ── List groups ───────────────────────────────────────
@router.get("/groups")
async def list_groups(search: str = "", db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if search:
                await cur.execute(
                    "SELECT chat_id, title, username, type, created_at FROM qunzu "
                    "WHERE title LIKE %s OR username LIKE %s OR CAST(chat_id AS CHAR) LIKE %s "
                    "ORDER BY created_at DESC",
                    (f"%{search}%", f"%{search}%", f"%{search}%"))
            else:
                await cur.execute(
                    "SELECT chat_id, title, username, type, created_at FROM qunzu ORDER BY created_at DESC")
            rows = await cur.fetchall()
    return [{"chat_id": r[0], "title": r[1], "username": r[2], "type": r[3], "created_at": str(r[4])} for r in rows]

# ── Get group detail (all settings) ───────────────────
@router.get("/groups/{chat_id}")
async def get_group_detail(chat_id: int, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    result = {"chat_id": chat_id}
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # basic info
            await cur.execute("SELECT title, username, type, created_at FROM qunzu WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="群组不存在")
            result["title"], result["username"], result["type"], result["created_at"] = row[0], row[1], row[2], str(row[3])

            # verify settings
            await cur.execute("SELECT verify_status, verify_mode, verify_duration, verify_penalty FROM group_settings WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["verify"] = {"status": bool(row[0]), "mode": row[1], "duration": row[2], "penalty": row[3]} if row else {"status": False, "mode": "button", "duration": 1, "penalty": "mute"}

            # welcome
            await cur.execute("SELECT status, delete_time, delete_last, media_type, welcome_text, buttons_text FROM group_welcome WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["welcome"] = {"status": bool(row[0]) if row else False, "delete_time": row[1] if row else 0, "delete_last": bool(row[2]) if row else False, "media_type": row[3] if row else None, "welcome_text": row[4] if row else "", "buttons_text": row[5] if row else ""}

            # points
            await cur.execute("SELECT status, msg_points, ignore_stickers, delete_time FROM group_points_settings WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["points"] = {"status": bool(row[0]) if row else False, "msg_points": row[1] if row else 0, "ignore_stickers": bool(row[2]) if row else True, "delete_time": row[3] if row else 0}

            # night mode
            await cur.execute("SELECT status, start_hour, end_hour, notify FROM group_night WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["night"] = {"status": bool(row[0]) if row else False, "start_hour": row[1] if row else 0, "end_hour": row[2] if row else 6, "notify": bool(row[3]) if row else True}

            # AI
            await cur.execute("SELECT chat_enabled, chat_prompt, chat_trigger, audit_enabled, audit_penalty FROM group_ai WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["ai"] = {"chat_enabled": bool(row[0]) if row else False, "chat_prompt": row[1] if row else "", "chat_trigger": row[2] if row else "", "audit_enabled": bool(row[3]) if row else False, "audit_penalty": row[4] if row else "delete"}

            # toggle
            await cur.execute("SELECT * FROM group_toggle WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if row:
                tcols = [d[0] for d in cur.description]
                result["toggle"] = {tcols[i]: row[i] for i in range(len(tcols))}
            else:
                result["toggle"] = {"enabled": False}

            # speak check
            await cur.execute("SELECT * FROM group_message_check WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if row:
                mcols = [d[0] for d in cur.description]
                result["speak_check"] = {mcols[i]: row[i] for i in range(len(mcols))}
            else:
                result["speak_check"] = {"enabled": False}

            # card
            await cur.execute("SELECT enabled, template FROM group_card WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["card"] = {"enabled": bool(row[0]) if row else False, "template": row[1] if row else "default"}

            # autodelete
            await cur.execute("SELECT pin, photo, title, join_leave FROM group_autodelete WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["autodelete"] = {"pin": bool(row[0]) if row else False, "photo": bool(row[1]) if row else False, "title": bool(row[2]) if row else False, "join_leave": bool(row[3]) if row else False}

            # permission
            await cur.execute("SELECT permissions FROM group_permission WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["permission"] = row[0] if row else "all"

            # antispam
            await cur.execute("SELECT * FROM group_antispam WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                result["antispam"] = {cols[i]: row[i] for i in range(len(cols))}
            else:
                result["antispam"] = {"enabled": False}

            # nsfw
            await cur.execute("SELECT enabled, penalty, threshold_val FROM group_nsfw WHERE chat_id=%s", (chat_id,))
            row = await cur.fetchone()
            result["nsfw"] = {"enabled": bool(row[0]) if row else False, "penalty": row[1] if row else "delete", "threshold": float(row[2]) if row and row[2] else 0.8}

            # subscriptions
            await cur.execute("SELECT feature, expires_at FROM group_subscriptions WHERE chat_id=%s AND expires_at > NOW()", (chat_id,))
            subs = await cur.fetchall()
            result["subscriptions"] = [{"feature": s[0], "expires_at": str(s[1])} for s in subs]

            # counts
            await cur.execute("SELECT COUNT(*) FROM group_dingshi WHERE chat_id=%s AND status=TRUE", (chat_id,))
            result["dingshi_count"] = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM group_weijinci WHERE chat_id=%s AND status=TRUE", (chat_id,))
            result["weijinci_count"] = (await cur.fetchone())[0]

            # action log count
            clean_id = str(chat_id).replace("-", "")
            try:
                await cur.execute(f"SELECT COUNT(*) FROM `{validate_table_name(f'qunzu_{clean_id}')}`")
                result["action_count"] = (await cur.fetchone())[0]
            except Exception:
                result["action_count"] = 0
    return result

# ── Update group info ─────────────────────────────────
@router.put("/groups/{chat_id}")
async def update_group_info(chat_id: int, data: GroupInfoUpdate, db: str = "", admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return {"ok": True}
    parts, vals = [], []
    for k, v in updates.items():
        from database import validate_column_name
        parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
    vals.append(chat_id)
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE qunzu SET {', '.join(parts)} WHERE chat_id=%s", vals)
    return {"ok": True}

# ── Sub-resource updaters (all use update_generic) ────
@router.put("/groups/{chat_id}/verify")
async def update_group_verify(chat_id: int, data: GroupVerifyUpdate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""INSERT INTO group_settings (chat_id, verify_status, verify_mode, verify_duration, verify_penalty)
                VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE verify_status=VALUES(verify_status),
                verify_mode=VALUES(verify_mode), verify_duration=VALUES(verify_duration), verify_penalty=VALUES(verify_penalty)""",
                (chat_id, data.verify_status, data.verify_mode, data.verify_duration, data.verify_penalty))
    return {"ok": True}

@router.put("/groups/{chat_id}/welcome")
async def update_group_welcome(chat_id: int, data: WelcomeSettingsUpdate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_welcome", data.model_dump())(conn)
    return {"ok": True}

@router.put("/groups/{chat_id}/night")
async def update_group_night(chat_id: int, data: NightSettingsUpdate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_night", data.model_dump())(conn)
    return {"ok": True}

@router.put("/groups/{chat_id}/antispam")
async def update_group_antispam(chat_id: int, data: AntispamUpdate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_antispam", data.model_dump())(conn)
    return {"ok": True}

@router.put("/groups/{chat_id}/ai")
async def update_group_ai(chat_id: int, data: ChatAISettings, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_ai", data.model_dump())(conn)
    return {"ok": True}

@router.put("/groups/{chat_id}/toggle")
async def update_group_toggle(chat_id: int, data: ToggleSettings, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_toggle", data.model_dump())(conn)
    return {"ok": True}

@router.put("/groups/{chat_id}/points")
async def update_group_points(chat_id: int, data: PointsSettings, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_points_settings", data.model_dump())(conn)
    return {"ok": True}

@router.put("/groups/{chat_id}/speak-check")
async def update_speak_check(chat_id: int, data: SpeakCheckSettings, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_message_check", data.model_dump())(conn)
    return {"ok": True}

@router.put("/groups/{chat_id}/card")
async def update_group_card(chat_id: int, data: CardSettingsUpdate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_card", data.model_dump())(conn)
    return {"ok": True}

@router.put("/groups/{chat_id}/autodelete")
async def update_group_autodelete(chat_id: int, data: AutodeleteUpdate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_autodelete", data.model_dump())(conn)
    return {"ok": True}

@router.put("/groups/{chat_id}/permission")
async def update_group_permission(chat_id: int, data: PermissionUpdate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""INSERT INTO group_permission (chat_id, permissions) VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE permissions=VALUES(permissions)""",
                (chat_id, data.permissions))
    return {"ok": True}

# ── NSFW detection settings ───────────────────────────
from pydantic import BaseModel

class NsfwUpdate(BaseModel):
    enabled: Optional[bool] = None
    penalty: Optional[str] = None
    threshold: Optional[float] = None

@router.put("/groups/{chat_id}/nsfw")
async def update_group_nsfw(chat_id: int, data: NsfwUpdate, db: str = "", admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates: return {"ok": True}
    # map 'threshold' to 'threshold_val' DB column
    if "threshold" in updates:
        updates["threshold_val"] = updates.pop("threshold")
    from database import update_generic
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        await update_generic(chat_id, "group_nsfw", updates)(conn)
    return {"ok": True}
