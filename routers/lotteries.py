# Lotteries read-only router
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from database import resolve_data_pool, rows_to_dicts, validate_column_name
from auth import get_current_admin

router = APIRouter()

# 允许编辑的字段（参加条件 + 核心字段）
ALLOWED_FIELDS = {
    "title", "prize_description", "winner_count", "status",
    "join_chats", "name_contains", "bio_contains", "need_photo",
}

@router.get("/lotteries")
async def list_lotteries(db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM group_choujiang ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)

@router.patch("/lotteries/{lottery_id}")
async def update_lottery(lottery_id: int, data: dict, db: str = "", admin=Depends(get_current_admin)):
    updates = {k: v for k, v in data.items() if k in ALLOWED_FIELDS and v is not None}
    if not updates:
        return {"ok": True}
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 确认存在
            await cur.execute("SELECT id FROM group_choujiang WHERE id=%s", (lottery_id,))
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="抽奖不存在")
            parts, vals = [], []
            for k, v in updates.items():
                parts.append(f"{validate_column_name(k)}=%s")
                vals.append(v)
            vals.append(lottery_id)
            await cur.execute(f"UPDATE group_choujiang SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True, "updated": list(updates.keys())}