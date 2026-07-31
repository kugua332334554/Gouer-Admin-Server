# System config router
import os
from datetime import datetime
from fastapi import APIRouter, Depends
from config import OBF
from auth import get_current_admin

router = APIRouter()

@router.get("/system/obfuscated-paths")
async def get_obfuscated_paths(admin=Depends(get_current_admin)):
    return {"paths": OBF}

@router.get("/system/config")
async def get_system_config(admin=Depends(get_current_admin)):
    return {
        "db_host": os.getenv("DB_HOST", "127.0.0.1"),
        "db_port": os.getenv("DB_PORT", "3306"),
        "db_name": os.getenv("DB", ""),
        "bot_username": os.getenv("BOT_USERNAME", ""),
        "has_payment": bool(os.getenv("MYQB_APP_ID", "")),
        "has_encryption": bool(os.getenv("KEY", "")),
        "ai_price": os.getenv("AI_PRICE", "30"),
        "card_price": os.getenv("CARD_PRICE", "20"),
        "push_channel": os.getenv("PUSH", ""),
    }
