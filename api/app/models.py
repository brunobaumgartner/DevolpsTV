from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from .db import Base


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True)
    tvg_id = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    logo_url = Column(String(500))
    category = Column(String(50), index=True)
    is_broadcast_tv = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    streams = relationship("Stream", back_populates="channel", cascade="all, delete-orphan")


class Stream(Base):
    __tablename__ = "streams"

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(1000), nullable=False)
    referrer = Column(String(500))
    user_agent = Column(String(500))
    quality = Column(String(20))
    is_healthy = Column(Boolean, index=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    last_checked_at = Column(DateTime)
    # reportado pelo NAVEGADOR do usuário quando o player falha de verdade, mesmo
    # depois do /resolve ter aprovado — sinal mais forte que qualquer checagem
    # server-side, porque reflete o que o cliente real conseguiu (ou não) tocar.
    # Ver ARQUITETURA.md secao 8.2.
    client_failed_at = Column(DateTime)
    client_failure_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    channel = relationship("Channel", back_populates="streams")


class Program(Base):
    __tablename__ = "programs"

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), nullable=False)
    subtitle = Column(String(500))
    description = Column(Text)
    category = Column(String(200))
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class VodTitle(Base):
    """Catálogo sob demanda (filmes/séries) — fica vazio até você adicionar
    títulos/links manualmente, conforme for conseguindo autorização pra cada
    obra. Nunca é populado automaticamente por nenhum worker. Ver
    ARQUITETURA.md seção 10."""

    __tablename__ = "vod_titles"

    id = Column(Integer, primary_key=True)
    type = Column(String(10), nullable=False)  # "movie" ou "series"
    title = Column(String(500), nullable=False)
    description = Column(Text)
    poster_url = Column(String(500))
    genre = Column(String(100))
    year = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())

    items = relationship("VodItem", back_populates="vod_title", cascade="all, delete-orphan")


class VodItem(Base):
    """Um item reproduzível: pra filme, 1 item por título (season/episode nulos);
    pra série, 1 item por episódio. `stream_url` fica NULL até você preencher —
    é o que marca o item como disponível ou não."""

    __tablename__ = "vod_items"

    id = Column(Integer, primary_key=True)
    title_id = Column(Integer, ForeignKey("vod_titles.id", ondelete="CASCADE"), nullable=False)
    season_number = Column(Integer)
    episode_number = Column(Integer)
    episode_title = Column(String(500))
    stream_url = Column(String(1000))
    created_at = Column(DateTime, server_default=func.now())

    # espelham as colunas equivalentes de Stream (canais ao vivo) — o
    # health-check manual/automático testa VOD junto com TV ao vivo agora
    is_healthy = Column(Boolean)
    consecutive_failures = Column(Integer, nullable=False, server_default="0")
    last_checked_at = Column(DateTime)

    vod_title = relationship("VodTitle", back_populates="items")


class AdminUser(Base):
    """Login do painel de administração (cadastro de links VOD) — separado do
    esquema de token-na-URL usado pra consumir a playlist."""

    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id = Column(Integer, primary_key=True)
    session_token = Column(String(64), unique=True, nullable=False)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)


class WorkerRun(Base):
    """1 linha por job do worker (fetch_channels/healthcheck/fetch_epg), sempre
    atualizada — última execução de cada um, pro dashboard."""

    __tablename__ = "worker_runs"

    job_name = Column(String(50), primary_key=True)
    last_run_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False)
    summary = Column(String(500))
    duration_seconds = Column(Integer)


class GenreKeyword(Base):
    """Palavra/expressão (EN ou PT) que indica um gênero, usada pra classificar
    títulos VOD sem gênero automaticamente por palavra-chave no título. Editável
    via /genres.html. A ordem de prioridade na classificação é pelo `id` mais
    antigo de cada gênero (gênero "descoberto" primeiro = checado primeiro)."""

    __tablename__ = "genre_keywords"

    id = Column(Integer, primary_key=True)
    genre = Column(String(100), nullable=False, index=True)
    keyword = Column(String(200), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class AccessToken(Base):
    __tablename__ = "access_tokens"

    id = Column(Integer, primary_key=True)
    token = Column(String(64), unique=True, nullable=False)
    label = Column(String(100))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    last_used_at = Column(DateTime)
