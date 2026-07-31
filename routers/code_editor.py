# Code editor router — browse/edit plugin and bot source files
import os
import sys
from fastapi import APIRouter, Depends, HTTPException
from models import FileSaveRequest
from auth import get_current_admin

router = APIRouter()

_PLUGINS_DIR = os.path.realpath(os.getenv("PLUGINS_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "plugins")))
_BOT_DIR = os.path.realpath(os.getenv("BOT_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "bot")))
_ALLOWED_EXT = {".py", ".json", ".env", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".md"}

# ── Walk file tree ────────────────────────────────────
def _walk_files(base: str, scope: str) -> list:
    files = []
    if not os.path.isdir(base): return files
    for root, dirs, dnames in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "__MACOSX", ".uploads")]
        for fname in sorted(dnames):
            ext = os.path.splitext(fname)[1].lower()
            if ext in _ALLOWED_EXT and not fname.startswith("."):
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, base)
                files.append({"name": rel, "path": rel, "size": os.path.getsize(full), "scope": scope})
    return files

# ── File tree ─────────────────────────────────────────
@router.get("/code/tree")
async def code_tree(admin=Depends(get_current_admin)):
    return _walk_files(_PLUGINS_DIR, "plugins") + _walk_files(_BOT_DIR, "bot")

# ── Read file ─────────────────────────────────────────
@router.get("/code/file")
async def code_read(path: str, scope: str = "plugins", admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if scope == "plugins" else _BOT_DIR
    full = os.path.realpath(os.path.join(base, path))
    if not full.startswith(base): raise HTTPException(status_code=403, detail="路径越权")
    if not os.path.isfile(full): raise HTTPException(status_code=404, detail="文件不存在")
    try:
        with open(full, "r", encoding="utf-8") as f: content = f.read()
    except Exception:
        with open(full, "r", encoding="latin-1") as f: content = f.read()
    return {"path": path, "content": content, "scope": scope}

# ── Save file ─────────────────────────────────────────
@router.put("/code/file")
async def code_save(req: FileSaveRequest, admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if req.scope == "plugins" else _BOT_DIR
    full = os.path.realpath(os.path.join(base, req.path))
    if not full.startswith(base): raise HTTPException(status_code=403, detail="路径越权")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f: f.write(req.content)
    # hot-reload if Python file
    if full.endswith(".py"):
        mod_name = os.path.splitext(req.path)[0].replace("/", ".").replace("\\", ".")
        try:
            if mod_name in sys.modules:
                import importlib; importlib.reload(sys.modules[mod_name])
        except: pass
    return {"ok": True, "path": req.path}

# ── Delete file ───────────────────────────────────────
@router.delete("/code/file")
async def code_delete(path: str, scope: str = "plugins", admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if scope == "plugins" else _BOT_DIR
    full = os.path.realpath(os.path.join(base, path))
    if not full.startswith(base): raise HTTPException(status_code=403)
    os.remove(full)
    return {"ok": True}

# ── Create file ───────────────────────────────────────
@router.post("/code/create")
async def code_create(scope: str = "plugins", name: str = "", admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if scope == "plugins" else _BOT_DIR
    safe = name.replace("..", "").replace("/", "").replace("\\", "")
    if not safe.endswith(".py"): safe += ".py"
    full = os.path.join(base, safe)
    if os.path.exists(full): raise HTTPException(status_code=400, detail="文件已存在")
    with open(full, "w") as f: f.write("# New plugin\n")
    return {"ok": True, "path": safe}

# ── Rename file ───────────────────────────────────────
@router.put("/code/rename")
async def code_rename(old: str = "", new: str = "", scope: str = "plugins", admin=Depends(get_current_admin)):
    base = _PLUGINS_DIR if scope == "plugins" else _BOT_DIR
    old_full = os.path.realpath(os.path.join(base, old))
    if not old_full.startswith(base): raise HTTPException(status_code=403)
    safe = new.replace("..", "").replace("/", "").replace("\\", "")
    new_full = os.path.join(os.path.dirname(old_full), safe)
    if os.path.exists(new_full): raise HTTPException(status_code=400, detail="目标文件已存在")
    os.rename(old_full, new_full)
    return {"ok": True, "path": os.path.relpath(new_full, base)}

# ── Hot-reload module ─────────────────────────────────
@router.post("/code/reload")
async def code_reload(path: str = "", admin=Depends(get_current_admin)):
    if not path: return {"reloaded": []}
    mod_name = os.path.splitext(path)[0].replace("/", ".").replace("\\", ".")
    import importlib; reloaded = []
    for name, mod in list(sys.modules.items()):
        if name == mod_name or name.startswith(mod_name + "."):
            try: importlib.reload(mod); reloaded.append(name)
            except: pass
    return {"reloaded": reloaded}
