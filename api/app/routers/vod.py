"""Catálogo sob demanda (filmes/séries). A tabela é preenchida manualmente por
você (ver README.md "Adicionando títulos ao catálogo VOD") conforme for
conseguindo autorização pra cada obra — nenhum worker popula isso
automaticamente, e nenhuma fonte externa é consultada aqui."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import AccessToken, VodTitle
from ..security import require_valid_token

router = APIRouter()


def _has_available_item(vod_title: VodTitle) -> bool:
    return any(item.stream_url for item in vod_title.items)


@router.get("/p/{token}/vod")
def list_vod(
    token: str,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    titles = db.query(VodTitle).options(joinedload(VodTitle.items)).order_by(VodTitle.title).all()
    return {
        "count": len(titles),
        "titles": [
            {
                "id": t.id,
                "type": t.type,
                "title": t.title,
                "poster_url": t.poster_url,
                "genre": t.genre,
                "year": t.year,
                "available": _has_available_item(t),
                "episode_count": len(t.items) if t.type == "series" else None,
            }
            for t in titles
        ],
    }


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
        "genre": t.genre,
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
