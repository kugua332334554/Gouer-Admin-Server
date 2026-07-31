# Users CRUD router
from datetime import datetime
from fastapi import APIRouter, Depends
from models import UserUpdate
from database import resolve_data_pool, validate_column_name, rows_to_dicts
from auth import get_current_admin

router = APIRouter()

@router.get("/users")
async def list_users(search: str = "", db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if search:
                await cur.execute(
                    "SELECT * FROM users WHERE username LIKE %s OR first_name LIKE %s OR CAST(user_id AS CHAR) LIKE %s "
                    "ORDER BY created_at DESC",
                    (f"%{search}%", f"%{search}%", f"%{search}%"))
            else:
                await cur.execute("SELECT * FROM users ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)

@router.put("/users/{user_id}")
async def update_user(user_id: int, data: UserUpdate, db: str = "", admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates: return {"ok": True}
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(user_id)
            await cur.execute(f"UPDATE users SET {', '.join(parts)} WHERE user_id=%s", vals)
    return {"ok": True}
