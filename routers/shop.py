# Points shop CRUD router
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from database import resolve_data_pool, validate_column_name, rows_to_dicts
from auth import get_current_admin
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class ShopItemCreate(BaseModel):
    chat_id: int
    name: str
    points_price: int = 0
    stock: int = -1  # -1 = unlimited
    description: str = ""
    delivery_mode: str = "manual"  # manual / auto
    card_data: str = ""  # newline-separated card codes
    status: bool = True

# ── List items ────────────────────────────────────────
@router.get("/shop")
async def list_shop_items(chat_id: int = None, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if chat_id:
                await cur.execute(
                    "SELECT id, chat_id, name, description, points_price, stock, "
                    "media_type, media_file_id, delivery_mode, card_data, status, created_at "
                    "FROM group_shop WHERE chat_id=%s ORDER BY id ASC", (chat_id,))
            else:
                await cur.execute(
                    "SELECT id, chat_id, name, description, points_price, stock, "
                    "media_type, media_file_id, delivery_mode, card_data, status, created_at "
                    "FROM group_shop ORDER BY id ASC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)

# ── Create item ───────────────────────────────────────
@router.post("/shop")
async def create_shop_item(data: ShopItemCreate, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO group_shop (chat_id, name, points_price, stock, description, delivery_mode, card_data, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (data.chat_id, data.name, data.points_price, data.stock, data.description,
                 data.delivery_mode, data.card_data, data.status))
            return {"ok": True, "id": cur.lastrowid}

# ── Update item ───────────────────────────────────────
@router.put("/shop/{item_id}")
async def update_shop_item(item_id: int, data: dict, db: str = "", admin=Depends(get_current_admin)):
    allowed = {"name", "description", "points_price", "stock", "delivery_mode", "card_data", "status"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates: return {"ok": True}
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            parts, vals = [], []
            for k, v in updates.items(): parts.append(f"{validate_column_name(k)}=%s"); vals.append(v)
            vals.append(item_id)
            await cur.execute(f"UPDATE group_shop SET {', '.join(parts)} WHERE id=%s", vals)
    return {"ok": True}

# ── Delete item ───────────────────────────────────────
@router.delete("/shop/{item_id}")
async def delete_shop_item(item_id: int, db: str = "", admin=Depends(get_current_admin)):
    pool = await resolve_data_pool(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM group_shop WHERE id=%s", (item_id,))
    return {"ok": True}
