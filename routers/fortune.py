# 抽签管理 (fortunes 签文库) CRUD router
# fortunes 表是 bot 抽签(/抽签)的数据源, 存储在每个 bot 自己的库里。
from fastapi import APIRouter, Depends
from models import FortuneCreate
from database import resolve_data_pool, rows_to_dicts
from auth import get_current_admin

router = APIRouter()


@router.get("/fortunes")
async def list_fortunes(search: str = "", db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if search:
                await cur.execute(
                    "SELECT id, sign, poem, reading, poem_key, created_at FROM fortunes "
                    "WHERE sign LIKE %s OR poem LIKE %s OR reading LIKE %s ORDER BY id DESC",
                    (f"%{search}%", f"%{search}%", f"%{search}%"))
            else:
                await cur.execute(
                    "SELECT id, sign, poem, reading, poem_key, created_at FROM fortunes ORDER BY id DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)


@router.post("/fortunes")
async def create_fortune(data: FortuneCreate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO fortunes (sign, poem, reading, poem_key) VALUES (%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE sign=VALUES(sign), poem=VALUES(poem), reading=VALUES(reading)",
                (data.sign[:64], data.poem[:255], data.reading[:255], data.poem[:191]))
            return {"ok": True, "id": cur.lastrowid}


@router.put("/fortunes/{fortune_id}")
async def update_fortune(fortune_id: int, data: FortuneCreate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE fortunes SET sign=%s, poem=%s, reading=%s, poem_key=%s WHERE id=%s",
                (data.sign[:64], data.poem[:255], data.reading[:255], data.poem[:191], fortune_id))
    return {"ok": True}


@router.delete("/fortunes/{fortune_id}")
async def delete_fortune(fortune_id: int, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM fortunes WHERE id=%s", (fortune_id,))
    return {"ok": True}
