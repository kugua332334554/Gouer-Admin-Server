# Quick publish (kuaisufabu) CRUD router
from datetime import datetime
from fastapi import APIRouter, Depends
from models import QuickPublishCreate
from database import resolve_data_pool, validate_column_name, rows_to_dicts
from auth import get_current_admin

router = APIRouter()

@router.get("/kuaisufabu")
async def list_kuaisufabu(db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM group_kuaisufabu ORDER BY created_at DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)

@router.post("/kuaisufabu")
async def create_kuaisufabu(data: QuickPublishCreate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO group_kuaisufabu (creator_id,name,keyword,content_text,buttons_text,status) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (data.creator_id, data.name, data.keyword, data.content_text, data.buttons_text, data.status))
            return {"ok": True, "id": cur.lastrowid}

@router.delete("/kuaisufabu/{pub_id}")
async def delete_kuaisufabu(pub_id: int, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_kuaisufabu WHERE id=%s", (pub_id,))
    return {"ok": True}

@router.put("/kuaisufabu/{pub_id}")
async def update_kuaisufabu(pub_id: int, data: dict, db: str = "", admin=Depends(get_current_admin)):
    allowed = {"name", "keyword", "content_text", "buttons_text", "status"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates: return {"ok": True}
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(pub_id)
            await cur.execute(f"UPDATE group_kuaisufabu SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}
