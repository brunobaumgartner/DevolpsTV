from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AccessToken
from ..playlist_builder import build_m3u, build_vod_m3u
from ..security import require_valid_token
from .vod import _hide_adult

router = APIRouter()


@router.get("/p/{token}/playlist.m3u8")
def playlist(
    token: str,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Só TV ao vivo -- pra VOD ver /p/{token}/playlist-vod.m3u8 (o catálogo de
    série multiplica por episódio e fica grande demais pra caber junto, ver
    playlist_builder.VOD_M3U_SERIES_MAX_TITLES)."""
    content = build_m3u(db)
    return PlainTextResponse(content, media_type="audio/x-mpegurl")


@router.get("/p/{token}/playlist-vod.m3u8")
def playlist_vod(
    token: str,
    type: Optional[str] = None,  # noqa: A002 - nome claro pro cliente
    genre: Optional[str] = None,
    limit: Optional[int] = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    access: AccessToken = Depends(require_valid_token),
):
    """Playlist M3U de VOD (filmes/séries). M3U não pagina de verdade pra
    quem consome (nenhum player "vira página"), então por padrão (sem
    `limit`) traz TODOS os títulos que baterem no filtro `type`/`genre` --
    não só os primeiros N. `?type=movie` sem `genre` já traz o catálogo de
    filme inteiro (organizado em categorias pelo gênero de cada um, o
    player agrupa sozinho pelo group-title). `?type=series` continua limitado
    (ver VOD_M3U_SERIES_MAX_TITLES): sem filtro de gênero, todas as séries
    juntas viram ~85MB/89s de resposta -- combine com `genre` pra série."""
    content = build_vod_m3u(
        db, type=type, genre=genre, hide_adult=_hide_adult(access), limit=limit, offset=offset
    )
    return PlainTextResponse(content, media_type="audio/x-mpegurl")
