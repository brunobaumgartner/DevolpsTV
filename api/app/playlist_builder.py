from datetime import datetime, timedelta, timezone

from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from .models import Channel, Stream

# por quanto tempo um "falhou de verdade no navegador" reportado pelo cliente
# continua suprimindo o stream da lista, mesmo que o health-check do worker
# ache ele saudável. Depois desse prazo, volta a ser oferecido normalmente —
# dá chance de se recuperar sem precisar de intervenção manual.
CLIENT_FAILURE_SUPPRESS_MINUTES = 30


def _is_client_suppressed(stream: Stream) -> bool:
    if stream.client_failed_at is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CLIENT_FAILURE_SUPPRESS_MINUTES)
    failed_at = stream.client_failed_at
    if failed_at.tzinfo is None:
        failed_at = failed_at.replace(tzinfo=timezone.utc)
    return failed_at > cutoff


def _ranked_streams(channel: Channel):
    """Todos os mirrors saudáveis de um canal (e sem reporte recente de falha real
    do navegador de um usuário), do melhor pro pior (menos falhas seguidas,
    checado mais recentemente primeiro)."""
    candidates = [s for s in channel.streams if s.is_healthy and not _is_client_suppressed(s)]
    if not candidates:
        return []
    fallback = datetime(2000, 1, 1)
    candidates.sort(key=lambda s: (s.consecutive_failures, -(s.last_checked_at or fallback).timestamp()))
    return candidates


def _best_stream(channel: Channel):
    ranked = _ranked_streams(channel)
    return ranked[0] if ranked else None


def _active_channels(db: Session):
    # joinedload dos streams: sem isso cada canal disparava 1 SELECT lazy dos
    # próprios streams (N+1) — ~250 queries a mais por chamada de channels.json
    return (
        db.query(Channel)
        .options(joinedload(Channel.streams))
        .filter(Channel.is_active.is_(True))
        .filter(Channel.streams.any(and_(Stream.is_healthy.is_(True))))
        .order_by(Channel.category, Channel.name)
        .all()
    )


def active_channels_with_stream(db: Session):
    """Canais ativos que têm pelo menos 1 stream saudável, já com o melhor stream escolhido."""
    result = []
    for ch in _active_channels(db):
        stream = _best_stream(ch)
        if stream is not None:
            result.append((ch, stream))
    return result


def ranked_stream_urls(channel: Channel, max_mirrors: int = 5, lang: str | None = None) -> list[str]:
    """URLs dos mirrors saudáveis de um canal, do melhor pro pior — usado pra
    verificação ao vivo na hora que o usuário pede pra assistir. Se `lang` for
    passado, só os streams daquele idioma (rótulo)."""
    streams = _ranked_streams(channel)
    if lang is not None:
        streams = [s for s in streams if _stream_lang(s) == lang]
    return [s.url for s in streams[:max_mirrors]]


def _stream_lang(stream: Stream) -> str:
    """Rótulo de idioma do stream; NULL no banco = 'Português' (canal de país
    lusófono / fonte brasileira sem info de feed)."""
    return stream.lang_label or "Português"


# "Português" primeiro, "Legendado" logo depois, o resto em ordem alfabética
_LANG_ORDER = {"Português": 0, "Legendado": 1}


def ranked_streams_by_language(channel: Channel, max_mirrors: int = 3) -> list[dict]:
    """Agrupa os mirrors saudáveis do canal por idioma, cada grupo já ordenado
    do melhor mirror pro pior. Usado pro frontend listar os idiomas disponíveis
    e o usuário escolher qual tocar."""
    groups: dict[str, list[str]] = {}
    for s in _ranked_streams(channel):
        groups.setdefault(_stream_lang(s), []).append(s.url)
    ordered = sorted(groups.items(), key=lambda kv: (_LANG_ORDER.get(kv[0], 2), kv[0]))
    return [{"label": label, "stream_urls": urls[:max_mirrors]} for label, urls in ordered]


def active_channels_with_all_streams(db: Session, max_mirrors: int = 3):
    """Igual a active_channels_with_stream, mas traz até `max_mirrors` streams saudáveis
    por canal (do melhor pro pior) — usado pro frontend tentar o próximo mirror
    automaticamente se o primeiro falhar na hora de reproduzir."""
    result = []
    for ch in _active_channels(db):
        ranked = _ranked_streams(ch)[:max_mirrors]
        if ranked:
            result.append((ch, ranked))
    return result


def build_m3u(db: Session) -> str:
    lines = ["#EXTM3U"]
    for channel, stream in active_channels_with_stream(db):
        group = channel.category or "outros"
        logo_attr = f' tvg-logo="{stream_escape(channel.logo_url)}"' if channel.logo_url else ""
        lines.append(
            f'#EXTINF:-1 tvg-id="{stream_escape(channel.tvg_id)}"{logo_attr} '
            f'group-title="{stream_escape(group)}",{stream_escape(channel.name)}'
        )
        if stream.referrer:
            lines.append(f"#EXTVLCOPT:http-referrer={stream.referrer}")
        if stream.user_agent:
            lines.append(f"#EXTVLCOPT:http-user-agent={stream.user_agent}")
        lines.append(stream.url)
    return "\n".join(lines) + "\n"


def stream_escape(value: str) -> str:
    """Escape simples para não quebrar os atributos do EXTINF."""
    if value is None:
        return ""
    return value.replace('"', "'")
