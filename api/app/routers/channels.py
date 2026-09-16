from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from .. import languages
from ..db import get_db
from ..categories_pt import category_label
from ..epg import now_playing_map, upcoming_programs
from ..models import AccessToken, Channel, Program, Stream
from ..playlist_builder import (
    _ranked_streams,
    ranked_stream_urls,
    ranked_streams_by_language,
)
from ..security import require_valid_token

router = APIRouter()

# valor especial no filtro de categoria pra "canais sem categoria"
CATEGORY_NONE = "Sem categoria"

# categoria "Adulto" só aparece (chip, listagem, Home, resolve) pro token
# marcado com sees_adult_content -- mesma regra do gênero "Adulto" do VOD
# (ver ADULT_GENRE em routers/vod.py). Pedido explícito do produto em 2026-09-13.
ADULT_CATEGORY = "Adulto"


class FailureReport(BaseModel):
    url: str


def _hide_adult(access: AccessToken) -> bool:
    return not (access and access.sees_adult_content)


def _visible_channels_query(db: Session, hide_adult: bool = True):
    """Canais que aparecem na listagem: ativos e com pelo menos 1 stream
    cadastrado (mesmo critério de active_channels_with_all_streams, mas sem
    trazer os streams — usado tanto pra paginar quanto pra contar categorias
    sem carregar o catálogo inteiro)."""
    q = db.query(Channel).filter(Channel.is_active.is_(True)).filter(Channel.streams.any())
    if hide_adult:
        # category != ADULT_CATEGORY sozinho excluiria quem tem category NULL
        # (NULL != 'Adulto' dá NULL em SQL, não TRUE) -- por isso o OR explícito
        q = q.filter(or_(Channel.category != ADULT_CATEGORY, Channel.category.is_(None)))
    return q


def _serialize_channel(channel: Channel, program=None):
    """Item de canal como o frontend espera. Devolve None quando o canal não
    tem nenhum mirror utilizável no momento (todos suprimidos por falha real
    reportada pelo navegador)."""
    streams = _ranked_streams(channel)[:3]
    if not streams:
        return None
    # idiomas disponíveis pro canal (Português primeiro). Se só tiver 1, o
    # frontend nem mostra seletor.
    languages = ranked_streams_by_language(channel)
    return {
        "tvg_id": channel.tvg_id,
        "name": channel.name,
        "logo_url": channel.logo_url,
        "backdrop_url": channel.backdrop_url,
        "description": channel.description,
        "category": channel.category,
        "category_label": category_label(channel.category),
        "is_broadcast_tv": channel.is_broadcast_tv,
        # stream_url / stream_urls: mantidos por compatibilidade — apontam pro
        # 1º idioma da lista (Português quando existe)
        "stream_url": languages[0]["stream_urls"][0] if languages else streams[0].url,
        "stream_urls": languages[0]["stream_urls"] if languages else [s.url for s in streams],
        "languages": languages,
        "quality": streams[0].quality,
        "now_playing": {"title": program.title, "ends_at": program.end_time.isoformat()} if program else None,
    }


LANGUAGE_NONE = languages.NONE_LABEL


def _language_counts(db: Session, hide_adult: bool = True):
    rows = (
        _visible_channels_query(db, hide_adult=hide_adult)
        .with_entities(Channel.language, func.count(Channel.id))
        .group_by(Channel.language)
        .all()
    )
    named = sorted(((l, n) for l, n in rows if l), key=lambda x: -x[1])
    none_n = sum(n for l, n in rows if l is None)
    if none_n:
        named.append((LANGUAGE_NONE, none_n))
    return named


def _category_counts(db: Session, hide_adult: bool = True):
    """[(categoria_ou_CATEGORY_NONE, count)] do maior pro menor, escopado aos
    canais visíveis. Compartilhado entre /channels/categories e /channels/home
    (mesmo padrão de _genre_counts em vod.py)."""
    rows = (
        _visible_channels_query(db, hide_adult=hide_adult)
        .with_entities(Channel.category, func.count(Channel.id))
        .group_by(Channel.category)
        .all()
    )
    named = sorted(((c, n) for c, n in rows if c), key=lambda x: -x[1])
    none_n = sum(n for c, n in rows if c is None)
    if none_n:
        named.append((CATEGORY_NONE, none_n))
    return named


@router.get("/p/{token}/channels.json")
def list_channels(
    token: str,
    response: Response,
    category: Optional[str] = None,
    language: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Listagem paginada e filtrada no servidor (achado em 2026-09-13: essa
    rota devolvia os ~56 mil canais ativos de uma vez, com streams/EPG/idiomas
    calculados pra cada um — era isso que deixava a tela de TV ao vivo lenta;
    o filtro por categoria/busca e a paginação ficavam todos no navegador).
    `language` filtra pelo idioma do CONTEÚDO do canal (Channel.language,
    recuperado dos dados originais de importação) -- não confundir com
    `?lang=` do /resolve, que escolhe entre mirrors de ÁUDIO do mesmo canal."""
    response.headers["Cache-Control"] = "public, max-age=120"
    base = _visible_channels_query(db, hide_adult=_hide_adult(_access))
    if category == CATEGORY_NONE:
        base = base.filter(Channel.category.is_(None))
    elif category:
        base = base.filter(Channel.category == category)
    if language == LANGUAGE_NONE:
        base = base.filter(Channel.language.is_(None))
    elif language:
        base = base.filter(Channel.language == language)
    if q:
        base = base.filter(Channel.name.ilike(f"%{q.strip()}%"))

    total = base.with_entities(func.count(Channel.id)).scalar() or 0

    page_channels = (
        base.options(joinedload(Channel.streams))
        .order_by(Channel.name)
        .offset(offset)
        .limit(limit)
        .all()
    )
    now_playing = now_playing_map(db, [channel.id for channel in page_channels])

    items = []
    for channel in page_channels:
        item = _serialize_channel(channel, now_playing.get(channel.id))
        if item is not None:
            items.append(item)
    return {"count": total, "channels": items}


@router.get("/p/{token}/channels/categories")
def list_channel_categories(
    token: str,
    response: Response,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Categorias com contagem real, do maior pro menor ('Sem categoria' por
    último) — escopadas aos mesmos canais que aparecem na listagem (ativos,
    com stream). Antes o chip bar era montado no navegador a partir da lista
    de canais já carregada, sem contagem e sem ordenação por relevância."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "categories": [
            {"category": c, "label": category_label(None if c == CATEGORY_NONE else c), "count": n}
            for c, n in _category_counts(db, hide_adult=_hide_adult(_access))
        ]
    }


@router.get("/p/{token}/channels/languages")
def list_channel_languages(
    token: str,
    response: Response,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Idiomas disponíveis com contagem, do maior pro menor -- usado pelo
    seletor de idioma da tela de TV ao vivo (pedido do produto em
    2026-09-13). Só aparece pro usuário quando há mais de 1 idioma real."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "languages": [
            {"language": l, "label": languages.label(None if l == LANGUAGE_NONE else l), "count": n}
            for l, n in _language_counts(db, hide_adult=_hide_adult(_access))
        ]
    }


@router.get("/p/{token}/channels/home")
def channels_home(
    token: str,
    response: Response,
    per_category: int = Query(20, ge=1, le=40),
    max_categories: int = Query(6, ge=1, le=20),
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Fileiras da Home (Agora na TV + categorias) num request só (achado em
    2026-09-13: a Home baixava os ~56 mil canais ativos inteiros só pra montar
    essas mesmas fileiras filtrando no navegador)."""
    response.headers["Cache-Control"] = "public, max-age=120"

    def _serialize(channels):
        now_playing = now_playing_map(db, [c.id for c in channels])
        out = []
        for c in channels:
            program = now_playing.get(c.id)
            out.append(
                {
                    "tvg_id": c.tvg_id,
                    "name": c.name,
                    "logo_url": c.logo_url,
                    "now_playing": {"title": program.title, "ends_at": program.end_time.isoformat()}
                    if program
                    else None,
                }
            )
        return out

    hide_adult = _hide_adult(_access)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    live_channels = (
        _visible_channels_query(db, hide_adult=hide_adult)
        .join(Program, Program.channel_id == Channel.id)
        .filter(Program.start_time <= now, Program.end_time > now)
        .order_by(Channel.name)
        .limit(per_category)
        .all()
    )

    rows = []
    for cat, _n in _category_counts(db, hide_adult=hide_adult)[:max_categories]:
        q = _visible_channels_query(db, hide_adult=hide_adult)
        q = q.filter(Channel.category.is_(None)) if cat == CATEGORY_NONE else q.filter(Channel.category == cat)
        channels = q.order_by(Channel.name).limit(per_category).all()
        rows.append({"category": cat, "label": category_label(None if cat == CATEGORY_NONE else cat), "channels": _serialize(channels)})

    return {"live_now": _serialize(live_channels), "rows": rows}


# IMPORTANTE: esta rota precisa ficar DEPOIS de /channels/categories e
# /channels/home -- o Starlette casa por ordem de registro, e "{tvg_id}"
# capturaria "categories"/"home" se viesse antes (mesma pegadinha já
# encontrada no admin.py em 2026-09-13).
@router.get("/p/{token}/channels/{tvg_id}")
def channel_detail(
    token: str,
    tvg_id: str,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Detalhe de UM canal pelo tvg_id. Existe porque a tela de assistir
    precisa do canal específico e a listagem virou paginada (achado em
    2026-09-13: o player procurava o canal dentro da lista de /channels.json,
    que passou a trazer só a 1ª página -- qualquer canal fora dela dava
    "Canal não encontrado ou fora do ar", ou seja, quase todos)."""
    channel = db.query(Channel).filter(Channel.tvg_id == tvg_id, Channel.is_active.is_(True)).first()
    if channel is None or (channel.category == ADULT_CATEGORY and _hide_adult(_access)):
        raise HTTPException(status_code=404, detail="Canal não encontrado")

    now_playing = now_playing_map(db, [channel.id])
    item = _serialize_channel(channel, now_playing.get(channel.id))
    if item is None:
        raise HTTPException(status_code=503, detail="Esse canal não tem nenhum mirror disponível agora.")
    return item


@router.get("/p/{token}/channels/{tvg_id}/resolve")
def resolve_channel(
    token: str,
    tvg_id: str,
    lang: Optional[str] = None,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Devolve o melhor mirror do canal pra tocar. Não testa mais ao vivo a
    partir do servidor (achado em 2026-09-13: o teste do servidor roda do IP
    da VPS, e vários provedores bloqueiam especificamente IP de datacenter —
    dá falso-negativo mesmo em mirror que funciona perfeitamente pro
    navegador do usuário real). A validação de verdade agora é o navegador:
    se a reprodução falhar de fato, o player chama /report-failure e tenta o
    próximo mirror sozinho. Com `?lang=`, só considera os mirrors daquele
    idioma."""
    channel = db.query(Channel).filter(Channel.tvg_id == tvg_id, Channel.is_active.is_(True)).first()
    # categoria "Adulto" só pro token autorizado -- mesma regra do VOD
    if channel is not None and channel.category == ADULT_CATEGORY and _hide_adult(_access):
        channel = None
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")

    candidates = ranked_stream_urls(channel, lang=lang)
    if not candidates:
        suffix = f" em {lang}" if lang else ""
        raise HTTPException(status_code=503, detail=f"Esse canal não tem nenhum mirror cadastrado{suffix}.")
    return {"tvg_id": tvg_id, "url": candidates[0], "checked_mirrors": len(candidates), "lang": lang}


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
