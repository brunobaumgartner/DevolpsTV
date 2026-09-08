"""Painel de administração: login e cadastro/edição do catálogo VOD (filmes/
séries) via formulário web, além do importador CSV (api/app/import_vod.py,
continua existindo pra cargas em lote)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from ..auth_admin import SESSION_COOKIE_NAME, create_session, require_admin, verify_password
from ..db import get_db
from ..import_vod import import_rows_from_text
from ..models import AdminUser, VodItem, VodTitle

router = APIRouter(prefix="/admin")


class LoginRequest(BaseModel):
    username: str
    password: str


class MovieRequest(BaseModel):
    title: str
    description: Optional[str] = None
    poster_url: Optional[str] = None
    genre: Optional[str] = None
    year: Optional[int] = None
    stream_url: Optional[str] = None


class SeriesRequest(BaseModel):
    title: str
    description: Optional[str] = None
    poster_url: Optional[str] = None
    genre: Optional[str] = None
    year: Optional[int] = None
    # opcional: já cria o 1º episódio junto, pra não obrigar 2 passos separados
    # quando só tem 1 link na mão. Mais episódios sempre dá pra adicionar depois.
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    episode_title: Optional[str] = None
    stream_url: Optional[str] = None


class EpisodeRequest(BaseModel):
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    episode_title: Optional[str] = None
    stream_url: Optional[str] = None


class UpdateItemRequest(BaseModel):
    stream_url: Optional[str] = None
    episode_title: Optional[str] = None


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(AdminUser.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    token = create_session(db, user.id)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=14 * 24 * 3600,
        path="/",
    )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(admin: AdminUser = Depends(require_admin)):
    return {"username": admin.username}


@router.get("/vod")
def admin_list_vod(db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    titles = db.query(VodTitle).options(joinedload(VodTitle.items)).order_by(VodTitle.title).all()
    return {
        "titles": [
            {
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
                        "stream_url": i.stream_url,
                    }
                    for i in sorted(t.items, key=lambda i: (i.season_number or 0, i.episode_number or 0))
                ],
            }
            for t in titles
        ]
    }


_MAX_CSV_BYTES = 5 * 1024 * 1024  # 5MB é bem mais que suficiente pra uma lista de títulos


@router.post("/vod/import-csv")
async def import_csv_upload(
    file: UploadFile,
    _admin: AdminUser = Depends(require_admin),
):
    """Mesma lógica do `python -m app.import_vod` (idempotente, nunca apaga um
    stream_url existente com uma célula em branco), só que via upload no painel
    web em vez de precisar copiar o arquivo pra VPS antes."""
    raw = await file.read(_MAX_CSV_BYTES + 1)
    if len(raw) > _MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV maior que 5MB")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Arquivo precisa ser CSV em UTF-8")

    try:
        stats = import_rows_from_text(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return stats


@router.post("/vod/movie")
def add_movie(payload: MovieRequest, db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    title = VodTitle(
        type="movie",
        title=payload.title,
        description=payload.description,
        poster_url=payload.poster_url,
        genre=payload.genre,
        year=payload.year,
    )
    db.add(title)
    db.flush()
    db.add(VodItem(title_id=title.id, stream_url=payload.stream_url))
    db.commit()
    return {"id": title.id}


@router.post("/vod/series")
def add_series(payload: SeriesRequest, db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    title = VodTitle(
        type="series",
        title=payload.title,
        description=payload.description,
        poster_url=payload.poster_url,
        genre=payload.genre,
        year=payload.year,
    )
    db.add(title)
    db.flush()

    # se algum campo de episódio veio preenchido, já cria o 1º episódio junto
    # (evita o passo extra de ter que descer até o catálogo pra colar o link)
    has_episode_data = any(
        v is not None for v in (payload.season_number, payload.episode_number, payload.episode_title, payload.stream_url)
    )
    if has_episode_data:
        db.add(
            VodItem(
                title_id=title.id,
                season_number=payload.season_number,
                episode_number=payload.episode_number,
                episode_title=payload.episode_title,
                stream_url=payload.stream_url,
            )
        )

    db.commit()
    return {"id": title.id}


@router.post("/vod/{title_id}/episodes")
def add_episode(
    title_id: int,
    payload: EpisodeRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    title = db.query(VodTitle).filter(VodTitle.id == title_id).first()
    if title is None:
        raise HTTPException(status_code=404, detail="Título não encontrado")

    item = VodItem(
        title_id=title_id,
        season_number=payload.season_number,
        episode_number=payload.episode_number,
        episode_title=payload.episode_title,
        stream_url=payload.stream_url,
    )
    db.add(item)
    db.commit()
    return {"id": item.id}


@router.patch("/vod/items/{item_id}")
def update_item(
    item_id: int,
    payload: UpdateItemRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    item = db.query(VodItem).filter(VodItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")

    item.stream_url = payload.stream_url
    if payload.episode_title is not None:
        item.episode_title = payload.episode_title
    db.commit()
    return {"ok": True}


@router.delete("/vod/titles/{title_id}")
def delete_title(title_id: int, db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    title = db.query(VodTitle).filter(VodTitle.id == title_id).first()
    if title is None:
        raise HTTPException(status_code=404, detail="Título não encontrado")
    db.delete(title)
    db.commit()
    return {"ok": True}


@router.delete("/vod/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    item = db.query(VodItem).filter(VodItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True}
