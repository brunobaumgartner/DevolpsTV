from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
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


class WorkerRun(Base):
    """1 linha por job (fetch_channels/healthcheck/fetch_epg), sempre
    atualizada (não é histórico) — só pra dar visibilidade de quando cada job
    rodou por último e com que resultado, já que hoje isso só existe no log
    do container (que se perde). Ver dashboard.html."""

    __tablename__ = "worker_runs"

    job_name = Column(String(50), primary_key=True)
    last_run_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False)  # "ok" ou "error"
    summary = Column(String(500))
    duration_seconds = Column(Integer)
