"""Catálogo sob demanda (filmes/séries). A tabela é preenchida manualmente por
você (ver README.md "Adicionando títulos ao catálogo VOD") conforme for
conseguindo autorização pra cada obra — nenhum worker popula isso
automaticamente, e nenhuma fonte externa é consultada aqui."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from .. import languages
from ..db import get_db
from ..models import AccessToken, VodItem, VodStream, VodTitle, WatchProgress
from ..security import require_valid_token
from ..vod_mirrors import item_is_available, ranked_mirror_urls

router = APIRouter()


class FailureReport(BaseModel):
    url: str

# valor especial no filtro de gênero pra "títulos sem gênero"
GENRE_NONE = "Outros"

# idem pra idioma (um <select> não consegue mandar NULL na query string)
LANGUAGE_NONE = languages.NONE_LABEL

# gênero "Adulto" só aparece (chip, listagem, busca, Home, detalhe, resolve)
# pro token marcado com sees_adult_content -- todo token novo nasce sem essa
# permissão, o admin liga manualmente pro token que ele mesmo usa. Pedido
# explícito do produto em 2026-09-13.
ADULT_GENRE = "Adulto"


def _hide_adult(access: AccessToken) -> bool:
    return not (access and access.sees_adult_content)

# ordem alfabética ignorando símbolos no começo ("¡Viva!", "...E o Vento",
# "(A) Fronteira", "#Natal"): sem isso o MySQL põe todos os títulos que
# começam com pontuação antes do "A" (achado real 2026-09-23)
SORT_TITLE = func.regexp_replace(VodTitle.title, "^[^[:alnum:]]+", "")

# fração do vídeo a partir da qual consideramos "assistido até o fim"
FINISH_RATIO = 0.92


@router.get("/p/{token}/vod")
def list_vod(
    token: str,
    response: Response,
    type: Optional[str] = None,  # noqa: A002 - nome claro pro cliente
    genre: Optional[str] = None,
    language: Optional[str] = None,
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
    lista de episódios só é carregada ao abrir um título (/vod/{id}).

    Só lista título com pelo menos 1 item que tenha link (EXISTS, barato --
    usa o índice de title_id, não precisa agregar nada) -- achado em
    2026-09-13: sem esse filtro, título sem nenhum item disponível continuava
    aparecendo normalmente na listagem, só marcado como "indisponível" no
    campo `available`; ficava a critério do FRONTEND esconder, e ele não
    escondia."""
    base = db.query(VodTitle).filter(VodTitle.items.any(VodItem.stream_url.isnot(None)))
    if _hide_adult(_access):
        # genre != ADULT_GENRE sozinho excluiria também quem tem genre NULL
        # (NULL != 'Adulto' dá NULL em SQL, não TRUE) -- por isso o OR explícito
        base = base.filter(or_(VodTitle.genre != ADULT_GENRE, VodTitle.genre.is_(None)))
    if type in ("movie", "series"):
        base = base.filter(VodTitle.type == type)
    if genre == GENRE_NONE:
        base = base.filter(VodTitle.genre.is_(None))
    elif genre:
        base = base.filter(VodTitle.genre == genre)
    if language == LANGUAGE_NONE:
        base = base.filter(VodTitle.language.is_(None))
    elif language:
        base = base.filter(VodTitle.language == language)
    if q:
        base = base.filter(VodTitle.title.ilike(f"%{q.strip()}%"))

    total = base.with_entities(func.count(VodTitle.id)).scalar() or 0

    # Paginação em 2 passos (achado real em 2026-09-13): fazer o agregado
    # (outerjoin + COUNT + GROUP BY) direto na query paginada obriga o MySQL
    # a montar uma tabela temporária com TODAS as ~341mil linhas que batem no
    # filtro pra só então ordenar e pegar as 20 primeiras — mesmo só
    # devolvendo 20, o custo é o catálogo inteiro. Em vez disso: 1) acha só
    # os IDs da página atual (rápido, usa o índice type/genre+title direto,
    # sem juntar nada) 2) busca o agregado só pra essas ≤200 linhas (join
    # trivial, IN pequeno). Muito mais barato pro caso comum (poucas páginas
    # vistas por vez) mesmo com catálogo de centenas de milhares de títulos.
    page_titles = base.order_by(SORT_TITLE, VodTitle.id).offset(offset).limit(limit).all()
    page_ids = [t.id for t in page_titles]

    counts = {}
    if page_ids:
        for title_id, item_count, available_count in (
            db.query(
                VodItem.title_id,
                func.count(VodItem.id),
                func.count(VodItem.stream_url),  # count() ignora NULL -- só itens com link
            )
            .filter(VodItem.title_id.in_(page_ids))
            .group_by(VodItem.title_id)
            .all()
        ):
            counts[title_id] = (item_count, available_count)

    return {
        "count": total,
        "titles": [
            {
                "id": t.id,
                "type": t.type,
                "title": t.title,
                "poster_url": t.poster_url,
                "genre": t.genre or GENRE_NONE,
                "language": t.language,
                "year": t.year,
                "available": counts.get(t.id, (0, 0))[1] > 0,
                "episode_count": counts.get(t.id, (0, 0))[0] if t.type == "series" else None,
            }
            for t in page_titles
        ],
    }


def _genre_counts(db, type: Optional[str] = None, include_adult: bool = False):  # noqa: A002 - nome claro pro cliente
    """[(genre_ou_'Outros', count)] ordenado do maior pro menor. 'Outros' (sem
    gênero) sempre por último. Com `type`, conta só filme OU série.
    `include_adult=True` é só pro admin (ver /admin/vod/genres) -- o público
    nunca deve receber o gênero "Adulto" (ver ADULT_GENRE).

    Achado real em 2026-09-13: sem esse filtro, um gênero (ex: "Series |
    Netflix") que tenha títulos com type=movie E type=series mostrava a MESMA
    contagem (soma dos dois) tanto na tela de Filmes quanto na de Séries —
    confuso quando os números não batiam com o que a listagem filtrada por
    tipo realmente trazia."""
    q = db.query(VodTitle.genre, func.count(VodTitle.id)).filter(
        VodTitle.items.any(VodItem.stream_url.isnot(None))
    )
    if not include_adult:
        q = q.filter(or_(VodTitle.genre != ADULT_GENRE, VodTitle.genre.is_(None)))
    if type in ("movie", "series"):
        q = q.filter(VodTitle.type == type)
    rows = q.group_by(VodTitle.genre).all()
    named = sorted(((g, c) for g, c in rows if g), key=lambda x: -x[1])
    none_c = sum(c for g, c in rows if g is None)
    if none_c:
        named.append((GENRE_NONE, none_c))
    return named


@router.get("/p/{token}/vod/genres")
def list_vod_genres(
    token: str,
    response: Response,
    type: Optional[str] = None,  # noqa: A002 - nome claro pro cliente
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Gêneros do catálogo com contagem, do maior pro menor ('Outros' por
    último). Sem 'Todos'. `?type=movie|series` escopa a contagem pro tipo
    daquela tela (sem isso, os chips de gênero misturavam filme+série)."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "genres": [
            {"genre": g, "count": c}
            for g, c in _genre_counts(db, type, include_adult=not _hide_adult(_access))
        ]
    }


@router.get("/p/{token}/vod/languages")
def list_vod_languages(
    token: str,
    response: Response,
    type: Optional[str] = None,  # noqa: A002 - nome claro pro cliente
    db: Session = Depends(get_db),
    _access: AccessToken = Depends(require_valid_token),
):
    """Idiomas do catálogo com contagem — alimenta o seletor de idioma das
    telas de Filmes/Séries/Anime (mesmo formato do /channels/languages)."""
    response.headers["Cache-Control"] = "public, max-age=300"
    q = db.query(VodTitle.language, func.count(VodTitle.id)).filter(
        VodTitle.items.any(VodItem.stream_url.isnot(None))
    )
    if _hide_adult(_access):
        q = q.filter(or_(VodTitle.genre != ADULT_GENRE, VodTitle.genre.is_(None)))
    if type in ("movie", "series"):
        q = q.filter(VodTitle.type == type)
    rows = q.group_by(VodTitle.language).all()

    named = sorted(((l, c) for l, c in rows if l), key=lambda x: -x[1])
    none_c = sum(c for l, c in rows if l is None)
    out = [{"language": l, "label": languages.label(l), "count": c} for l, c in named]
    if none_c:
        out.append({"language": LANGUAGE_NONE, "label": LANGUAGE_NONE, "count": none_c})
    return {"languages": out}


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
    for genre, _count in _genre_counts(db, include_adult=not _hide_adult(_access))[:max_genres]:
        q = db.query(VodTitle).filter(VodTitle.items.any(VodItem.stream_url.isnot(None)))
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
    # gênero "Adulto" só pro token autorizado -- 404 (não 403, mesma lógica do
    # require_valid_token) pra não confirmar que o ID existe
    if t is None or (t.genre == ADULT_GENRE and _hide_adult(_access)):
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
                "available": item_is_available(i),
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
    """Devolve o melhor mirror do item pra tocar. Não testa mais ao vivo a
    partir do servidor (ver rank_mirrors() — o teste do servidor roda do IP
    da VPS e dá falso-negativo em provedores que bloqueiam datacenter, o que
    já causou 503 em links que funcionavam perfeitamente pro usuário real).
    Quem valida de verdade agora é o navegador: se a reprodução falhar de
    fato, o player chama /report-failure e tenta o próximo mirror sozinho
    (ver hls.js/Watch.jsx)."""
    item = (
        db.query(VodItem)
        .options(joinedload(VodItem.streams), joinedload(VodItem.vod_title))
        .filter(VodItem.id == item_id)
        .first()
    )
    # gênero "Adulto" só pro token autorizado -- mesma regra do vod_detail
    if item is not None and item.vod_title.genre == ADULT_GENRE and _hide_adult(_access):
        item = None
    if item is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")

    candidates = ranked_mirror_urls(item)
    if not candidates:
        raise HTTPException(status_code=503, detail="Esse item não tem nenhum link cadastrado.")
    return {"item_id": item_id, "url": candidates[0], "checked_mirrors": len(candidates)}


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
    eps = [e for e in eps if item_is_available(e)]
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
