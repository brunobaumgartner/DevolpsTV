"""Catálogo sob demanda (filmes/séries). A tabela é preenchida manualmente por
você (ver README.md "Adicionando títulos ao catálogo VOD") conforme for
conseguindo autorização pra cada obra — nenhum worker popula isso
automaticamente, e nenhuma fonte externa é consultada aqui."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..live_check import resolve_live_url
from ..models import AccessToken, VodItem, VodStream, VodTitle, WatchProgress
from ..security import require_valid_token
from ..vod_mirrors import item_has_healthy_mirror, ranked_mirror_urls

router = APIRouter()


class FailureReport(BaseModel):
    url: str

# valor especial no filtro de gênero pra "títulos sem gênero"
GENRE_NONE = "Outros"

# fração do vídeo a partir da qual consideramos "assistido até o fim"
FINISH_RATIO = 0.92


def _healthy_titles_query(db: Session):
    """IDs de título que têm pelo menos 1 item com pelo menos 1 mirror
    saudável — mesmo critério que já esconde canal ao vivo sem stream
    saudável (`playlist_builder._active_channels`). Um título só sai da
    listagem quando TODOS os links de TODOS os episódios/filme falharem no
    health-check; volta sozinho assim que um mirror voltar a passar."""
    return (
        db.query(VodItem.title_id)
        .join(VodStream, VodStream.item_id == VodItem.id)
        .filter(VodStream.is_healthy.is_(True))
        .distinct()
    )


@router.get("/p/{token}/vod")
def list_vod(
    token: str,
    response: Response,
    type: Optional[str] = None,  # noqa: A002 - nome claro pro cliente
    genre: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    response.headers["Cache-Control"] = "public, max-age=120"
    """Listagem paginada e filtrada no servidor. NÃO devolve os episódios/itens
    (era isso que deixava lento: 25k títulos puxavam 237k itens juntos) — a
    disponibilidade e a contagem de episódios vêm de agregados baratos, e a
    lista de episódios só é carregada ao abrir um título (/vod/{id})."""
    base = db.query(VodTitle).filter(VodTitle.id.in_(_healthy_titles_query(db)))
    if type in ("movie", "series"):
        base = base.filter(VodTitle.type == type)
    if genre == GENRE_NONE:
        base = base.filter(VodTitle.genre.is_(None))
    elif genre:
        base = base.filter(VodTitle.genre == genre)
    if q:
        base = base.filter(VodTitle.title.ilike(f"%{q.strip()}%"))

    total = base.with_entities(func.count(VodTitle.id)).scalar() or 0

    rows = (
        base.add_columns(func.count(VodItem.id).label("item_count"))
        .outerjoin(VodItem, VodItem.title_id == VodTitle.id)
        .group_by(VodTitle.id)
        .order_by(VodTitle.title)
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "count": total,
        "titles": [
            {
                "id": t.id,
                "type": t.type,
                "title": t.title,
                "poster_url": t.poster_url,
                "genre": t.genre or GENRE_NONE,
                "year": t.year,
                # sempre True aqui: a listagem já filtrou pra só títulos com
                # pelo menos 1 mirror saudável (ver _healthy_titles_query)
                "available": True,
                "episode_count": item_count if t.type == "series" else None,
            }
            for (t, item_count) in rows
        ],
    }


def _genre_counts(db):
    """[(genre_ou_'Outros', count)] ordenado do maior pro menor. 'Outros' (sem
    gênero) sempre por último. Só conta títulos com pelo menos 1 mirror
    saudável (mesmo critério da listagem) — senão os chips de gênero
    mostrariam números maiores do que o que a listagem filtrada realmente
    devolve."""
    rows = (
        db.query(VodTitle.genre, func.count(VodTitle.id))
        .filter(VodTitle.id.in_(_healthy_titles_query(db)))
        .group_by(VodTitle.genre)
        .all()
    )
    named = sorted(((g, c) for g, c in rows if g), key=lambda x: -x[1])
    none_c = sum(c for g, c in rows if g is None)
    if none_c:
        named.append((GENRE_NONE, none_c))
    return named


@router.get("/p/{token}/vod/genres")
def list_vod_genres(
    token: str,
    response: Response,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Gêneros do catálogo com contagem, do maior pro menor ('Outros' por
    último). Sem 'Todos'."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"genres": [{"genre": g, "count": c} for g, c in _genre_counts(db)]}


@router.get("/p/{token}/vod/home")
def vod_home(
    token: str,
    response: Response,
    per_genre: int = Query(15, ge=1, le=40),
    max_genres: int = Query(12, ge=1, le=30),
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    response.headers["Cache-Control"] = "public, max-age=180"
    """As primeiras fileiras da Home num request só (senão a Home dispara ~20
    requests, um por gênero). Sem itens/episódios."""
    out = []
    for genre, _count in _genre_counts(db)[:max_genres]:
        q = db.query(VodTitle).filter(VodTitle.id.in_(_healthy_titles_query(db)))
        if genre == GENRE_NONE:
            q = q.filter(VodTitle.genre.is_(None))
        else:
            q = q.filter(VodTitle.genre == genre)
        titles = q.order_by(VodTitle.id.desc()).limit(per_genre).all()
        out.append(
            {
                "genre": genre,
                "titles": [
                    {
                        "id": t.id,
                        "type": t.type,
                        "title": t.title,
                        "poster_url": t.poster_url,
                        "genre": t.genre or GENRE_NONE,
                        "year": t.year,
                    }
                    for t in titles
                ],
            }
        )
    return {"rows": out}


@router.get("/p/{token}/vod/{title_id}")
def vod_detail(
    token: str,
    title_id: int,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    t = (
        db.query(VodTitle)
        .options(joinedload(VodTitle.items).joinedload(VodItem.streams))
        .filter(VodTitle.id == title_id)
        .first()
    )
    if t is None:
        raise HTTPException(status_code=404, detail="Título não encontrado")

    items = sorted(t.items, key=lambda i: (i.season_number or 0, i.episode_number or 0))
    wp = (
        db.query(WatchProgress)
        .filter(WatchProgress.token_id == _access.id, WatchProgress.title_id == t.id)
        .first()
    )
    return {
        "id": t.id,
        "type": t.type,
        "title": t.title,
        "description": t.description,
        "poster_url": t.poster_url,
        "backdrop_url": t.backdrop_url,
        "genre": t.genre or GENRE_NONE,
        "year": t.year,
        "rating": t.rating,
        "progress": (
            {"item_id": wp.item_id, "position": wp.position, "duration": wp.duration}
            if wp
            else None
        ),
        "items": [
            {
                "id": i.id,
                "season_number": i.season_number,
                "episode_number": i.episode_number,
                "episode_title": i.episode_title,
                # disponível = tem mirror que passou no health-check (não só
                # "tem link cadastrado") — numa série, cada episódio tem seu
                # próprio status: só o(s) que estiver(em) com link saudável
                # aparece(m) como assistível, os outros ficam "sem link" até
                # algum mirror deles voltar a passar no teste.
                "available": item_has_healthy_mirror(i),
                # a URL só é revelada aqui, no detalhe de um título específico já
                # autenticado por token — não aparece na listagem geral. Mantida
                # por compatibilidade (play imediato); o player deve preferir
                # /resolve, que testa os mirrors de verdade na hora de tocar.
                "stream_url": i.stream_url,
            }
            for i in items
        ],
    }


@router.get("/p/{token}/vod/items/{item_id}/resolve")
def resolve_vod_item(
    token: str,
    item_id: int,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Mesma ideia do /resolve de canal ao vivo: testa os mirrors do item AGORA
    (não pelo cache do health-check periódico) e devolve o primeiro que
    responder de verdade. Permite ter mais de um link por filme/episódio
    (ex: vindos de fontes/CSVs diferentes) com fallback automático."""
    item = db.query(VodItem).options(joinedload(VodItem.streams)).filter(VodItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")

    candidates = ranked_mirror_urls(item)
    live_url = resolve_live_url(candidates)
    if live_url is None:
        raise HTTPException(
            status_code=503,
            detail=f"Nenhum dos {len(candidates)} link(s) desse item respondeu agora.",
        )
    return {"item_id": item_id, "url": live_url, "checked_mirrors": len(candidates)}


@router.post("/p/{token}/vod/items/{item_id}/report-failure")
def report_vod_failure(
    token: str,
    item_id: int,
    report: FailureReport,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Chamado pelo frontend quando o player realmente falhou em tocar um
    mirror (mesmo depois do /resolve ter aprovado) — mesmo mecanismo do
    report-failure de canal ao vivo (ver channels.py)."""
    stream = db.query(VodStream).filter(VodStream.item_id == item_id, VodStream.url == report.url).first()
    if stream is None:
        raise HTTPException(status_code=404, detail="Mirror não encontrado nesse item")

    stream.client_failed_at = datetime.now(timezone.utc)
    stream.client_failure_count += 1
    db.commit()
    return {"ok": True, "client_failure_count": stream.client_failure_count}


# ---------------- "Continuar assistindo" ----------------


class ProgressIn(BaseModel):
    title_id: int
    item_id: Optional[int] = None
    position: float
    duration: Optional[float] = None


def _next_episode(db: Session, title_id: int, item_id: Optional[int]) -> Optional[VodItem]:
    """Próximo episódio disponível (com stream_url) depois do item atual."""
    if item_id is None:
        return None
    cur = db.query(VodItem).filter(VodItem.id == item_id).first()
    if cur is None:
        return None
    key = (cur.season_number or 0, cur.episode_number or 0)
    eps = (
        db.query(VodItem)
        .options(joinedload(VodItem.streams))
        .filter(VodItem.title_id == title_id)
        .all()
    )
    eps = [e for e in eps if item_has_healthy_mirror(e)]
    nxt = sorted(
        (e for e in eps if (e.season_number or 0, e.episode_number or 0) > key),
        key=lambda e: (e.season_number or 0, e.episode_number or 0),
    )
    return nxt[0] if nxt else None


@router.post("/p/{token}/progress")
def save_progress(
    token: str,
    payload: ProgressIn,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Upsert da posição. Se o vídeo foi assistido até o fim (>= FINISH_RATIO):
    série -> avança pro próximo episódio; filme ou último episódio -> sai da
    lista."""
    row = (
        db.query(WatchProgress)
        .filter(WatchProgress.token_id == _access.id, WatchProgress.title_id == payload.title_id)
        .first()
    )
    dur = payload.duration or (row.duration if row else None)
    finished = bool(dur and dur > 0 and payload.position / dur >= FINISH_RATIO)

    if finished:
        nxt = _next_episode(db, payload.title_id, payload.item_id)
        if nxt is not None:
            if row is None:
                row = WatchProgress(token_id=_access.id, title_id=payload.title_id)
                db.add(row)
            row.item_id = nxt.id
            row.position = 0
            row.duration = None
            db.commit()
            return {"ok": True, "removed": False, "advanced_to": nxt.id}
        if row is not None:
            db.delete(row)
            db.commit()
        return {"ok": True, "removed": True}

    if row is None:
        row = WatchProgress(token_id=_access.id, title_id=payload.title_id)
        db.add(row)
    row.item_id = payload.item_id
    row.position = max(0.0, payload.position)
    if payload.duration:
        row.duration = payload.duration
    db.commit()
    return {"ok": True, "removed": False}


@router.delete("/p/{token}/progress/{title_id}")
def remove_progress(
    token: str,
    title_id: int,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    db.query(WatchProgress).filter(
        WatchProgress.token_id == _access.id, WatchProgress.title_id == title_id
    ).delete()
    db.commit()
    return {"ok": True}


@router.get("/p/{token}/continue-watching")
def continue_watching(
    token: str,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    rows = (
        db.query(WatchProgress)
        .filter(WatchProgress.token_id == _access.id)
        .order_by(WatchProgress.updated_at.desc())
        .limit(limit)
        .all()
    )
    title_ids = [r.title_id for r in rows]
    item_ids = [r.item_id for r in rows if r.item_id]
    titles = {t.id: t for t in db.query(VodTitle).filter(VodTitle.id.in_(title_ids or [0]))}
    items = {i.id: i for i in db.query(VodItem).filter(VodItem.id.in_(item_ids or [0]))}

    out = []
    for r in rows:
        t = titles.get(r.title_id)
        if t is None:
            continue
        it = items.get(r.item_id) if r.item_id else None
        ep_label = None
        if it is not None:
            ep_label = f"T{it.season_number or '?'}E{it.episode_number or '?'}"
        pct = (r.position / r.duration) if (r.duration and r.duration > 0) else 0
        out.append(
            {
                "title_id": t.id,
                "type": t.type,
                "title": t.title,
                "poster_url": t.poster_url,
                "backdrop_url": t.backdrop_url,
                "position": r.position,
                "duration": r.duration,
                "pct": round(min(max(pct, 0), 1), 3),
                "item_id": r.item_id,
                "episode_label": ep_label,
                "episode_title": it.episode_title if it else None,
            }
        )
    return {"items": out}
