# Bot process control + status + NEW multi-bot list router
import os
import sys
import asyncio
import subprocess
import signal
from fastapi import APIRouter, Depends, HTTPException
from database import get_db_pool, _get_pool_for
from auth import get_current_admin

router = APIRouter()

# paths for bot directory
_BOT_DIR = os.path.realpath(os.getenv("BOT_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "bot")))
_BOT_MAIN = os.path.join(_BOT_DIR, "main.py") if os.path.isdir(_BOT_DIR) else ""
_BOT_PYTHON = os.getenv("BOT_PYTHON", sys.executable)
_bot_processes = {}  # name → subprocess.Popen

# ── NEW: Multi-bot list for viewer ─────────────────────
@router.get("/bots/list")
async def bots_list_for_viewer(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    bots = []
    # main bot entry
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM qunzu")
            main_groups = (await cur.fetchone())[0]
            await cur.execute("SELECT COUNT(*) FROM pindao")
            main_channels = (await cur.fetchone())[0]
    bots.append({
        "id": 0, "bot_username": os.getenv("BOT_USERNAME", "主机器人"),
        "db_name": "", "is_main": True, "status": "active",
        "group_count": main_groups, "channel_count": main_channels,
    })
    # clone bots
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, bot_username, db_name, status FROM bot_tokens WHERE status='active' ORDER BY id")
            for row in await cur.fetchall():
                bid, uname, db_name, status = row
                g_cnt, c_cnt = 0, 0
                if db_name:
                    try:
                        clone_pool = await _get_pool_for(db_name)
                        async with clone_pool.acquire() as c2:
                            async with c2.cursor() as cur2:
                                await cur2.execute("SELECT COUNT(*) FROM qunzu")
                                g_cnt = (await cur2.fetchone())[0]
                                await cur2.execute("SELECT COUNT(*) FROM pindao")
                                c_cnt = (await cur2.fetchone())[0]
                    except Exception:
                        pass
                bots.append({
                    "id": bid, "bot_username": uname, "db_name": db_name,
                    "is_main": False, "status": status,
                    "group_count": g_cnt, "channel_count": c_cnt,
                })
    return bots

# ── Bot process status ─────────────────────────────────
@router.get("/bots/status")
async def bots_status(admin=Depends(get_current_admin)):
    pool = await get_db_pool()
    bots = []
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, bot_username, db_name, pid, status FROM bot_tokens ORDER BY id")
            for row in await cur.fetchall():
                bid, uname, db_name, pid, status = row
                running = False
                if pid:
                    try: os.kill(pid, 0); running = True
                    except: pass
                bots.append({"id": bid, "username": uname, "db": db_name,
                             "pid": pid, "status": status, "running": running})
    return bots

# ── Main bot status (ps scan) ──────────────────────────
@router.get("/bots/main/status")
async def main_bot_status(admin=Depends(get_current_admin)):
    running = False; pid = 0
    for line in subprocess.run(["ps","aux"], capture_output=True, text=True).stdout.split("\n"):
        if "grep" not in line and "main.py" in line:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    check_pid = int(parts[1])
                    # exclude child bots (BOT_IS_CHILD=1)
                    try:
                        with open(f"/proc/{check_pid}/environ", "rb") as f:
                            if b"BOT_IS_CHILD=1" in f.read():
                                continue
                    except Exception:
                        pass
                    pid = check_pid; running = True; break
                except Exception:
                    pass
    log_size = os.path.getsize("/var/log/gouer_main_bot.log") if os.path.exists("/var/log/gouer_main_bot.log") else 0
    return {"running": running, "pid": pid, "log_size": log_size}

# ── Log viewers ────────────────────────────────────────
@router.get("/bots/main/log")
async def main_bot_log(tail: int = 100, admin=Depends(get_current_admin)):
    lf = "/var/log/gouer_main_bot.log"
    if not os.path.exists(lf): return {"lines": []}
    with open(lf) as f: return {"lines": [l.rstrip() for l in f.readlines()[-tail:]]}

@router.get("/bots/{bot_id}/log")
async def bot_log(bot_id: int, tail: int = 100, admin=Depends(get_current_admin)):
    log_file = f"/var/log/gouer_child_{bot_id}.log"
    if not os.path.exists(log_file): return {"lines": []}
    with open(log_file, "r") as f:
        return {"lines": [l.rstrip() for l in f.readlines()[-tail:]]}

# ── Start / Stop / Restart ─────────────────────────────
@router.post("/bots/start-all")
async def start_all_bots(admin=Depends(get_current_admin)):
    if not _BOT_MAIN or not os.path.isfile(_BOT_MAIN):
        raise HTTPException(status_code=400, detail="Bot 目录未配置")
    log_f = open("/var/log/gouer_main_bot.log", "a")
    p = subprocess.Popen([_BOT_PYTHON, _BOT_MAIN], cwd=_BOT_DIR,
                         stdout=log_f, stderr=log_f, start_new_session=True)
    _bot_processes["main"] = p
    return {"started": [{"name": "main", "pid": p.pid}]}

@router.post("/bots/stop-all")
async def stop_all_bots(admin=Depends(get_current_admin)):
    stopped = []
    for name, p in list(_bot_processes.items()):
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            stopped.append({"name": name, "pid": p.pid})
        except: pass
    _bot_processes.clear()
    # kill any stragglers
    try: subprocess.run(["pkill", "-f", f"{_BOT_DIR}/main.py"], timeout=5)
    except: pass
    return {"stopped": stopped}

@router.post("/bots/restart-all")
async def restart_all_bots(admin=Depends(get_current_admin)):
    await stop_all_bots(admin=admin)
    await asyncio.sleep(2)
    return await start_all_bots(admin=admin)
