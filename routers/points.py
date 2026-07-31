# Points management router
from fastapi import APIRouter, Depends
from models import PointsUpdateModel
from database import resolve_data_pool
from auth import get_current_admin

router = APIRouter()

@router.get("/points")
async def list_points(chat_id: int = None, user_id: int = None, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if chat_id and user_id:
                await cur.execute("SELECT chat_id, user_id, points FROM user_points WHERE chat_id=%s AND user_id=%s",
                                  (chat_id, user_id))
            elif chat_id:
                await cur.execute("SELECT chat_id, user_id, points FROM user_points WHERE chat_id=%s ORDER BY points DESC",
                                  (chat_id,))
            else:
                await cur.execute("SELECT chat_id, user_id, points FROM user_points ORDER BY points DESC")
            rows = await cur.fetchall()
    return [{"chat_id": r[0], "user_id": r[1], "points": r[2]} for r in rows]

@router.put("/points/{chat_id}/{user_id}")
async def update_user_points_api(chat_id: int, user_id: int, data: PointsUpdateModel, db: str = "",
                                  admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO user_points (chat_id, user_id, points) VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE points = VALUES(points)
            """, (chat_id, user_id, data.points))
    return {"ok": True, "points": data.points}
