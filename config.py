# Obfuscated API path generation
import os
import hashlib
import secrets

def generate_obfuscated_paths(secret_key: str = "") -> dict:
    if not secret_key:
        secret_key = os.getenv("KEY", secrets.token_hex(16))
    h = hashlib.sha256(f"admin_panel_v5_{secret_key}".encode()).hexdigest()
    return {
        "api_prefix": f"/api/{h[:12]}",
        "login_path": f"/{h[12:24]}",
        "admin_path": f"/{h[24:36]}",
        "health_path": f"/_health_{h[8:16]}",
    }

OBF = generate_obfuscated_paths(os.getenv("KEY", ""))
PREFIX = OBF["api_prefix"]
