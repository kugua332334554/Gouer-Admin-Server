# Bot token (clone) CRUD router
import os
from datetime import datetime
from fastapi import APIRouter, Depends
from models import BotTokenCreate
from database import get_db_pool, rows_to_dicts
from auth import get_current_admin

router = APIRouter()

@router.get("/bot-tokens")
async def list_bot_tokens(admin=Depends(get_current_admin)):
    pool = await get_db_pool()  # always main DB
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, owner_id, bot_username, db_name, pid, status, created_at "
                "FROM bot_tokens ORDER BY id DESC")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    return rows_to_dicts(rows, cols)

@router.post("/bot-tokens")
async def create_bot_token(data: BotTokenCreate, admin=Depends(get_current_admin)):
    from crypto_utils import encrypt_token
    pool = await get_db_pool()
    encrypted = encrypt_token(data.bot_token)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO bot_tokens (owner_id, bot_token, bot_username) VALUES (%s,%s,%s)",
                (data.owner_id, encrypted, data.bot_username))
            return {"ok": True, "id": cur.lastrowid}

@router.delete("/bot-tokens/{token_id}")
async def delete_bot_token_api(token_id: int, admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # find db_name and pid before deleting
            await cur.execute("SELECT db_name, pid FROM bot_tokens WHERE id=%s", (token_id,))
            row = await cur.fetchone()
            db_name, pid = row if row else (None, None)

            # kill running child process
            if pid:
                try: os.kill(pid, 9)
                except Exception: pass

            # remove from bot_tokens
            await cur.execute("DELETE FROM bot_tokens WHERE id=%s", (token_id,))

            # drop clone database
            if db_name:
                try: await cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
                except Exception: pass
    return {"ok": True}
