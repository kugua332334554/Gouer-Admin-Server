# Subscriptions CRUD router
from datetime import datetime
from fastapi import APIRouter, Depends
from models import SubscriptionUpdate, SubscriptionEditRequest
from database import resolve_data_pool, validate_column_name, rows_to_dicts
from auth import get_current_admin

router = APIRouter()

@router.get("/subscriptions")
async def list_subscriptions(db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM group_subscriptions ORDER BY expires_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)

@router.post("/subscriptions")
async def add_subscription(data: SubscriptionUpdate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""INSERT INTO group_subscriptions (chat_id, feature, expires_at)
                VALUES (%s,%s,DATE_ADD(NOW(), INTERVAL %s DAY))
                ON DUPLICATE KEY UPDATE expires_at = IF(expires_at > NOW(),
                DATE_ADD(expires_at, INTERVAL %s DAY), DATE_ADD(NOW(), INTERVAL %s DAY))""",
                (data.chat_id, data.feature, data.days, data.days, data.days))
    return {"ok": True}

@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(sub_id: int, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_subscriptions WHERE id=%s", (sub_id,))
    return {"ok": True}

@router.put("/subscriptions/{sub_id}")
async def update_subscription(sub_id: int, data: SubscriptionEditRequest, db: str = "", admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates: return {"ok": True}
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(sub_id)
            await cur.execute(f"UPDATE group_subscriptions SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}
