"""Normaliza `channels.category` pro vocabulário canônico já usado pelo
sistema (os slugs do iptv-org em `categories_pt.CATEGORY_LABELS` — os mesmos
que `channel_classifier.py` já sabe atribuir por palavra-chave no nome).

Mesmo problema já resolvido pro gênero de VOD (ver normalize_genres.py):
a importação em massa trouxe ~1200 valores distintos de `category`, a
maioria não é categoria de conteúdo de verdade -- é país/idioma da fonte
("BRAZIL", "TR: Turkey"), plataforma ("Pluto TV | Filmes", "DAZN LaLiga"),
nome de anime/novela usado como agrupamento ("Naruto Shippuuden (2007)"), ou
metadado técnico ("4K", "Undefined"). Regra do produto (mesma do gênero):
só o que também é categoria de conteúdo de TV de verdade vira categoria --
o resto vira NULL (deixa pra classify_channel_category, que já roda por
palavra-chave no NOME, preencher depois)."""

import re
import sys
import unicodedata

from sqlalchemy import func

from .categories_pt import CATEGORY_LABELS
from .db import SessionLocal
from .models import Channel

_CANONICAL = set(CATEGORY_LABELS) - {"outros", "xxx"}

# combinações "categoria1/categoria2" onde um token isolado não bate --
# escolhe 1 canônico em vez de tentar decidir por token
_COMPOUND_OVERRIDES = {
    "doku/news/kultur": "documentary",
    "spor/gerilim/suc": "sports",
}

# token normalizado (sem acento, minúsculo) -> slug canônico (multi-idioma:
# PT, EN, IT, TR, ES, DE observados nos dados reais)
_TOKEN_MAP = {
    "news": "news", "noticias": "news", "noticiario": "news", "jornal": "news", "haber": "news",
    "actualidad": "news", "haberler": "news",
    "sport": "sports", "sports": "sports", "esporte": "sports", "esportes": "sports",
    "deportes": "sports", "spor": "sports", "sportv": "sports",
    "music": "music", "musica": "music", "muzik": "music", "musicais": "music", "radio": "music",
    "radios": "music", "rdio": "music",
    "movies": "movies", "movie": "movies", "filme": "movies", "filmes": "movies",
    "cine": "movies", "cinema": "movies", "peliculas": "movies", "sinema": "movies", "film": "movies",
    "series": "series", "dizi": "series", "diziler": "series",
    "documentary": "documentary", "documentario": "documentary", "documentarios": "documentary",
    "documentario s": "documentary", "belgesel": "documentary", "doku": "documentary",
    "kids": "kids", "infantil": "kids", "infantis": "kids", "cocuk": "kids", "bambini": "kids",
    "ragazzi": "kids", "enfants": "kids", "kinder": "kids", "kinderkanal": "kids",
    "religious": "religious", "religioso": "religious", "religiosos": "religious", "religiao": "religious",
    "religio": "religious",
    "education": "education", "educacao": "education", "educativo": "education",
    "legislative": "legislative", "legislativo": "legislative",
    "entertainment": "entertainment", "entretenimento": "entertainment", "variedades": "entertainment",
    "business": "business", "economia": "business",
    "weather": "weather", "clima": "weather",
    "shop": "shop", "shopping": "shop",
    "travel": "travel", "viagem": "travel",
    "auto": "auto", "automoveis": "auto",
    "animation": "animation", "animasyon": "animation", "animacao": "animation", "cartoon": "animation",
    "desenho": "animation", "desenhos": "animation", "cartoni": "animation", "animati": "animation",
    "comedy": "comedy", "comedia": "comedy",
    "culture": "culture", "cultura": "culture", "kultur": "culture",
    "lifestyle": "lifestyle",
    "classic": "classic", "classici": "classic", "classicos": "classic",
    "cooking": "cooking", "culinaria": "cooking",
    "general": "general", "geral": "general",
    "outdoor": "outdoor",
    "science": "science",
    "family": "family", "familia": "family", "famiglia": "family",
    "public": "public",
    "relax": "relax",
}

_SPLIT_RE = re.compile(r"[|/;&:\s]+")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _normalize_token(s: str) -> str:
    s = _strip_accents(s).lower().strip()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def classify_category(raw: str) -> str | None:
    """Um valor bruto de `channels.category` -> slug canônico, ou None se não
    for categoria de conteúdo de verdade (país, plataforma, nome de
    programa, metadado técnico)."""
    if not raw:
        return None
    value = raw.strip()

    low = value.lower()
    for pattern, canon in _COMPOUND_OVERRIDES.items():
        if pattern in low:
            return canon

    for part in _SPLIT_RE.split(value):
        token = _normalize_token(part)
        if token in _TOKEN_MAP:
            return _TOKEN_MAP[token]
    return None


def build_mapping(db) -> dict[str, str | None]:
    raws = [c for (c,) in db.query(Channel.category).filter(Channel.category.isnot(None)).distinct().all()]
    mapping = {}
    for raw in raws:
        canon = classify_category(raw)
        if canon is not None and canon not in _CANONICAL:
            raise ValueError(f"categoria canônica {canon!r} (de {raw!r}) não existe em CATEGORY_LABELS")
        mapping[raw] = canon
    return mapping


def apply_mapping(db, mapping: dict[str, str | None], progress_every=200) -> dict:
    stats = {"canais_recategorizados": 0, "valores_processados": 0}
    items = list(mapping.items())
    for i, (raw, canon) in enumerate(items, start=1):
        if raw == canon:
            stats["valores_processados"] += 1
            continue
        n = (
            db.query(Channel)
            .filter(Channel.category == raw)
            .update({Channel.category: canon}, synchronize_session=False)
        )
        stats["canais_recategorizados"] += n
        stats["valores_processados"] += 1
        if progress_every and i % progress_every == 0:
            db.commit()
            print(f"  ... {i}/{len(items)} valores de categoria processados", file=sys.stderr)
    db.commit()
    return stats


def run(db=None):
    owns_session = db is None
    db = db or SessionLocal()
    try:
        mapping = build_mapping(db)
        return apply_mapping(db, mapping)
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Normalização de categoria de canal concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
