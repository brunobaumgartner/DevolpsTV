from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..categories_pt import category_label
from ..epg import now_playing_map, upcoming_programs
from ..live_check import resolve_live_url
from ..models import AccessToken, Channel, Stream
from ..playlist_builder import (
    active_channels_with_all_streams,
    ranked_stream_urls,
    ranked_streams_by_language,
)
from ..security import require_valid_token

router = APIRouter()


class FailureReport(BaseModel):
    url: str


@router.get("/p/{token}/channels.json")
def list_channels(
    token: str,
    response: Response,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    # muda no máximo a cada ciclo de health-check (15min); 120s é seguro e já
    # evita rebaixar a lista ao navegar entre telas
    response.headers["Cache-Control"] = "public, max-age=120"
    entries = [
        (channel, streams)
        for channel, streams in active_channels_with_all_streams(db)
        if not category or channel.category == category
    ]
    now_playing = now_playing_map(db, [channel.id for channel, _ in entries])

    items = []
    for channel, streams in entries:
        program = now_playing.get(channel.id)
        # idiomas disponíveis pro canal (Português primeiro). Se só tiver 1, o
        # frontend nem mostra seletor — comportamento idêntico ao de antes.
        languages = ranked_streams_by_language(channel)
        items.append(
            {
                "tvg_id": channel.tvg_id,
                "name": channel.name,
                "logo_url": channel.logo_url,
                "backdrop_url": channel.backdrop_url,
                "description": channel.description,
                "category": channel.category,
                "category_label": category_label(channel.category),
                "is_broadcast_tv": channel.is_broadcast_tv,
                # stream_url / stream_urls: mantidos por compatibilidade — apontam
                # pro 1º idioma da lista (Português quando existe)
                "stream_url": languages[0]["stream_urls"][0] if languages else streams[0].url,
                "stream_urls": languages[0]["stream_urls"] if languages else [s.url for s in streams],
                "languages": languages,
                "quality": streams[0].quality,
                "now_playing": {"title": program.title, "ends_at": program.end_time.isoformat()}
                if program
                else None,
            }
        )
    return {"count": len(items), "channels": items}


@router.get("/p/{token}/channels/{tvg_id}/resolve")
def resolve_channel(
    token: str,
    tvg_id: str,
    lang: Optional[str] = None,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Verifica AO VIVO (na hora, não pelo cache do health-check) qual mirror do
    canal está respondendo agora, e devolve só esse. Evita mostrar como
    'disponível' um canal cuja fonte já caiu desde a última checagem periódica.
    Com `?lang=`, testa só os mirrors daquele idioma."""
    channel = db.query(Channel).filter(Channel.tvg_id == tvg_id, Channel.is_active.is_(True)).first()
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")

    candidates = ranked_stream_urls(channel, lang=lang)
    live_url = resolve_live_url(candidates)
    if live_url is None:
        suffix = f" em {lang}" if lang else ""
        raise HTTPException(
            status_code=503,
            detail=f"Nenhum dos {len(candidates)} servidor(es) desse canal{suffix} respondeu agora.",
        )
    return {"tvg_id": tvg_id, "url": live_url, "checked_mirrors": len(candidates), "lang": lang}


@router.get("/p/{token}/channels/{tvg_id}/epg")
def channel_epg(
    token: str,
    tvg_id: str,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Grade de programação (próximas ~12h) de um canal, quando disponível.
    Nem todo canal tem EPG — a fonte cruza por nome exato, então cobre uma
    fração do catálogo (ver ARQUITETURA.md seção 8.3)."""
    channel = db.query(Channel).filter(Channel.tvg_id == tvg_id).first()
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")

    programs = upcoming_programs(db, channel.id)
    return {
        "tvg_id": tvg_id,
        "has_epg": len(programs) > 0,
        "programs": [
            {
                "title": p.title,
                "subtitle": p.subtitle,
                "description": p.description,
                # gravados UTC-naive no banco — "Z" explícito pro navegador
                # não interpretar como horário local
                "starts_at": p.start_time.isoformat() + "Z",
                "ends_at": p.end_time.isoformat() + "Z",
            }
            for p in programs
        ],
    }


@router.post("/p/{token}/channels/{tvg_id}/report-failure")
def report_failure(
    token: str,
    tvg_id: str,
    report: FailureReport,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Chamado pelo FRONTEND quando o player realmente falhou em tocar um mirror
    (mesmo depois do /resolve ter aprovado). Esse sinal é mais confiável que
    qualquer checagem server-side — reflete o que o navegador do usuário real
    conseguiu (ou não). Suprime o mirror da listagem por um tempo (ver
    playlist_builder.CLIENT_FAILURE_SUPPRESS_MINUTES) em vez de excluir pra
    sempre, já que essas fontes se recuperam sozinhas com frequência."""
    channel = db.query(Channel).filter(Channel.tvg_id == tvg_id).first()
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")

    stream = db.query(Stream).filter(Stream.channel_id == channel.id, Stream.url == report.url).first()
    if stream is None:
        raise HTTPException(status_code=404, detail="Stream não encontrado nesse canal")

    stream.client_failed_at = datetime.now(timezone.utc)
    stream.client_failure_count += 1
    db.commit()
    return {"ok": True, "client_failure_count": stream.client_failure_count}
