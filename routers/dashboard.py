# Dashboard stats router
from fastapi import APIRouter, Depends
from database import resolve_data_pool
from auth import get_current_admin

router = APIRouter()

@router.get("/dashboard")
async def api_dashboard(db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM qunzu"); groups = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM pindao"); channels = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM users"); users = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM group_choujiang WHERE status='active'"); active_lotteries = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM bot_tokens WHERE status='active'"); active_clones = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM group_subscriptions WHERE expires_at > NOW()"); active_subs = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM group_dingshi WHERE status=TRUE"); scheduled_msgs = (await cur.fetchone())[0]
    return {"groups": groups, "channels": channels, "users": users,
            "active_lotteries": active_lotteries, "active_clones": active_clones,
            "active_subscriptions": active_subs, "scheduled_messages": scheduled_msgs}
