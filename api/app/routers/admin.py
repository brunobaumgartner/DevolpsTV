"""Painel de administração: login e cadastro/edição do catálogo VOD (filmes/
séries) via formulário web, além do importador CSV (api/app/import_vod.py,
continua existindo pra cargas em lote)."""

import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..auth_admin import (
    SESSION_COOKIE_NAME,
    create_session,
    hash_password,
    require_admin,
    require_login,
    verify_password,
)
from ..channel_classifier import get_classify_channels_job, start_classify_channels_job
from ..dashboard import get_dashboard_stats
from ..db import get_db
from ..db_console import QueryError, describe_table, list_tables, run_query
from ..genre_classifier import get_classify_job, start_classify_job
from ..imdb_classifier import get_imdb_classify_job, is_dataset_available, start_imdb_classify_job
from ..job_registry import list_jobs, prune, request_cancel
from ..poster_fetch import get_tmdb_job, start_tmdb_job
from ..import_vod import get_import_job, start_import_job
from ..manual_healthcheck import get_healthcheck_job, start_healthcheck_job
from ..models import AccessToken, AdminUser, Channel, GenreKeyword, Stream, VodItem, VodTitle, WorkerRun
from ..system_info import snapshot as system_snapshot

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


class SetGenreRequest(BaseModel):
    genre: str


class LiveChannelRequest(BaseModel):
    tvg_id: str
    name: str
    category: Optional[str] = None
    logo_url: Optional[str] = None
    is_broadcast_tv: bool = False
    stream_url: str


class GenreKeywordRequest(BaseModel):
    genre: str
    keyword: str


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
def me(user: AdminUser = Depends(require_login), db: Session = Depends(get_db)):
    """Whoami pro site inteiro agora (não só o painel): devolve o papel e o
    token de conteúdo já resolvido, pra o front não precisar mais pedir pra
    colar link nenhum."""
    token = user.access_token.token if user.access_token else None
    if token is None and user.role == "admin":
        # admin sem token vinculado: pega o 1º token ativo da conta (mesmo
        # comportamento de antes, quando o front buscava via /admin/tokens)
        t = db.query(AccessToken).filter(AccessToken.is_active.is_(True)).order_by(AccessToken.created_at).first()
        token = t.token if t else None
    return {"username": user.username, "role": user.role, "token": token}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    return get_dashboard_stats(db)


@router.get("/tokens")
def list_tokens(db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    """Usado pelo botão 'Acessar minha lista' no painel: como só existe 1 admin
    (uso pessoal), qualquer token ativo cadastrado é 'do admin' — não há hoje
    uma associação formal token↔usuário além disso."""
    tokens = db.query(AccessToken).filter(AccessToken.is_active.is_(True)).order_by(AccessToken.created_at).all()
    return {"tokens": [{"token": t.token, "label": t.label} for t in tokens]}


@router.get("/vod")
def admin_list_vod(
    type: Optional[str] = None,  # noqa: A002
    genre: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 60,
    offset: int = 0,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    """Paginado e filtrado — a tela Catálogo carrega 26k+ títulos, carregar
    tudo de uma vez (com os 273k itens juntos, joinedload) era o que deixava
    a tela de Cadastro pesada (achado real em 2026-09-11). Os itens/episódios
    de cada título só vêm no detalhe (GET /admin/vod/{id}), aberto sob
    demanda ao expandir um título na lista."""
    limit = max(1, min(limit, 200))
    base = db.query(VodTitle)
    if type in ("movie", "series"):
        base = base.filter(VodTitle.type == type)
    if genre == "Outros":
        base = base.filter(VodTitle.genre.is_(None))
    elif genre:
        base = base.filter(VodTitle.genre == genre)
    if q:
        base = base.filter(VodTitle.title.ilike(f"%{q.strip()}%"))

    total = base.with_entities(func.count(VodTitle.id)).scalar() or 0
    titles = base.order_by(VodTitle.title).offset(offset).limit(limit).all()
    return {
        "count": total,
        "titles": [
            {
                "id": t.id,
                "type": t.type,
                "title": t.title,
                "poster_url": t.poster_url,
                "genre": t.genre,
                "year": t.year,
            }
            for t in titles
        ],
    }


@router.get("/vod/{title_id}")
def admin_vod_detail(
    title_id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    """Detalhe + episódios de 1 título — carregado só quando expande o card
    na tela Catálogo (não em toda a listagem)."""
    t = db.query(VodTitle).options(joinedload(VodTitle.items)).filter(VodTitle.id == title_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Título não encontrado")
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
                "stream_url": i.stream_url,
            }
            for i in sorted(t.items, key=lambda i: (i.season_number or 0, i.episode_number or 0))
        ],
    }


_MAX_CSV_BYTES = 100 * 1024 * 1024  # 100MB — alinhado com o client_max_body_size do nginx


@router.post("/vod/import-csv")
async def import_csv_upload(
    file: UploadFile,
    _admin: AdminUser = Depends(require_admin),
):
    """Mesma lógica do `python -m app.import_vod` (idempotente, nunca apaga um
    stream_url existente com uma célula em branco), só que via upload no painel
    web em vez de precisar copiar o arquivo pra VPS antes.

    Não processa o CSV na hora — dispara um job em background e devolve o
    job_id na mesma hora. Pra CSVs grandes o processamento pode levar minutos
    (cada linha é uma consulta/gravação no banco), e fazer isso dentro da
    própria requisição HTTP trava o navegador esperando com zero feedback
    (achado real em 2026-09-09) e ainda arrisca dar timeout no proxy antes de
    terminar. O painel consulta o progresso em /vod/import-csv/{job_id}/status."""
    raw = await file.read(_MAX_CSV_BYTES + 1)
    if len(raw) > _MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail=f"CSV maior que {_MAX_CSV_BYTES // (1024*1024)}MB")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Arquivo precisa ser CSV em UTF-8")

    try:
        job_id = start_import_job(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"job_id": job_id}


@router.get("/vod/import-csv/{job_id}/status")
def import_csv_status(job_id: str, _admin: AdminUser = Depends(require_admin)):
    job = get_import_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job de importação não encontrado (ou o container reiniciou)")
    return job


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


@router.get("/vod/titles-without-genre")
def list_titles_without_genre(
    type: str,  # noqa: A002 - nome claro pro cliente, mesmo sombreando o builtin
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    """Lista paginada de títulos (filme OU série, conforme `type`) sem gênero —
    alimenta a tela de classificação manual aberta ao clicar em 'sem gênero'
    nos gráficos do dashboard. Não inclui os itens/episódios: é só pra
    escolher o gênero, não pra editar o catálogo (isso já existe em
    admin.html)."""
    if type not in ("movie", "series"):
        raise HTTPException(status_code=400, detail="type deve ser 'movie' ou 'series'")

    query = db.query(VodTitle).filter(VodTitle.type == type, VodTitle.genre.is_(None))
    total = query.count()
    titles = query.order_by(VodTitle.id).offset(offset).limit(min(limit, 200)).all()
    return {
        "total": total,
        "titles": [{"id": t.id, "title": t.title, "year": t.year} for t in titles],
    }


@router.patch("/vod/titles/{title_id}/genre")
def set_title_genre(
    title_id: int,
    payload: SetGenreRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    title = db.query(VodTitle).filter(VodTitle.id == title_id).first()
    if title is None:
        raise HTTPException(status_code=404, detail="Título não encontrado")
    title.genre = payload.genre
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


# --- Canais de TV ao vivo (cadastro manual, complementa o worker automático) ---


@router.post("/channels")
def add_live_channel(
    payload: LiveChannelRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    """Se o tvg_id já existir, só adiciona esse link como mais um mirror do
    canal existente (não duplica canal) — útil tanto pra cadastrar um canal
    novo quanto pra reforçar um que o worker já trouxe com poucos mirrors."""
    channel = db.query(Channel).filter(Channel.tvg_id == payload.tvg_id).first()
    is_new_channel = channel is None

    if channel is None:
        channel = Channel(
            tvg_id=payload.tvg_id,
            name=payload.name,
            category=payload.category,
            logo_url=payload.logo_url,
            is_broadcast_tv=payload.is_broadcast_tv,
            is_active=True,
        )
        db.add(channel)
        db.flush()
    else:
        # atualiza metadados só se vierem preenchidos, nunca apaga o que já tinha
        if payload.name:
            channel.name = payload.name
        if payload.category:
            channel.category = payload.category
        if payload.logo_url:
            channel.logo_url = payload.logo_url
        channel.is_broadcast_tv = channel.is_broadcast_tv or payload.is_broadcast_tv

    existing_stream = db.query(Stream).filter(Stream.channel_id == channel.id, Stream.url == payload.stream_url).first()
    stream_added = existing_stream is None
    if existing_stream is None:
        db.add(Stream(channel_id=channel.id, url=payload.stream_url))

    db.commit()
    return {"channel_id": channel.id, "new_channel": is_new_channel, "stream_added": stream_added}


# --- Catálogo de canais (listar/editar/apagar — o POST /channels acima só
# cria/adiciona mirror; faltava ver e mexer no que já existe) ---


class ChannelUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    logo_url: Optional[str] = None
    is_broadcast_tv: Optional[bool] = None
    is_active: Optional[bool] = None


class StreamUpdateRequest(BaseModel):
    url: Optional[str] = None
    referrer: Optional[str] = None
    user_agent: Optional[str] = None
    lang_label: Optional[str] = None


@router.get("/channels/categories")
def admin_channel_categories(db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    rows = db.query(Channel.category, func.count(Channel.id)).group_by(Channel.category).all()
    named = sorted(((c, n) for c, n in rows if c), key=lambda x: -x[1])
    none_c = sum(n for c, n in rows if c is None)
    out = [{"category": c, "count": n} for c, n in named]
    if none_c:
        out.append({"category": "Outros", "count": none_c})
    return {"categories": out}


@router.get("/channels")
def admin_list_channels(
    q: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    limit = max(1, min(limit, 200))
    base = db.query(Channel)
    if category == "Outros":
        base = base.filter(Channel.category.is_(None))
    elif category:
        base = base.filter(Channel.category == category)
    if q:
        base = base.filter(Channel.name.ilike(f"%{q.strip()}%"))

    total = base.with_entities(func.count(Channel.id)).scalar() or 0
    rows = (
        base.add_columns(func.count(Stream.id).label("stream_count"))
        .outerjoin(Stream, Stream.channel_id == Channel.id)
        .group_by(Channel.id)
        .order_by(Channel.name)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "count": total,
        "channels": [
            {
                "id": c.id,
                "tvg_id": c.tvg_id,
                "name": c.name,
                "category": c.category,
                "logo_url": c.logo_url,
                "is_broadcast_tv": c.is_broadcast_tv,
                "is_active": c.is_active,
                "stream_count": stream_count,
            }
            for (c, stream_count) in rows
        ],
    }


@router.get("/channels/{channel_id}")
def admin_channel_detail(channel_id: int, db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    c = db.query(Channel).options(joinedload(Channel.streams)).filter(Channel.id == channel_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")
    return {
        "id": c.id,
        "tvg_id": c.tvg_id,
        "name": c.name,
        "category": c.category,
        "logo_url": c.logo_url,
        "is_broadcast_tv": c.is_broadcast_tv,
        "is_active": c.is_active,
        "streams": [
            {
                "id": s.id,
                "url": s.url,
                "lang_label": s.lang_label,
                "is_healthy": s.is_healthy,
                "consecutive_failures": s.consecutive_failures,
            }
            for s in c.streams
        ],
    }


@router.patch("/channels/{channel_id}")
def admin_update_channel(
    channel_id: int,
    payload: ChannelUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    c = db.query(Channel).filter(Channel.id == channel_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(c, field, value)
    db.commit()
    return {"ok": True}


@router.delete("/channels/{channel_id}")
def admin_delete_channel(channel_id: int, db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    c = db.query(Channel).filter(Channel.id == channel_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Canal não encontrado")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.patch("/streams/{stream_id}")
def admin_update_stream(
    stream_id: int,
    payload: StreamUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    s = db.query(Stream).filter(Stream.id == stream_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Link não encontrado")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(s, field, value)
    db.commit()
    return {"ok": True}


@router.delete("/streams/{stream_id}")
def admin_delete_stream(stream_id: int, db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    s = db.query(Stream).filter(Stream.id == stream_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Link não encontrado")
    db.delete(s)
    db.commit()
    return {"ok": True}


# --- Palavras-chave de gênero (classificação automática, editável) ---


@router.get("/genre-keywords")
def list_genre_keywords(db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    rows = db.query(GenreKeyword).order_by(GenreKeyword.id).all()
    genres: dict[str, list[dict]] = {}
    first_id: dict[str, int] = {}
    for row in rows:
        genres.setdefault(row.genre, []).append({"id": row.id, "keyword": row.keyword})
        first_id.setdefault(row.genre, row.id)
    ordered = sorted(genres.keys(), key=lambda g: first_id[g])
    return {"genres": [{"genre": g, "keywords": genres[g]} for g in ordered]}


@router.post("/genre-keywords")
def add_genre_keyword(
    payload: GenreKeywordRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    genre = payload.genre.strip()
    keyword = payload.keyword.strip()
    if not genre or not keyword:
        raise HTTPException(status_code=400, detail="Gênero e palavra-chave são obrigatórios")

    exists = db.query(GenreKeyword).filter(GenreKeyword.genre == genre, GenreKeyword.keyword == keyword).first()
    if exists:
        return {"id": exists.id}

    row = GenreKeyword(genre=genre, keyword=keyword)
    db.add(row)
    db.commit()
    return {"id": row.id}


@router.delete("/genre-keywords/{keyword_id}")
def delete_genre_keyword(keyword_id: int, db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    row = db.query(GenreKeyword).filter(GenreKeyword.id == keyword_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Palavra-chave não encontrada")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.delete("/genre-keywords/genre/{genre}")
def delete_genre(genre: str, db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    """Remove um gênero inteiro (todas as palavras dele)."""
    deleted = db.query(GenreKeyword).filter(GenreKeyword.genre == genre).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "removidas": deleted}


@router.post("/vod/classify-genres")
def classify_genres(_admin: AdminUser = Depends(require_admin)):
    """Dispara em background: classifica por palavra-chave todo título VOD com
    genre NULL. Nunca sobrescreve gênero já preenchido."""
    job_id = start_classify_job()
    return {"job_id": job_id}


@router.get("/vod/classify-genres/{job_id}/status")
def classify_genres_status(job_id: str, _admin: AdminUser = Depends(require_admin)):
    job = get_classify_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado (ou o container reiniciou)")
    return job


@router.get("/vod/imdb-dataset-status")
def imdb_dataset_status(_admin: AdminUser = Depends(require_admin)):
    return {"available": is_dataset_available()}


@router.post("/vod/classify-genres-imdb")
def classify_genres_imdb(_admin: AdminUser = Depends(require_admin)):
    """Dispara em background: casa cada título (filme OU série) com uma obra
    real do IMDb pelo título exato (original ou a tradução em PT-BR) e herda
    o gênero de lá. Diferente do /vod/classify-genres (palavra-chave), este
    SOBRESCREVE gênero já preenchido quando acha um match melhor — corrige
    palpites errados, não só preenche vazio."""
    if not is_dataset_available():
        raise HTTPException(
            status_code=503,
            detail="Dataset do IMDb não encontrado no servidor (title.basics.tsv.gz / title.akas.tsv.gz).",
        )
    job_id = start_imdb_classify_job()
    return {"job_id": job_id}


@router.get("/vod/classify-genres-imdb/{job_id}/status")
def classify_genres_imdb_status(job_id: str, _admin: AdminUser = Depends(require_admin)):
    job = get_imdb_classify_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado (ou o container reiniciou)")
    return job


@router.post("/vod/fetch-metadata")
def fetch_vod_metadata(_admin: AdminUser = Depends(require_admin)):
    """Dispara em background: busca o pôster (e o ano, se faltar) no endpoint
    público de autocomplete da IMDb pra todo título VOD sem pôster. Não precisa
    de conta nem de chave. Nunca sobrescreve pôster já preenchido."""
    job_id = start_tmdb_job()
    return {"job_id": job_id}


@router.get("/vod/fetch-metadata/{job_id}/status")
def fetch_vod_metadata_status(job_id: str, _admin: AdminUser = Depends(require_admin)):
    job = get_tmdb_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado (ou o container reiniciou)")
    return job


@router.post("/healthcheck")
def run_healthcheck(_admin: AdminUser = Depends(require_admin)):
    """Dispara em background: testa TODOS os streams cadastrados agora, sem
    esperar o próximo ciclo automático do worker (a cada
    HEALTHCHECK_INTERVAL_MIN). Grava o resultado nos streams e também em
    worker_runs, então some como mais uma rodada de 'healthcheck' no painel."""
    job_id = start_healthcheck_job()
    return {"job_id": job_id}


@router.get("/healthcheck/{job_id}/status")
def healthcheck_status(job_id: str, _admin: AdminUser = Depends(require_admin)):
    job = get_healthcheck_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado (ou o container reiniciou)")
    return job


@router.post("/channels/classify-categories")
def classify_channel_categories(_admin: AdminUser = Depends(require_admin)):
    """Dispara em background: classifica por palavra-chave no nome todo canal
    com category NULL/vazia. Nunca sobrescreve categoria já preenchida (nem a
    que vem do iptv-org, nem uma classificação anterior)."""
    job_id = start_classify_channels_job()
    return {"job_id": job_id}


@router.get("/channels/classify-categories/{job_id}/status")
def classify_channel_categories_status(job_id: str, _admin: AdminUser = Depends(require_admin)):
    job = get_classify_channels_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado (ou o container reiniciou)")
    return job


@router.get("/streams")
def list_streams(
    healthy: Optional[bool] = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    """Lista streams com o canal dono, pro modal de 'saudáveis vs não
    saudáveis' do dashboard. `healthy=true`/`false` filtra; sem o parâmetro
    devolve todos.

    A idade de `last_checked_at` é calculada AQUI, não no frontend: a coluna é
    um datetime "naive" (sem timezone, sempre UTC por convenção — mesmo padrão
    de WorkerRun.last_run_at em dashboard.py). Se devolvêssemos o isoformat()
    puro, o `new Date(...)` do JS no navegador interpretaria como horário
    LOCAL do usuário, não UTC, e a idade apareceria errada."""
    query = db.query(Stream).options(joinedload(Stream.channel))
    if healthy is not None:
        query = query.filter(Stream.is_healthy.is_(healthy))
    streams = query.order_by(Stream.channel_id).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "streams": [
            {
                "id": s.id,
                "url": s.url,
                "is_healthy": s.is_healthy,
                "consecutive_failures": s.consecutive_failures,
                "checked_age_seconds": (now - s.last_checked_at).total_seconds() if s.last_checked_at else None,
                "channel_id": s.channel_id,
                "channel_name": s.channel.name if s.channel else None,
                "channel_tvg_id": s.channel.tvg_id if s.channel else None,
            }
            for s in streams
        ]
    }


# ---------- tela "Sistema": processos + consumo do servidor ----------


@router.get("/system/jobs")
def system_jobs(_admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Jobs em processo (threads dentro da API) + última execução de cada job
    do worker (tabela worker_runs)."""
    prune()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    worker_runs = [
        {
            "job_name": w.job_name,
            "status": w.status,
            "summary": w.summary,
            "duration_seconds": w.duration_seconds,
            "age_seconds": (now - w.last_run_at).total_seconds() if w.last_run_at else None,
        }
        for w in db.query(WorkerRun).order_by(WorkerRun.job_name).all()
    ]
    return {"in_process": list_jobs(), "worker_runs": worker_runs}


@router.post("/system/jobs/{job_id}/cancel")
def system_cancel_job(job_id: str, _admin: AdminUser = Depends(require_admin)):
    if not request_cancel(job_id):
        raise HTTPException(status_code=404, detail="Job não encontrado (pode já ter terminado)")
    return {"ok": True, "note": "cancelamento pedido — o job para no próximo checkpoint"}


@router.get("/system/resources")
def system_resources(_admin: AdminUser = Depends(require_admin)):
    return system_snapshot()


# ---------- tela "Banco": consulta somente-leitura ----------


class SqlQuery(BaseModel):
    sql: str


@router.get("/db/tables")
def db_tables(_admin: AdminUser = Depends(require_admin)):
    return {"tables": list_tables()}


@router.get("/db/tables/{name}")
def db_table(name: str, _admin: AdminUser = Depends(require_admin)):
    try:
        return describe_table(name)
    except QueryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/db/query")
def db_query(payload: SqlQuery, _admin: AdminUser = Depends(require_admin)):
    try:
        return run_query(payload.sql)
    except QueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # erro de SQL do próprio banco
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}"[:400])


# ---------------- Usuários do site (login admin/usuário) ----------------


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"  # "admin" ou "user"
    label: Optional[str] = None  # rótulo do token, só pra role "user"


@router.get("/users")
def list_users(db: Session = Depends(get_db), _admin: AdminUser = Depends(require_admin)):
    users = db.query(AdminUser).order_by(AdminUser.created_at).all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "token": u.access_token.token if u.access_token else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    }


@router.post("/users")
def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
):
    if payload.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role precisa ser 'admin' ou 'user'")
    if not payload.username.strip() or not payload.password:
        raise HTTPException(status_code=400, detail="usuário e senha são obrigatórios")
    if db.query(AdminUser).filter(AdminUser.username == payload.username).first():
        raise HTTPException(status_code=409, detail="já existe um usuário com esse nome")

    user = AdminUser(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    if payload.role == "user":
        # cada usuário comum ganha seu próprio token de conteúdo — assim dá
        # pra revogar 1 pessoa sem afetar as outras
        access = AccessToken(token=secrets.token_urlsafe(24), label=payload.label or payload.username)
        db.add(access)
        db.flush()
        user.access_token_id = access.id
    db.add(user)
    db.commit()
    return {"ok": True, "id": user.id}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: AdminUser = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="não dá pra apagar o próprio usuário logado")
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    db.delete(user)
    db.commit()
    return {"ok": True}
