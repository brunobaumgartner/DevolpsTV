"""Consolida VodTitle duplicados -- mesmo filme/série importado várias vezes
(uma vez por fonte de CSV) como títulos SEPARADOS, em vez de um título único
com vários mirrors. Achado em 2026-09-13 investigando por que "O Incrível
Hulk" dava "esse item não tem nenhum link cadastrado": existiam 4 VodTitle
diferentes pra esse mesmo filme (ids 80146, 122255, 634333, 661642), cada um
com seu próprio item/link -- quando os mirrors do título que o app escolheu
esgotavam (client_failed_at), o fallback nunca via os links saudáveis dos
"títulos irmãos" porque tecnicamente eram registros diferentes.

Critério de duplicata (conservador, prefere não mesclar a mesclar errado):
mesmo `type` + título normalizado (sem acento/case, sem sufixo "- ANO"
redundante) + mesmo `year` resolvido (da coluna ou embutido no título).
Títulos em idiomas diferentes pro mesmo filme (ex: "O Incrível Hulk" vs "The
Incredible Hulk") NÃO são unificados por este critério -- ficam de fora,
tratamento mais arriscado que não vale o risco aqui.

Só migra os VodItems pro título sobrevivente (reatribui title_id) -- não
resolve duplicata de EPISÓDIO dentro do título resultante (uma série com
2 títulos duplicados, cada um com os mesmos episódios, vira 1 título com
episódios duplicados); rode consolidate_duplicate_episodes.py depois pra
resolver isso, ele já foi feito pra exatamente esse caso.

Idempotente: rodar de novo não muda nada (não sobra grupo com mais de 1
título)."""

import re
import sys
import unicodedata
from collections import defaultdict

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.exc import StaleDataError

from .db import SessionLocal
from .models import VodItem, VodTitle, WatchProgress

_YEAR_SUFFIX = re.compile(r"[\s\-–(]+((?:19|20)\d{2})\)?\s*$")
_RETRYABLE = (StaleDataError, OperationalError)
_ID_CHUNK = 2000


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _normalize(title: str, year: int | None) -> tuple[str, int | None]:
    t = _strip_accents(title).lower().strip()
    m = _YEAR_SUFFIX.search(t)
    embedded_year = int(m.group(1)) if m else None
    if m:
        t = _YEAR_SUFFIX.sub("", t).strip()
    t = re.sub(r"\s+", " ", t)
    resolved_year = year if year is not None else embedded_year
    return t, resolved_year


def _dedupe_group(db, titles: list[VodTitle]) -> int:
    """`titles`: todos os VodTitle do mesmo grupo (type, título normalizado,
    year), 2+. Mantém o de menor id, migra os VodItems dos outros pra ele,
    apaga os duplicados vazios. Devolve quantos títulos foram removidos."""
    titles.sort(key=lambda t: t.id)
    survivor, dupes = titles[0], titles[1:]
    dupe_ids = [d.id for d in dupes]

    db.query(VodItem).filter(VodItem.title_id.in_(dupe_ids)).update(
        {VodItem.title_id: survivor.id}, synchronize_session=False
    )
    db.query(WatchProgress).filter(WatchProgress.title_id.in_(dupe_ids)).update(
        {WatchProgress.title_id: survivor.id}, synchronize_session=False
    )
    # preenche campos vazios do sobrevivente com o que os duplicados tiverem
    # (poster/descrição/gênero) -- fonte diferente pode ter metadado que a
    # outra não tinha
    for dupe in dupes:
        if not survivor.poster_url and dupe.poster_url:
            survivor.poster_url = dupe.poster_url
        if not survivor.backdrop_url and dupe.backdrop_url:
            survivor.backdrop_url = dupe.backdrop_url
        if not survivor.description and dupe.description:
            survivor.description = dupe.description
        if not survivor.genre and dupe.genre:
            survivor.genre = dupe.genre
        if not survivor.year and dupe.year:
            survivor.year = dupe.year

    db.query(VodTitle).filter(VodTitle.id.in_(dupe_ids)).delete(synchronize_session=False)
    return len(dupes)


def run(db=None, progress_every=20) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    stats = {"grupos_consolidados": 0, "titulos_removidos": 0, "grupos_com_erro_concorrencia": 0}
    try:
        rows = db.query(VodTitle.id, VodTitle.type, VodTitle.title, VodTitle.year).all()
        grouped: dict[tuple, list[int]] = defaultdict(list)
        for tid, ttype, title, year in rows:
            norm_title, resolved_year = _normalize(title, year)
            grouped[(ttype, norm_title, resolved_year)].append(tid)

        dupe_groups = [ids for ids in grouped.values() if len(ids) > 1]
        total_groups = len(dupe_groups)

        for i, ids in enumerate(dupe_groups, start=1):
            try:
                with db.begin_nested():
                    titles = db.query(VodTitle).filter(VodTitle.id.in_(ids)).all()
                    removed = _dedupe_group(db, titles)
                stats["grupos_consolidados"] += 1
                stats["titulos_removidos"] += removed
            except _RETRYABLE:
                stats["grupos_com_erro_concorrencia"] += 1

            if i % _ID_CHUNK == 0:
                db.commit()
                db.expunge_all()
            if i % (progress_every * _ID_CHUNK) == 0:
                print(f"  ... {i}/{total_groups} grupos processados", file=sys.stderr)

        db.commit()
        return stats
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Consolidação de títulos VOD duplicados concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
