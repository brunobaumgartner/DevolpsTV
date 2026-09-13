"""Recupera, a partir dos CSVs originais da importação em massa (ainda
presentes em /app/data/bulk_import), os títulos cujo `genre` bruto indicava
claramente conteúdo adulto ou religioso -- essas linhas foram nuladas pela
normalização de gênero (normalize_genres.py) porque "Adulto"/"Religião" ainda
não existiam no vocabulário canônico (genre_keywords) na hora em que ela
rodou. Script de uso único (achado em 2026-09-13): melhor recuperar o sinal
real do CSV do que depender só da classificação por palavra-chave no título,
que não pega a maioria (o título raramente contém "xxx"/"religioso" etc).

Só atualiza título que hoje está com genre IS NULL -- nunca sobrescreve um
gênero já classificado (por segurança, mesmo não devendo haver conflito)."""

import csv
import glob
import sys

from sqlalchemy import tuple_

from .db import SessionLocal
from .models import VodTitle

CSV_GLOB = "/app/data/bulk_import/vod_results_v2_part*.csv"

_ADULT_RAW = {
    "Filmes | [XXX] Adultos",
    "FOR ADULTS",
    "★XXX | 24hrs",
    "[XXX] A Casa das Brasileirinhas",
}
_RELIGIOUS_RAW = {
    "Filmes | Religiosos",
    "Religião",
    "Religious",
    "OpenTV | Religioso",
    "Movies;Religious",
}


def _scan_csvs() -> dict[str, set[tuple[str, str]]]:
    """{"Adulto": {(type, title), ...}, "Religião": {...}}"""
    found: dict[str, set[tuple[str, str]]] = {"Adulto": set(), "Religião": set()}
    files = sorted(glob.glob(CSV_GLOB))
    for path in files:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                genre = (row.get("genre") or "").strip()
                title = (row.get("title") or "").strip()
                ttype = (row.get("type") or "").strip()
                if not genre or not title or not ttype:
                    continue
                if genre in _ADULT_RAW:
                    found["Adulto"].add((ttype, title))
                elif genre in _RELIGIOUS_RAW:
                    found["Religião"].add((ttype, title))
    return found


def run(db=None) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    stats = {}
    try:
        found = _scan_csvs()
        for canon, pairs in found.items():
            stats[f"encontrados_no_csv_{canon}"] = len(pairs)
            n = 0
            pairs_list = list(pairs)
            for i in range(0, len(pairs_list), 2000):
                chunk = pairs_list[i : i + 2000]
                n += (
                    db.query(VodTitle)
                    .filter(tuple_(VodTitle.type, VodTitle.title).in_(chunk))
                    .filter(VodTitle.genre.is_(None))
                    .update({VodTitle.genre: canon}, synchronize_session=False)
                )
            db.commit()
            stats[f"titulos_recuperados_{canon}"] = n
        return stats
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Recuperação de Adulto/Religião concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
