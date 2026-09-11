import logging
import os
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .auth_admin import hash_password
from .config import ADMIN_PASSWORD, ADMIN_USERNAME, FRONTEND_DIR
from .db import Base, SessionLocal, engine
from .genre_classifier import seed_default_keywords_if_empty, sync_new_default_keywords
from .models import AccessToken, AdminUser
from .routers import admin, channels, health, hls_proxy, media_proxy, playlist, vod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("iptv-api")

app = FastAPI(title="IPTV-BR API")

# CORS liberado pra facilitar o teste local do frontend. Restringir antes de expor
# publicamente (ver ARQUITETURA.md secao 9).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(playlist.router)
app.include_router(channels.router)
app.include_router(hls_proxy.router)
app.include_router(media_proxy.router)
app.include_router(vod.router)
app.include_router(admin.router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    _ensure_dev_token()
    _ensure_admin_user()
    _ensure_genre_keywords()


def _ensure_dev_token():
    """Garante que exista pelo menos 1 token pra facilitar o teste local.
    Não roda mais nada disso se já houver token cadastrado."""
    db = SessionLocal()
    try:
        existing = db.query(AccessToken).first()
        if existing is not None:
            return
        token = secrets.token_urlsafe(24)
        db.add(AccessToken(token=token, label="dev-auto-gerado"))
        db.commit()
        logger.warning("=" * 60)
        logger.warning("Nenhum token encontrado. Token de teste criado:")
        logger.warning(token)
        logger.warning("Use em: http://localhost:%s/p/%s/playlist.m3u8", os.environ.get("API_PORT", "7678"), token)
        logger.warning("=" * 60)
    finally:
        db.close()


def _ensure_admin_user():
    """O .env é a fonte de verdade pro usuário/senha do admin: se ADMIN_PASSWORD
    estiver definido lá, o hash é recalculado a cada subida (trocar a senha no
    .env e reiniciar já basta). Se não tiver ADMIN_PASSWORD configurado e ainda
    não existir usuário nenhum, gera uma senha aleatória só pra não travar o
    primeiro uso (mesmo padrão do token de playlist)."""
    db = SessionLocal()
    try:
        existing = db.query(AdminUser).filter(AdminUser.username == ADMIN_USERNAME).first()

        # docker-compose com "${ADMIN_PASSWORD:-}" gera string VAZIA quando a
        # variável não existe no .env — não None. "not password" cobre os dois
        # casos (variável ausente E variável vazia).
        password = ADMIN_PASSWORD
        if not password:
            if existing is not None:
                return  # já existe usuário e não foi passada senha nova via env — não mexe
            password = secrets.token_urlsafe(12)
            logger.warning("=" * 60)
            logger.warning("ADMIN_PASSWORD não definido no .env. Senha de admin gerada:")
            logger.warning("usuário: %s", ADMIN_USERNAME)
            logger.warning("senha:   %s", password)
            logger.warning("Defina ADMIN_USERNAME/ADMIN_PASSWORD no .env pra usar sua própria senha.")
            logger.warning("=" * 60)

        password_hash = hash_password(password)
        if existing is None:
            db.add(AdminUser(username=ADMIN_USERNAME, password_hash=password_hash))
        else:
            existing.password_hash = password_hash
        db.commit()
    finally:
        db.close()


def _ensure_genre_keywords():
    """Semeia a lista padrão de palavras-chave (EN+PT) só na primeira vez —
    depois disso quem edita é o usuário via /genres.html, nunca sobrescrevemos."""
    db = SessionLocal()
    try:
        added = seed_default_keywords_if_empty(db)
        if added:
            logger.info("Semeadas %d palavras-chave de gênero padrão.", added)
        synced = sync_new_default_keywords(db)
        if synced:
            logger.info("Adicionadas %d palavras-chave novas de gênero padrão.", synced)
    finally:
        db.close()


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
