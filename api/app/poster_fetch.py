"""Enriquece o catálogo VOD (pôster + sinopse + ano + gênero) usando a API do
TMDB (themoviedb.org). Uma busca por título já devolve tudo: `poster_path`,
`overview` (pt-BR), data de estreia e `genre_ids`.

Precisa da chave grátis v3 em TMDB_API_KEY (.env). Sem ela o job devolve erro
claro e não faz nada.

Fallback: quando o TMDB acha o título mas não tem pôster, tenta o pôster no
endpoint público de autocomplete da IMDb (sem chave).

Nunca sobrescreve campo já preenchido — só preenche o que está vazio.
Mesmo padrão de job em background + progresso do imdb_classifier.py.
"""

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from .config import TMDB_API_KEY
from .db import SessionLocal
from .job_registry import is_cancelled, register
from .models import VodTitle

_TMDB_SEARCH = "https://api.themoviedb.org/3/search/{kind}"
_TMDB_IMG = "https://image.tmdb.org/t/p/w342{path}"
_TMDB_BACKDROP = "https://image.tmdb.org/t/p/w780{path}"
_IMDB_SUGGEST = "https://v2.sg.media-imdb.com/suggestion/{key}/{query}.json"
_TIMEOUT = 12
_WORKERS = 8  # TMDB aguenta ~50 req/s; 8 é folgado
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# --- mapa de gênero: id do TMDB -> nosso rótulo (mesma lista/prioridade do
# imdb_index_builder). ids de filme e série; quando batem, batem no mesmo. ---
_TMDB_GENRE = {
    28: "Ação", 12: "Aventura", 16: "Animação", 35: "Comédia", 80: "Crime",
    99: "Documentário", 18: "Drama", 10751: "Família", 14: "Fantasia",
    36: "Época", 27: "Terror", 10402: "Musical", 9648: "Mistério",
    10749: "Romance", 878: "Ficção científica", 53: "Suspense/Thriller",
    10752: "Guerra", 37: "Western",
    # séries
    10759: "Ação", 10762: "Família", 10763: "Documentário", 10765: "Ficção científica",
    10766: "Drama", 10768: "Guerra",
}
# quando um título tem vários gêneros, o mais específico vence (topo desta lista)
_PRIORITY = [
    "Documentário", "Biografia", "Animação", "Musical", "Western", "Guerra",
    "Época", "Ficção científica", "Fantasia", "Terror", "Suspense/Thriller",
    "Crime", "Mistério", "Esporte", "Família", "Romance", "Comédia",
    "Aventura", "Ação", "Drama",
]


def is_configured() -> bool:
    return bool(TMDB_API_KEY)


_tl = threading.local()


def _session() -> requests.Session:
    s = getattr(_tl, "s", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = _UA
        _tl.s = s
    return s


def _pick_genre(genre_ids, is_anime: bool) -> str | None:
    ours = {_TMDB_GENRE[g] for g in (genre_ids or []) if g in _TMDB_GENRE}
    if not ours:
        return None
    for g in _PRIORITY:
        if g in ours:
            if g == "Animação" and is_anime:
                return "Anime"
            return g
    return None


def _tmdb_get(kind: str, params: dict):
    for attempt in range(4):
        try:
            r = _session().get(_TMDB_SEARCH.format(kind=kind), params=params, timeout=_TIMEOUT)
        except requests.RequestException:
            time.sleep(1 + attempt)
            continue
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)) + 0.5)
            continue
        if r.status_code != 200:
            return None
        try:
            return r.json().get("results") or []
        except ValueError:
            return None
    return None


def _search_tmdb(title: str, year, is_series: bool):
    kind = "tv" if is_series else "movie"
    base = {"api_key": TMDB_API_KEY, "language": "pt-BR", "query": title.strip(), "include_adult": "false"}
    if year:
        base["first_air_date_year" if is_series else "primary_release_year"] = year

    results = _tmdb_get(kind, base)
    if not results and year:
        base.pop("first_air_date_year", None)
        base.pop("primary_release_year", None)
        results = _tmdb_get(kind, base)
    if not results:
        return None

    best = results[0]
    if year:
        for cand in results:
            d = cand.get("release_date") or cand.get("first_air_date") or ""
            if d[:4] == str(year):
                best = cand
                break

    date = best.get("release_date") or best.get("first_air_date") or ""
    is_anime = (best.get("original_language") == "ja") or ("JP" in (best.get("origin_country") or []))
    vote = best.get("vote_average")
    return {
        "poster_url": _TMDB_IMG.format(path=best["poster_path"]) if best.get("poster_path") else None,
        "backdrop_url": _TMDB_BACKDROP.format(path=best["backdrop_path"]) if best.get("backdrop_path") else None,
        "overview": (best.get("overview") or "").strip() or None,
        "year": int(date[:4]) if date[:4].isdigit() else None,
        "genre": _pick_genre(best.get("genre_ids"), is_anime),
        "rating": round(float(vote), 1) if vote else None,
        "tmdb_id": best.get("id"),
    }


def _imdb_poster(title: str):
    """Só o pôster, como fallback quando o TMDB não tem imagem."""
    q = title.strip()
    if not q:
        return None
    key = next((c.lower() for c in q if c.isalnum()), "x")
    try:
        r = _session().get(_IMDB_SUGGEST.format(key=key, query=quote(q)), timeout=_TIMEOUT)
        body = r.text.lstrip()
        if r.status_code != 200 or not body.startswith("{"):
            return None
        for d in json.loads(body).get("d") or []:
            img = d.get("i", {}).get("imageUrl")
            if str(d.get("id", "")).startswith("tt") and img:
                return img
    except (requests.RequestException, ValueError):
        return None
    return None


# limita o ritmo de chamadas ao TMDB (evita rate-limit/sobrecarga num
# catálogo com dezenas de milhares de títulos faltando dado) — processa um
# lote, espera completar a janela de 20min desde o início dele, processa o
# próximo. O job continua em 1 clique só: a barra de progresso do dashboard
# vai avançando aos poucos (pode levar horas num backlog grande).
_TMDB_BATCH_SIZE = 900
_TMDB_BATCH_WINDOW_SEC = 20 * 60
_CANCEL_POLL_SEC = 5  # granularidade da checagem de cancelamento durante a espera

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _set(job_id, **kw):
    with _lock:
        _jobs[job_id].update(kw)


def start_tmdb_job() -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "status": "running", "phase": "buscando no TMDB",
            "processed": 0, "total": 0, "matched": 0, "genres": 0, "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    register("Buscar capas + dados (TMDB)", job_id, get_tmdb_job)

    def _worker():
        db = SessionLocal()
        try:
            if not is_configured():
                raise RuntimeError("TMDB_API_KEY não configurada no .env do servidor.")

            # tudo que ainda falta pôster OU sinopse OU gênero
            rows = list(
                db.query(
                    VodTitle.id, VodTitle.title, VodTitle.year, VodTitle.type,
                    VodTitle.poster_url.isnot(None), VodTitle.description.isnot(None),
                    VodTitle.genre.isnot(None), VodTitle.backdrop_url.isnot(None),
                    VodTitle.rating.isnot(None),
                ).filter(
                    VodTitle.poster_url.is_(None)
                    | VodTitle.description.is_(None)
                    | VodTitle.genre.is_(None)
                    | VodTitle.backdrop_url.is_(None)
                    | VodTitle.rating.is_(None)
                    | VodTitle.tmdb_id.is_(None)
                )
            )
            _set(job_id, total=len(rows))

            def task(row):
                tid, title, year, typ = row[0], row[1], row[2], row[3]
                res = _search_tmdb(title, year, typ == "series")
                poster = res["poster_url"] if res else None
                if not row[4] and res and not poster:
                    poster = _imdb_poster(title)  # fallback só do pôster
                return row, res, poster

            matched = genres = done = 0
            cancelled = False
            batches = [rows[i : i + _TMDB_BATCH_SIZE] for i in range(0, len(rows), _TMDB_BATCH_SIZE)]

            for batch_idx, batch in enumerate(batches):
                batch_start = time.monotonic()
                _set(job_id, phase=f"lote {batch_idx + 1}/{len(batches)} — buscando no TMDB")

                with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
                    futs = [pool.submit(task, r) for r in batch]
                    for fut in as_completed(futs):
                        row, res, poster = fut.result()
                        tid, _t, year, _typ, has_poster, has_desc, has_genre, has_bd, has_rating = row
                        done += 1
                        vals = {}
                        if poster and not has_poster:
                            vals["poster_url"] = poster
                            matched += 1
                        if res:
                            if res["overview"] and not has_desc:
                                vals["description"] = res["overview"]
                            if res["year"] and not year:
                                vals["year"] = res["year"]
                            if res["genre"] and not has_genre:
                                vals["genre"] = res["genre"]
                                genres += 1
                            if res["backdrop_url"] and not has_bd:
                                vals["backdrop_url"] = res["backdrop_url"]
                            if res["rating"] and not has_rating:
                                vals["rating"] = res["rating"]
                            if res["tmdb_id"]:
                                vals["tmdb_id"] = res["tmdb_id"]
                        if vals:
                            db.query(VodTitle).filter(VodTitle.id == tid).update(vals, synchronize_session=False)
                        if done % 50 == 0:
                            db.commit()
                            _set(job_id, processed=done, matched=matched, genres=genres)
                        if is_cancelled(job_id):
                            cancelled = True
                            for f in futs:
                                f.cancel()
                            break

                db.commit()
                _set(job_id, processed=done, matched=matched, genres=genres)
                if cancelled:
                    break

                is_last_batch = batch_idx == len(batches) - 1
                if not is_last_batch:
                    wait = max(0.0, _TMDB_BATCH_WINDOW_SEC - (time.monotonic() - batch_start))
                    _set(job_id, phase=f"lote {batch_idx + 1}/{len(batches)} feito — "
                                        f"aguardando {int(wait / 60)}min pro próximo (limite de {_TMDB_BATCH_SIZE}/20min)")
                    slept = 0.0
                    while slept < wait:
                        if is_cancelled(job_id):
                            cancelled = True
                            break
                        time.sleep(min(_CANCEL_POLL_SEC, wait - slept))
                        slept += _CANCEL_POLL_SEC
                if cancelled:
                    break

            if cancelled:
                _set(job_id, status="cancelled", phase=f"cancelado em {done} de {len(rows)}",
                     processed=done, matched=matched, genres=genres)
            else:
                _set(job_id, status="done", phase="concluído", processed=len(rows),
                     matched=matched, genres=genres)
        except Exception as e:
            db.rollback()
            _set(job_id, status="error", error=str(e))
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True, name=f"tmdb-{job_id[:8]}").start()
    return job_id


def get_tmdb_job(job_id: str):
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None
