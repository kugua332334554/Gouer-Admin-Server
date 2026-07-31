# Keyword reply CRUD router
from datetime import datetime
from fastapi import APIRouter, Depends
from models import KeywordReplyCreate
from database import resolve_data_pool, validate_column_name, rows_to_dicts
from auth import get_current_admin

router = APIRouter()

@router.get("/keyword-reply")
async def list_keyword_reply(chat_id: int = None, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if chat_id:
                await cur.execute(
                    "SELECT id, chat_id, keyword, reply_text, media_type, media_file_id, "
                    "buttons_text, match_mode, status, created_at "
                    "FROM group_keyword_reply WHERE chat_id=%s ORDER BY id ASC", (chat_id,))
            else:
                await cur.execute(
                    "SELECT id, chat_id, keyword, reply_text, media_type, media_file_id, "
                    "buttons_text, match_mode, status, created_at "
                    "FROM group_keyword_reply ORDER BY id ASC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)

@router.post("/keyword-reply")
async def create_keyword_reply(data: KeywordReplyCreate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO group_keyword_reply (chat_id, keyword, match_mode, reply_text, buttons_text, status) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (data.chat_id, data.keyword, data.match_mode, data.reply_text, data.buttons_text, data.status))
            return {"ok": True, "id": cur.lastrowid}

@router.put("/keyword-reply/{reply_id}")
async def update_keyword_reply(reply_id: int, data: dict, db: str = "", admin=Depends(get_current_admin)):
    allowed = {"keyword", "reply_text", "match_mode", "buttons_text", "status"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates: return {"ok": True}
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(reply_id)
            await cur.execute(f"UPDATE group_keyword_reply SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}

@router.delete("/keyword-reply/{reply_id}")
async def delete_keyword_reply(reply_id: int, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_keyword_reply WHERE id=%s", (reply_id,))
    return {"ok": True}
