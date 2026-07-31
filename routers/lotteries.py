# Lotteries read-only router
from datetime import datetime
from fastapi import APIRouter, Depends
from database import resolve_data_pool, rows_to_dicts
from auth import get_current_admin

router = APIRouter()

@router.get("/lotteries")
async def list_lotteries(db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM group_choujiang ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)
