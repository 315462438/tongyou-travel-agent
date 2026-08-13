"""鉴权工具（Phase 15）：密码哈希 + 令牌，纯 stdlib。"""

import hashlib
import hmac
import os
import secrets

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """pbkdf2-sha256 加盐哈希，格式 pbkdf2$iter$salt_hex$hash_hex。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt_hex, hash_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:  # noqa: BLE001
        return False


def new_token() -> str:
    return secrets.token_hex(32)
