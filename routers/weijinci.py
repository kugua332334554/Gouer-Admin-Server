# Weijinci (banned words) CRUD router
from datetime import datetime
from fastapi import APIRouter, Depends
from models import KeywordCreate
from database import resolve_data_pool, validate_column_name, rows_to_dicts
from auth import get_current_admin

router = APIRouter()

@router.get("/weijinci")
async def list_weijinci(chat_id: int = None, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if chat_id:
                await cur.execute("SELECT * FROM group_weijinci WHERE chat_id=%s ORDER BY created_at DESC", (chat_id,))
            else:
                await cur.execute("SELECT * FROM group_weijinci ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)

@router.post("/weijinci")
async def create_weijinci(data: KeywordCreate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO group_weijinci (chat_id, word, penalty, mute_duration, status) VALUES (%s,%s,%s,%s,%s)",
                (data.chat_id, data.word, data.penalty, data.mute_duration, data.status))
            return {"ok": True, "id": cur.lastrowid}

@router.delete("/weijinci/{word_id}")
async def delete_weijinci(word_id: int, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_weijinci WHERE id=%s", (word_id,))
    return {"ok": True}

@router.put("/weijinci/{word_id}")
async def update_weijinci(word_id: int, data: dict, db: str = "", admin=Depends(get_current_admin)):
    allowed = {"word", "penalty", "mute_duration", "status"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates: return {"ok": True}
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(word_id)
            await cur.execute(f"UPDATE group_weijinci SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}
