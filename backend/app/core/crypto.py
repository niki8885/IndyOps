import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import SECRET_KEY


def _fernet() -> Fernet:
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not set — cannot encrypt ESI tokens")
    key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None
