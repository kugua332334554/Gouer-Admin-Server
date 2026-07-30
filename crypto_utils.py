import hashlib
import base64
from cryptography.fernet import Fernet

#derive_key
def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)

#enctoken
def encrypt_token(token: str, secret: str = "") -> str:
    if not token:
        return ""
    if not secret:
        import os
        secret = os.getenv("KEY")
    key = _derive_key(secret)
    f = Fernet(key)
    return f.encrypt(token.encode()).decode()

#dectoken
def decrypt_token(encrypted: str, secret: str = "") -> str:
    if not encrypted:
        return ""
    if not secret:
        import os
        secret = os.getenv("KEY")
    key = _derive_key(secret)
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()

#hashtoken
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
