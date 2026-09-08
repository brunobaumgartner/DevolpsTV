"""Autenticação do painel de administração (cadastro de links VOD) — separada
do esquema de token-na-URL usado pra consumir a playlist. Aqui é usuário/senha
de verdade com sessão por cookie, porque é uma capacidade de ESCRITA (adicionar/
editar títulos e links), não só leitura."""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import AdminSession, AdminUser

SESSION_COOKIE_NAME = "admin_session"
SESSION_TTL_DAYS = 14
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(derived, expected)


def create_session(db: Session, admin_user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    db.add(AdminSession(session_token=token, admin_user_id=admin_user_id, expires_at=expires_at))
    db.commit()
    return token


def require_admin(
    admin_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> AdminUser:
    if not admin_session:
        raise HTTPException(status_code=401, detail="Não autenticado")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = (
        db.query(AdminSession)
        .filter(AdminSession.session_token == admin_session, AdminSession.expires_at > now)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")

    user = db.query(AdminUser).filter(AdminUser.id == session.admin_user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return user
