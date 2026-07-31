# Channel CRUD router
from fastapi import APIRouter, Depends
from models import GroupInfoUpdate
from database import resolve_data_pool, validate_column_name
from auth import get_current_admin

router = APIRouter()

@router.get("/channels")
async def list_channels(search: str = "", db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if search:
                await cur.execute(
                    "SELECT * FROM pindao WHERE title LIKE %s OR username LIKE %s ORDER BY created_at DESC",
                    (f"%{search}%", f"%{search}%"))
            else:
                await cur.execute("SELECT * FROM pindao ORDER BY created_at DESC")
            rows = await cur.fetchall()
    return [{"chat_id": r[0], "title": r[1], "username": r[2], "created_at": str(r[3])} for r in rows]

@router.put("/channels/{chat_id}")
async def update_channel(chat_id: int, data: GroupInfoUpdate, db: str = "", admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates: return {"ok": True}
    parts, vals = [], []
    for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
    vals.append(chat_id)
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE pindao SET {', '.join(parts)} WHERE chat_id=%s", vals)
    return {"ok": True}
