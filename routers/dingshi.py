# Dingshi (scheduled messages) CRUD router
from datetime import datetime
from fastapi import APIRouter, Depends
from models import DingshiCreate
from database import resolve_data_pool, validate_column_name, rows_to_dicts
from auth import get_current_admin

router = APIRouter()

@router.get("/dingshi")
async def list_dingshi(chat_id: int = None, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if chat_id:
                await cur.execute("SELECT * FROM group_dingshi WHERE chat_id=%s ORDER BY created_at DESC", (chat_id,))
            else:
                await cur.execute("SELECT * FROM group_dingshi ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)

@router.post("/dingshi")
async def create_dingshi(data: DingshiCreate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO group_dingshi (chat_id,schedule_time,schedule_days,interval_minutes,content_text,buttons_text,status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (data.chat_id, data.schedule_time, data.schedule_days, data.interval_minutes,
                 data.content_text, data.buttons_text, data.status))
            return {"ok": True, "id": cur.lastrowid}

@router.put("/dingshi/{ding_id}")
async def update_dingshi(ding_id: int, data: dict, db: str = "", admin=Depends(get_current_admin)):
    allowed = {"schedule_time","schedule_days","interval_minutes","content_text","buttons_text","status"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates: return {"ok": True}
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(ding_id)
            await cur.execute(f"UPDATE group_dingshi SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}

@router.delete("/dingshi/{ding_id}")
async def delete_dingshi(ding_id: int, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_dingshi WHERE id=%s", (ding_id,))
    return {"ok": True}
