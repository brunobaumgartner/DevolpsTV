"""Normaliza `vod_titles.genre` pra bater com o vocabulário canônico que já
existe em `genre_keywords` (usado pela classificação automática) — não cria
tabela nova (a lista de valores distintos de `genre_keywords.genre` já É a
lista canônica).

Achado em 2026-09-13 (depois de consolidar episódios-como-filme na etapa 1):
dos 802 valores distintos hoje em `vod_titles.genre`, a maioria é lixo de
importação, não gênero de verdade — nome de plataforma (Netflix, Amazon
Prime, Disney+...), país/idioma da fonte (United States, TR-VOD, DE |...),
nome de série usado como "categoria" (The Walking Dead, Game of Thrones...),
ou metadado de catálogo (Lançamentos, 4K, Legendados). Regra explícita do
produto: só granularity que também é gênero de filme/série de verdade vira
gênero — o resto vira NULL (mesma regra pros valores antigos e novos).

Idempotente: rodar de novo não muda nada (valores já canônicos ou já NULL
ficam como estão)."""

import re
import sys
import unicodedata

from .db import SessionLocal
from .models import GenreKeyword, VodTitle

# combinações "genero1/genero2" ou "genero1 e genero2" onde queremos um só
# canônico em vez de tentar decidir token por token
_COMPOUND_OVERRIDES = {
    "fantasia e ficcao": "Fantasia",
    "komedi/dram/romantik": "Comédia",
    "aksiyon/gerilim/suc": "Ação",
    "cocuk/animasyon filmler": "Animação",
    "korku/gizem": "Terror",
    "fantastik/bilim-kurgu": "Fantasia",
}

# token normalizado (sem acento, minúsculo) -> gênero canônico
_TOKEN_MAP = {
    "acao": "Ação", "azione": "Ação", "action": "Ação", "aksiyon": "Ação",
    "animacao": "Animação", "animazione": "Animação", "animation": "Animação", "animasyon": "Animação",
    "anime": "Anime",
    "apocalipse": "Apocalipse",
    "aventura": "Aventura", "avventura": "Aventura", "adventure": "Aventura",
    "biografia": "Biografia", "biografico": "Biografia", "biography": "Biografia", "biografie": "Biografia",
    "comedia": "Comédia", "commedia": "Comédia", "comedy": "Comédia", "komedi": "Comédia",
    "crime": "Crime",
    "danca": "Dança",
    "documentario": "Documentário", "documentarios": "Documentário", "documentary": "Documentário",
    "drama": "Drama", "drammatico": "Drama", "dramma": "Drama",
    "epoca": "Época", "storia": "Época",
    "esporte": "Esporte", "sport": "Esporte", "sports": "Esporte",
    "familia": "Família", "famiglia": "Família", "family": "Família",
    "fantasia": "Fantasia", "fantasy": "Fantasia", "fantastik": "Fantasia",
    "ficcaocientifica": "Ficção científica", "fantascienza": "Ficção científica",
    "scifi": "Ficção científica", "sciencefiction": "Ficção científica", "ficcao": "Ficção científica",
    "bilimkurgu": "Ficção científica",
    "guerra": "Guerra", "war": "Guerra",
    "misterio": "Mistério", "mystery": "Mistério", "gizem": "Mistério",
    "musical": "Musical",
    "policial": "Policial",
    "romance": "Romance", "romantico": "Romance", "romantici": "Romance", "romantic": "Romance", "romantik": "Romance",
    "sobrenatural": "Sobrenatural", "supernatural": "Sobrenatural",
    "suspense": "Suspense/Thriller", "suspensethriller": "Suspense/Thriller", "thriller": "Suspense/Thriller",
    "gerilim": "Suspense/Thriller",
    "terror": "Terror", "horror": "Terror", "korku": "Terror",
    "western": "Western", "faroeste": "Western",
}

_YEAR_SUFFIX = re.compile(r"[_\s]?(19|20)\d{2}$")
_SPLIT_RE = re.compile(r"[|/;&]|(?:\bcom\b)")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _normalize_token(s: str) -> str:
    s = _strip_accents(s).lower().strip()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def classify_genre(raw: str) -> str | None:
    """Um valor bruto de `vod_titles.genre` -> gênero canônico, ou None se
    não for um gênero de verdade (plataforma, país, nome de série, metadado)."""
    if not raw:
        return None
    value = _YEAR_SUFFIX.sub("", raw.strip())

    low = value.lower().strip()
    for pattern, canon in _COMPOUND_OVERRIDES.items():
        if pattern in low:
            return canon

    for part in _SPLIT_RE.split(value):
        token = _normalize_token(part)
        if token in _TOKEN_MAP:
            return _TOKEN_MAP[token]
    return None


def build_mapping(db) -> dict[str, str | None]:
    """{genre_bruto: genero_canonico_ou_None} pra todo valor hoje presente em
    vod_titles.genre. Também confirma que todo gênero canônico usado bate com
    um valor de verdade em genre_keywords (evita erro de digitação silencioso)."""
    canonical = {g for (g,) in db.query(GenreKeyword.genre).distinct().all()}
    raws = [g for (g,) in db.query(VodTitle.genre).filter(VodTitle.genre.isnot(None)).distinct().all()]

    mapping = {}
    for raw in raws:
        canon = classify_genre(raw)
        if canon is not None and canon not in canonical:
            raise ValueError(f"gênero canônico {canon!r} (de {raw!r}) não existe em genre_keywords")
        mapping[raw] = canon
    return mapping


def apply_mapping(db, mapping: dict[str, str | None], progress_every=200) -> dict:
    stats = {"titulos_recategorizados": 0, "valores_processados": 0}
    items = list(mapping.items())
    for i, (raw, canon) in enumerate(items, start=1):
        if raw == canon:
            stats["valores_processados"] += 1
            continue
        n = (
            db.query(VodTitle)
            .filter(VodTitle.genre == raw)
            .update({VodTitle.genre: canon}, synchronize_session=False)
        )
        stats["titulos_recategorizados"] += n
        stats["valores_processados"] += 1
        if progress_every and i % progress_every == 0:
            db.commit()
            print(f"  ... {i}/{len(items)} valores de gênero processados", file=sys.stderr)
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
    print("Normalização de gênero concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
