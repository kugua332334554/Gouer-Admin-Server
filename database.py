# Database connection pools — main + multi-clone support
import os
import re
import aiomysql
from fastapi import HTTPException

# ── Main DB pool ──────────────────────────────────────
_db_pool = None

async def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = await aiomysql.create_pool(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            db=os.getenv("DB", "test"),
            autocommit=True,
            minsize=2, maxsize=10,
        )
    return _db_pool

# ── Multi-DB pools (clone databases) ──────────────────
_db_pools = {}  # db_name → pool

async def _get_pool_for(db_name: str = ""):
    """Create or reuse a pool for a specific database name."""
    if not db_name:
        return await get_db_pool()
    if db_name not in _db_pools:
        _db_pools[db_name] = await aiomysql.create_pool(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            db=db_name, autocommit=True, minsize=1, maxsize=5)
    return _db_pools[db_name]

async def resolve_data_pool(db: str = ""):
    """Resolve pool by db param. Validates clone db_name against bot_tokens."""
    if not db or db == "main":
        return await get_db_pool()
    # Security: verify db_name belongs to a known clone
    main_pool = await get_db_pool()
    async with main_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM bot_tokens WHERE db_name=%s AND status='active'", (db,))
            if not await cur.fetchone():
                raise HTTPException(status_code=400, detail="无效的数据库名称")
    return await _get_pool_for(db)

# ── SQL injection protection ──────────────────────────
_VALID_COLUMN_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def validate_column_name(col: str) -> str:
    if not _VALID_COLUMN_RE.match(col):
        raise ValueError(f"Invalid column name: {col}")
    return col

def validate_table_name(name: str) -> str:
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Invalid table name: {name}")
    return name

# ── Generic upsert helper ─────────────────────────────

def update_generic(chat_id, table, data: dict):
    """Returns an async function that does INSERT IGNORE + UPDATE."""
    updates = {k: v for k, v in data.items() if v is not None}
    if not updates:
        return lambda conn: None
    async def do(conn):
        async with conn.cursor() as cur:
            await cur.execute(
                f"INSERT IGNORE INTO {validate_table_name(table)} (chat_id) VALUES (%s)",
                (chat_id,))
            parts, vals = [], []
            for k, v in updates.items():
                parts.append(f"{validate_column_name(k)}=%s")
                vals.append(v)
            vals.append(chat_id)
            await cur.execute(
                f"UPDATE {validate_table_name(table)} SET {', '.join(parts)} WHERE chat_id=%s",
                vals)
    return do

# ── Row-to-dict helper ────────────────────────────────
from datetime import datetime

def rows_to_dicts(rows, cols) -> list:
    return [{cols[i]: (str(r[i]) if isinstance(r[i], datetime) else r[i])
             for i in range(len(cols))} for r in rows]
