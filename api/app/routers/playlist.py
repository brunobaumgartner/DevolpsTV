from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AccessToken
from ..playlist_builder import build_m3u
from ..security import require_valid_token

router = APIRouter()


@router.get("/p/{token}/playlist.m3u8")
def playlist(
    token: str,
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    content = build_m3u(db)
    return PlainTextResponse(content, media_type="audio/x-mpegurl")
