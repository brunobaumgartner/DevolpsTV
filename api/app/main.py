import logging
import os
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIR
from .db import Base, SessionLocal, engine
from .models import AccessToken
from .routers import channels, health, playlist, vod

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
app.include_router(vod.router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    _ensure_dev_token()


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


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
