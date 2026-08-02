# 集群黑名单 (cluster_blacklist) CRUD router
# 黑名单统一存主库, 由所有 Gouer Bot(主 + 克隆)共享。
from fastapi import APIRouter, Depends
from models import BlacklistCreate
from database import get_db_pool, rows_to_dicts
from auth import get_current_admin

router = APIRouter()


@router.get("/blacklist")
async def list_blacklist(search: str = "", admin=Depends(get_current_admin)):
    pool = await get_db_pool()  # always main DB
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if search:
                await cur.execute(
                    "SELECT user_id, username, reason, created_at FROM cluster_blacklist "
                    "WHERE CAST(user_id AS CHAR) LIKE %s OR username LIKE %s "
                    "ORDER BY created_at DESC",
                    (f"%{search}%", f"%{search}%"))
            else:
                await cur.execute(
                    "SELECT user_id, username, reason, created_at FROM cluster_blacklist ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)


@router.post("/blacklist")
async def add_blacklist(data: BlacklistCreate, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO cluster_blacklist (user_id, username, reason)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE username=VALUES(username), reason=VALUES(reason)
            """, (data.user_id, data.username, data.reason))
    return {"ok": True}


@router.delete("/blacklist/{user_id}")
async def delete_blacklist(user_id: int, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM cluster_blacklist WHERE user_id=%s", (user_id,))
    return {"ok": True}
