"""Catálogo sob demanda (filmes/séries). A tabela é preenchida manualmente por
você (ver README.md "Adicionando títulos ao catálogo VOD") conforme for
conseguindo autorização pra cada obra — nenhum worker popula isso
automaticamente, e nenhuma fonte externa é consultada aqui."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import AccessToken, VodItem, VodTitle
from ..security import require_valid_token

router = APIRouter()

# valor especial no filtro de gênero pra "títulos sem gênero"
GENRE_NONE = "Outros"


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
    base = db.query(VodTitle)
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
        base.add_columns(
            func.count(VodItem.id).label("item_count"),
            # count() ignora NULL — conta só itens com link
            func.count(VodItem.stream_url).label("available_count"),
        )
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
                "available": available_count > 0,
                "episode_count": item_count if t.type == "series" else None,
            }
            for (t, item_count, available_count) in rows
        ],
    }


def _genre_counts(db):
    """[(genre_ou_'Outros', count)] ordenado do maior pro menor. 'Outros' (sem
    gênero) sempre por último."""
    rows = db.query(VodTitle.genre, func.count(VodTitle.id)).group_by(VodTitle.genre).all()
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
        q = db.query(VodTitle)
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
    t = db.query(VodTitle).options(joinedload(VodTitle.items)).filter(VodTitle.id == title_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Título não encontrado")

    items = sorted(t.items, key=lambda i: (i.season_number or 0, i.episode_number or 0))
    return {
        "id": t.id,
        "type": t.type,
        "title": t.title,
        "description": t.description,
        "poster_url": t.poster_url,
        "genre": t.genre or GENRE_NONE,
        "year": t.year,
        "items": [
            {
                "id": i.id,
                "season_number": i.season_number,
                "episode_number": i.episode_number,
                "episode_title": i.episode_title,
                "available": i.stream_url is not None,
                # a URL só é revelada aqui, no detalhe de um título específico já
                # autenticado por token — não aparece na listagem geral
                "stream_url": i.stream_url,
            }
            for i in items
        ],
    }
