"""Tira o ano do fim de `vod_titles.title` ("Slender Man - 2018" -> "Slender
Man") e preenche `year` quando estava vazio. Ver title_clean.py.

Só RENOMEIA, não mescla: o mesmo filme com e sem o sufixo passa a ter o
mesmo nome e, quando o ano bate, é o consolidate_duplicate_vod_titles.py
(rodar depois) que junta os dois. Idempotente.

Uso: python -m app.clean_year_suffix_titles [--dry-run]"""

import sys

from .db import SessionLocal
from .models import VodTitle
from .title_clean import split_trailing_year

_BATCH = 2000


def run(db=None, dry_run: bool = False) -> dict:
    owns = db is None
    db = db or SessionLocal()
    stats = {"total": 0, "renomeados": 0, "ano_preenchido": 0}
    try:
        rows = db.query(VodTitle.id, VodTitle.title, VodTitle.year).all()
        stats["total"] = len(rows)
        updates = []
        for tid, title, year in rows:
            clean, new_year = split_trailing_year(title, year)
            if clean == title:
                continue
            upd = {"id": tid, "title": clean}
            if year is None and new_year:
                upd["year"] = new_year
                stats["ano_preenchido"] += 1
            updates.append(upd)
        stats["renomeados"] = len(updates)
        if not dry_run:
            for i in range(0, len(updates), _BATCH):
                db.bulk_update_mappings(VodTitle, updates[i : i + _BATCH])
                db.commit()
        return stats
    except Exception:
        db.rollback()
        raise
    finally:
        if owns:
            db.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print("(simulação, nada gravado)" if dry else "Limpeza de ano no fim do título concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
