"""Autenticación: usuarios en MySQL (bcrypt) + cookie de sesión firmada (itsdangerous)."""
from __future__ import annotations

import logging

import bcrypt
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config, db

log = logging.getLogger("backupcsr-web")

_serializer: URLSafeTimedSerializer | None = None


def _ser() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="backupcsr-session")
    return _serializer


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def user_count() -> int:
    row = db.query("SELECT COUNT(*) AS n FROM users", one=True)
    return int(row["n"]) if row else 0


def get_user(username: str):
    return db.query(
        "SELECT id, username, password_hash, role, active FROM users WHERE username = %s",
        (username,),
        one=True,
    )


def create_user(username: str, password: str, role: str = "admin") -> None:
    db.execute(
        """
        INSERT INTO users (username, password_hash, role, active)
        VALUES (%s, %s, %s, 1)
        ON DUPLICATE KEY UPDATE
            password_hash = VALUES(password_hash),
            role = VALUES(role),
            active = 1
        """,
        (username, hash_password(password), role),
    )


def make_session(username: str, role: str) -> str:
    return _ser().dumps({"u": username, "r": role})


def read_session(token: str):
    try:
        return _ser().loads(token, max_age=config.SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


async def current_user(request: Request) -> dict:
    token = request.cookies.get(config.SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="no autenticado")
    data = read_session(token)
    if not data:
        raise HTTPException(status_code=401, detail="sesión inválida o expirada")
    return {"username": data.get("u"), "role": data.get("r", "viewer")}


async def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="requiere rol admin")
    return user
