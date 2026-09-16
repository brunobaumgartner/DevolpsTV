from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AccessToken
from ..playlist_builder import VOD_M3U_MAX_TITLES, build_m3u, build_vod_m3u
from ..security import require_valid_token
from .vod import _hide_adult

router = APIRouter()


@router.get("/p/{token}/playlist.m3u8")
def playlist(
    token: str,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Só TV ao vivo -- pra VOD ver /p/{token}/playlist-vod.m3u8, que é
    paginado/filtrado (o catálogo de VOD é grande demais pra caber junto,
    ver playlist_builder.VOD_M3U_MAX_TITLES)."""
    content = build_m3u(db)
    return PlainTextResponse(content, media_type="audio/x-mpegurl")


@router.get("/p/{token}/playlist-vod.m3u8")
def playlist_vod(
    token: str,
    type: Optional[str] = None,  # noqa: A002 - nome claro pro cliente
    genre: Optional[str] = None,
    limit: int = Query(300, ge=1, le=VOD_M3U_MAX_TITLES),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    access: AccessToken = Depends(require_valid_token),
):
    """Playlist M3U só de VOD (filmes/séries), sempre filtrada e paginada por
    título -- use `genre`/`type` pra escolher a fatia do catálogo e
    `limit`/`offset` pra paginar dentro dela. Sem filtro nenhum, pega os
    primeiros `limit` títulos em ordem alfabética (ainda assim nunca o
    catálogo inteiro de uma vez)."""
    content = build_vod_m3u(
        db, type=type, genre=genre, hide_adult=_hide_adult(access), limit=limit, offset=offset
    )
    return PlainTextResponse(content, media_type="audio/x-mpegurl")
