# DB Manager router — browse tables, run SELECT queries, backup
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from database import get_db_pool, _get_pool_for, validate_table_name
from models import DBQueryRequest
from auth import get_current_admin

router = APIRouter()

# ── List databases ────────────────────────────────────
@router.get("/db/databases")
async def db_list_databases(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW DATABASES")
            dbs = [r[0] for r in await cur.fetchall()]
            # filter system DBs
            return [d for d in dbs if d not in (
                "information_schema","mysql","performance_schema","sys","phpmyadmin")]

# ── List tables ───────────────────────────────────────
@router.get("/db/tables")
async def db_list_tables(db: str = "", admin=Depends(get_current_admin)):
    pool = await _get_pool_for(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW TABLES")
            return {"tables": [r[0] for r in await cur.fetchall()], "db": db or os.getenv("DB","")}

# ── Table info (DESCRIBE) ──────────────────────────────
@router.get("/db/tables/{table}")
async def db_table_info(table: str, db: str = "", admin=Depends(get_current_admin)):
    table = validate_table_name(table)
    pool = await _get_pool_for(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"DESCRIBE `{table}`")
            columns = [{"field": r[0], "type": r[1], "null": r[2], "key": r[3],
                        "default": str(r[4]), "extra": r[5]} for r in await cur.fetchall()]
            await cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            row_count = (await cur.fetchone())[0]
    return {"table": table, "columns": columns, "row_count": row_count, "db": db or os.getenv("DB","")}

# ── Table rows ────────────────────────────────────────
@router.get("/db/tables/{table}/rows")
async def db_table_rows(table: str, page: int = 1, limit: int = 50, db: str = "",
                         admin=Depends(get_current_admin)):
    table = validate_table_name(table)
    offset = (page - 1) * limit
    pool = await _get_pool_for(db)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT COUNT(*) FROM `{table}`"); total = (await cur.fetchone())[0]
            await cur.execute(f"SELECT * FROM `{table}` LIMIT {int(limit)} OFFSET {int(offset)}")
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
    data = []
    for r in rows:
        row_dict = {}
        for i, c in enumerate(cols):
            v = r[i]
            if isinstance(v, datetime): v = str(v)
            elif isinstance(v, bytes): v = f"<BLOB {len(v)} bytes>"
            row_dict[c] = v
        data.append(row_dict)
    return {"total": total, "page": page, "limit": limit, "columns": cols, "rows": data,
            "db": db or os.getenv("DB","")}

# ── SQL query (read-only) ──────────────────────────────
@router.post("/db/query")
async def db_query(req: DBQueryRequest, admin=Depends(get_current_admin)):
    sql_upper = req.sql.strip().upper()
    if not any(sql_upper.startswith(w) for w in ("SELECT","SHOW","DESCRIBE","EXPLAIN")):
        raise HTTPException(status_code=400, detail="仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN")
    for kw in ("DROP","DELETE","UPDATE","INSERT","ALTER","CREATE","TRUNCATE"):
        if kw in sql_upper:
            raise HTTPException(status_code=400, detail="不允许写操作")
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(req.sql[:req.limit * 10])
                rows = await cur.fetchmany(req.limit)
                cols = [d[0] for d in cur.description] if cur.description else []
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL 错误: {str(e)}")
    data = []
    for r in rows:
        row_dict = {}
        for i, c in enumerate(cols):
            v = r[i]
            if isinstance(v, datetime): v = str(v)
            elif isinstance(v, bytes): v = f"<BLOB {len(v)} bytes>"
            row_dict[c] = v
        data.append(row_dict)
    return {"columns": cols, "rows": data, "count": len(data)}

# ── DB Backup ──────────────────────────────────────────
@router.get("/db/backup")
async def db_backup(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    sql_lines = ["-- GouerAdmin Database Backup", f"-- {datetime.now()}", ""]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW TABLES")
            tables = [r[0] for r in await cur.fetchall()]
            for table in tables:
                await cur.execute(f"SELECT * FROM `{validate_table_name(table)}`")
                rows = await cur.fetchall()
                cols = [d[0] for d in cur.description]
                if not rows: continue
                sql_lines.append(f"\n-- Table: {table}")
                col_names = ", ".join(f"`{c}`" for c in cols)
                for row in rows:
                    vals = []
                    for v in row:
                        if v is None: vals.append("NULL")
                        elif isinstance(v, (int, float)): vals.append(str(v))
                        else: vals.append("'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'")
                    sql_lines.append(f"INSERT INTO `{table}` ({col_names}) VALUES ({', '.join(vals)});")
    sql = "\n".join(sql_lines)
    return Response(content=sql, media_type="application/sql",
                    headers={"Content-Disposition": f"attachment; filename=gouer_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"})
