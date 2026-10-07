"""Password hashing + JWT for the AirAuth service."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

BASE_DIR = Path(__file__).resolve().parent
SECRET_FILE = BASE_DIR / ".jwt_secret"

_bearer = HTTPBearer(auto_error=False)


def _load_secret() -> str:
    env = os.environ.get("AIRAUTH_JWT_SECRET")
    if env and len(env) >= 32:
        return env
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text().strip()
    import secrets
    secret = secrets.token_hex(32)
    fd = os.open(str(SECRET_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secret)
    return secret


_JWT_SECRET = _load_secret()
_JWT_ALG = "HS256"
_JWT_DAYS = 7


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, pw_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), pw_hash.encode())


def make_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=_JWT_DAYS)).timestamp()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session. Log in again.")


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    if not creds:
        raise HTTPException(status_code=401, detail="Log in first.")
    payload = decode_token(creds.credentials)
    import signstore
    user = signstore.get_user(int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return user


def require_roles(*roles):
    def _check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Not allowed for your role.")
        return user
    return _check


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "business_id": user["business_id"],
        "airsig_enrolled": bool(user["airsig_enrolled"]),
    }
