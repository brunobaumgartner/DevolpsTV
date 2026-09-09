"""Classificação automática de categoria dos canais de TV ao vivo, por
palavra-chave no NOME do canal — mesmo espírito do genre_classifier.py (que
faz isso pra filme/série), só que pra `channels.category`.

Por que existe: a categoria "oficial" de cada canal vem do próprio catálogo
do iptv-org (ver worker/app/jobs/fetch_channels.py) — quando a fonte não
informa categoria pra um canal, ele fica sem (aparece como "sem categoria" no
dashboard). Isso NUNCA sobrescreve uma categoria já preenchida, seja ela vinda
do iptv-org ou de uma classificação anterior — só age em canais com
`category IS NULL` (ou string vazia).

As categorias usadas aqui seguem os slugs oficiais do iptv-org
(github.com/iptv-org/api) pra manter compatibilidade com o resto do catálogo
— não é uma taxonomia inventada.

Limite conhecido: canal cujo nome não dá nenhuma pista de categoria (ex:
"Canal 12", ou uma marca sem palavra-chave óbvia) continua sem classificar."""

import re
import threading
import unicodedata
import uuid
from datetime import datetime, timezone

from .db import SessionLocal
from .models import Channel

# ordem de prioridade: categorias mais específicas primeiro — evita que um
# canal religioso infantil (ex: "Gospel Kids") vire "kids" antes de "religious"
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "religious": [
        "gospel", "catedral", "igreja", "church", "crista", "catolic", "evangelic",
        "fe tv", "novo tempo", "record news gospel", "canção nova", "cancao nova",
        "aparecida", "santuario", "diocese", "paroquia",
    ],
    "kids": [
        "kids", "infantil", "cartoon", "disney", "nickelodeon", "nick jr", "gloob",
        "discovery kids", "baby tv", "boomerang", "desenho",
    ],
    "news": [
        "news", "noticias", "notícias", "jornal", "cnn", "journal", "info tv",
        "globonews", "band news", "record news", "sbt news",
    ],
    "sports": [
        "sport", "esporte", "esportes", "combate", "espn", "fox sports",
        "premiere", "sportv", "sporttv",
    ],
    "music": [
        "music", "musica", "música", "mtv", "hits fm", "multishow",
        " fm ", "radio",
    ],
    "movies": [
        "cine", "cinema", "movies", "movie", "filme", "filmes", "telecine",
        "megapix", "paramount",
    ],
    "series": [
        "series", "séries", "warner", "sony channel", "fx", "amc",
    ],
    "documentary": [
        "discovery", "documentary", "documentário", "history channel",
        "nat geo", "national geographic", "animal planet", "curiosity",
    ],
    "education": [
        "educa", "school", "escola", "universidade", "university", "univesp",
    ],
    "legislative": [
        "senado", "camara", "câmara", "assembleia", "congress", "parlamento",
        "tv justica", "tv justiça",
    ],
    "entertainment": [
        "entertainment", "variedades", "comédia", "comedy", "e! ",
        "warner channel",
    ],
    "business": [
        "business", "economia", "bloomberg", "cnbc", "money",
    ],
    "weather": [
        "weather", "clima", "climatempo",
    ],
    "shop": [
        "shop", "shopping", "polishop",
    ],
    "travel": [
        "travel", "viagem",
    ],
    "auto": [
        "auto", "motor", "carácter", "velocidade",
    ],
}


def _normalize(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _build_patterns() -> list[tuple[str, re.Pattern]]:
    patterns = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        escaped = sorted({re.escape(_normalize(kw)) for kw in keywords if kw.strip()}, key=len, reverse=True)
        if not escaped:
            continue
        # nem toda palavra-chave é uma "palavra" isolada (ex: " fm ") — usa \b só
        # quando o termo não já tem espaço nas bordas cuidando disso sozinho
        pattern = re.compile(r"\b(" + "|".join(escaped) + r")\b" if all(" " not in kw for kw in escaped) else "(" + "|".join(escaped) + ")")
        patterns.append((category, pattern))
    return patterns


def classify_channel_category(name: str, patterns: list[tuple[str, re.Pattern]]) -> str | None:
    normalized = " " + _normalize(name) + " "  # espaços nas bordas pra bater keywords tipo " fm "
    for category, pattern in patterns:
        if pattern.search(normalized):
            return category
    return None


# --- job em background com progresso (mesmo padrão do genre_classifier.py) ---

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_classify_channels_job() -> str:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "total": 0,
            "processed": 0,
            "classified": 0,
            "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

    def _worker():
        db = SessionLocal()
        try:
            patterns = _build_patterns()
            channels = (
                db.query(Channel)
                .filter((Channel.category.is_(None)) | (Channel.category == ""))
                .all()
            )
            with _jobs_lock:
                _jobs[job_id]["total"] = len(channels)

            classified = 0
            for i, channel in enumerate(channels, start=1):
                category = classify_channel_category(channel.name, patterns)
                if category:
                    channel.category = category
                    classified += 1
                if i % 25 == 0:
                    with _jobs_lock:
                        _jobs[job_id]["processed"] = i
                        _jobs[job_id]["classified"] = classified

            db.commit()
            with _jobs_lock:
                _jobs[job_id]["processed"] = len(channels)
                _jobs[job_id]["classified"] = classified
                _jobs[job_id]["status"] = "done"
        except Exception as e:
            db.rollback()
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True, name=f"classify-channels-{job_id[:8]}").start()
    return job_id


def get_classify_channels_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
