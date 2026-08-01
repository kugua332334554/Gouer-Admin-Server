# GouerAdmin Server — slim entry point
import os
import sys
import logging
import asyncio
import mimetypes
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Config ────────────────────────────────────────────
from config import OBF, PREFIX

# ── App ────────────────────────────────────────────────
app = FastAPI(title="GouerAdmin", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ── Security middleware ────────────────────────────────
from auth import security_headers_middleware, rate_limit_middleware
app.middleware("http")(security_headers_middleware)
app.middleware("http")(rate_limit_middleware)

# ── Register all routers ──────────────────────────────
from routers import (dashboard, groups, channels, dingshi, weijinci, keyword_reply,
                     kuaisufabu, lotteries, users, points, subscriptions,
                     bot_tokens, bots, db_manager, code_editor, system, shop)
from auth import router as auth_router

app.include_router(auth_router, prefix=PREFIX)
app.include_router(dashboard.router, prefix=PREFIX)
app.include_router(groups.router, prefix=PREFIX)
app.include_router(channels.router, prefix=PREFIX)
app.include_router(dingshi.router, prefix=PREFIX)
app.include_router(weijinci.router, prefix=PREFIX)
app.include_router(keyword_reply.router, prefix=PREFIX)
app.include_router(kuaisufabu.router, prefix=PREFIX)
app.include_router(lotteries.router, prefix=PREFIX)
app.include_router(users.router, prefix=PREFIX)
app.include_router(points.router, prefix=PREFIX)
app.include_router(subscriptions.router, prefix=PREFIX)
app.include_router(bot_tokens.router, prefix=PREFIX)
app.include_router(bots.router, prefix=PREFIX)
app.include_router(db_manager.router, prefix=PREFIX)
app.include_router(code_editor.router, prefix=PREFIX)
app.include_router(system.router, prefix=PREFIX)
app.include_router(shop.router, prefix=PREFIX)

# ── Health check ───────────────────────────────────────
@app.get(OBF["health_path"])
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

# ── SPA serving ────────────────────────────────────────
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

_static_dir = os.getenv("BOT_FT", os.path.join(os.path.dirname(__file__), "..", "admin_frontend", "dist"))
_admin_path = OBF["admin_path"]

def _fix_and_inject(html_content: str) -> str:
    """Inject base href + API prefix meta tag into SPA index.html."""
    html_content = html_content.replace(" crossorigin", "")
    base_tag = f'<base href="{_admin_path}/">'
    meta_tag = f'<meta name="api-prefix" content="{PREFIX}">'
    return html_content.replace("<head>", f"<head>{meta_tag}{base_tag}", 1)

def _serve_file_or_spa(rest: str = ""):
    fp = os.path.join(_static_dir, rest) if rest else os.path.join(_static_dir, "index.html")
    real = os.path.realpath(fp)
    if not real.startswith(os.path.realpath(_static_dir)):
        fp = os.path.join(_static_dir, "index.html")
    if os.path.isfile(fp) and rest:
        mt, _ = mimetypes.guess_type(fp)
        return FileResponse(fp, media_type=mt)
    html = _fix_and_inject(open(os.path.join(_static_dir, "index.html")).read())
    return HTMLResponse(content=html)

if os.path.exists(_static_dir):
    @app.api_route(f"{_admin_path}", methods=["GET", "HEAD"])
    async def serve_admin_redirect(request: Request):
        return RedirectResponse(url=f"{_admin_path}/")

    @app.api_route(f"{_admin_path}/", methods=["GET", "HEAD"])
    async def serve_admin(request: Request):
        return _serve_file_or_spa()

    @app.api_route(f"{_admin_path}/{{rest:path}}", methods=["GET", "HEAD"])
    async def serve_admin_spa(request: Request, rest: str):
        return _serve_file_or_spa(rest)

# ── Startup ────────────────────────────────────────────
async def _startup_clean():
    import signal as _sig
    import subprocess as _sp
    killed = 0
    _bot_dir = os.getenv("BOT_DIR", "")
    for proc in _sp.run(["ps", "aux"], capture_output=True, text=True).stdout.split("\n"):
        if _bot_dir and f"{_bot_dir}/main.py" in proc and "grep" not in proc:
            try:
                pid = int(proc.split()[1])
                os.kill(pid, _sig.SIGTERM)
                killed += 1
            except: pass
    if killed:
        logging.getLogger("gouer_admin").info(f"Startup: killed {killed} stale bot process(es)")
    # clear stale PIDs — use temp pool, NOT get_db_pool(), to avoid caching in wrong event loop
    try:
        import aiomysql as _am
        p = await _am.create_pool(
            host=os.getenv("DB_HOST","127.0.0.1"), port=int(os.getenv("DB_PORT","3306")),
            user=os.getenv("DB_USER","root"), password=os.getenv("DB_PASS",""),
            db=os.getenv("DB","test"), autocommit=True)
        async with p.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE bot_tokens SET pid=0 WHERE pid>0")
        p.close()
        await p.wait_closed()
    except Exception:
        pass

if __name__ == "__main__":
    import uvicorn
    from auth import _current_2fa_secret, ADMIN_2FA_SECRET, init_auth
    from config import OBF as _OBF

    port = int(os.getenv("ADMIN_PORT", "8800"))
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("gouer_admin")

    # persist 2FA secret if not set
    if not ADMIN_2FA_SECRET:
        from auth import save_env
        save_env("ADMIN_2FA_SECRET", _current_2fa_secret)
        os.environ["ADMIN_2FA_SECRET"] = _current_2fa_secret

    print(f"\n  GouerAdmin v2.0  |  Port: {port}  |  2FA: {_current_2fa_secret}")
    print(f"  后台地址: http://服务器IP:{port}{_OBF['admin_path']}/")
    print()

    # startup cleanup
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_startup_clean())
    loop.close()

    uvicorn.run(app, host="0.0.0.0", port=port)
