"""Consolida VodItems duplicados -- mesmo (title_id, season_number,
episode_number) registrado mais de uma vez, um por fonte de importação, em
vez de UM item com os vários links como mirrors (VodStream).

Achado em 2026-09-13 investigando por que "2 Cachorros Bobos" (e muita coisa
mais) dava "esse item não tem nenhum link cadastrado" mesmo tendo outra fonte
saudável pro mesmo episódio: o app resolve mirror por ITEM específico
(/vod/items/{id}/resolve, e o "continuar assistindo" grava o item_id exato).
Cada fonte de CSV virou um VodItem separado pro mesmo episódio, então quando
o único link daquele item específico falhava (client_failed_at), o
fallback automático nunca enxergava o link bom do "item irmão" -- é
tecnicamente outro registro, não um mirror do mesmo.

253.160 grupos duplicados, 526.817 itens afetados na 1ª medição -- processa
em chunks de títulos (não de linhas) pra manter uso de memória baixo, já que
cada grupo pode ter vários itens e preciso ver todos juntos pra decidir quem
sobrevive.

Idempotente: rodar de novo não muda nada (não sobra grupo com mais de 1 item)."""

import sys
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import StaleDataError

from .db import SessionLocal
from .models import VodItem, VodStream, WatchProgress

# health-check e outros jobs mexem em vod_streams ao mesmo tempo -- um
# UPDATE/DELETE concorrente na mesma linha entre o SELECT e o commit deste
# script gera StaleDataError (rowcount não bate) ou deadlock (OperationalError
# 1213/1205). Achado em 2026-09-13: 1º rodada em produção crashou inteira por
# isso, sem consolidar nada (savepoint por grupo evita perder o chunk todo
# por causa de 1 grupo com concorrência).
_RETRYABLE = (StaleDataError, OperationalError)

_TITLE_CHUNK = 100


def _distinct_title_ids_with_dupes(db) -> list[int]:
    # sem filtro de season_number: filme tem 1 item com season/episode NULL,
    # e o MySQL agrupa múltiplos NULL juntos no GROUP BY (diferente de um
    # WHERE) -- então isso também pega filme duplicado (2+ VodItem pro mesmo
    # título, achado em 2026-09-13 com "O Incrível Hulk" depois da
    # consolidação de VodTitle: os itens dos títulos mesclados ficam soltos,
    # um por fonte, dentro do mesmo título até isso rodar)
    rows = (
        db.query(VodItem.title_id)
        .group_by(VodItem.title_id, VodItem.season_number, VodItem.episode_number)
        .having(func.count(VodItem.id) > 1)
        .all()
    )
    return sorted({r[0] for r in rows})


def _dedupe_group(db, items: list[VodItem]) -> int:
    """`items`: todos os VodItem do mesmo (title_id, season, episode), 2+.
    Mantém o de menor id, migra os streams (e o stream_url legado) dos
    outros pra ele -- sem duplicar URL já presente --, apaga o resto.
    Devolve quantos itens foram removidos."""
    items.sort(key=lambda i: i.id)
    survivor, dupes = items[0], items[1:]

    existing_urls = {s.url for s in survivor.streams}
    if survivor.stream_url:
        existing_urls.add(survivor.stream_url)

    for dupe in dupes:
        for stream in list(dupe.streams):
            if stream.url in existing_urls:
                db.delete(stream)
            else:
                stream.item_id = survivor.id
                existing_urls.add(stream.url)
        if dupe.stream_url and dupe.stream_url not in existing_urls:
            db.add(VodStream(item_id=survivor.id, url=dupe.stream_url))
            existing_urls.add(dupe.stream_url)

    dupe_ids = [d.id for d in dupes]
    db.query(WatchProgress).filter(WatchProgress.item_id.in_(dupe_ids)).update(
        {WatchProgress.item_id: survivor.id}, synchronize_session=False
    )
    db.query(VodItem).filter(VodItem.id.in_(dupe_ids)).delete(synchronize_session=False)
    return len(dupes)


def run(db=None, progress_every=20) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    stats = {
        "titulos_processados": 0,
        "grupos_consolidados": 0,
        "itens_removidos": 0,
        "grupos_com_erro_concorrencia": 0,
    }
    try:
        title_ids = _distinct_title_ids_with_dupes(db)
        total_titles = len(title_ids)
        # commit por CONTAGEM DE GRUPOS processados, não por título -- achado
        # em 2026-09-13: um único chunk de 100 títulos pode esconder um título
        # gigante (novela com 1000+ episódios/duplicatas) e prender a
        # transação inteira acumulando dezenas de milhares de linhas
        # travadas antes do commit no fim do chunk
        _GROUP_COMMIT_EVERY = 200
        groups_since_commit = 0

        for i in range(0, total_titles, _TITLE_CHUNK):
            chunk = title_ids[i : i + _TITLE_CHUNK]
            items = (
                db.query(VodItem)
                .options(joinedload(VodItem.streams))
                .filter(VodItem.title_id.in_(chunk))
                .all()
            )
            grouped: dict[tuple, list[VodItem]] = defaultdict(list)
            for item in items:
                grouped[(item.title_id, item.season_number, item.episode_number)].append(item)

            for group in grouped.values():
                if len(group) <= 1:
                    continue
                # savepoint por grupo: um erro de concorrência (health-check
                # mexendo nas mesmas linhas ao mesmo tempo) não derruba o
                # chunk inteiro, só esse grupo -- como o script é idempotente,
                # rodar de novo resolve o que sobrou (mais simples e seguro
                # que tentar retry dentro da mesma sessão já afetada pelo erro)
                try:
                    with db.begin_nested():
                        removed = _dedupe_group(db, group)
                    stats["grupos_consolidados"] += 1
                    stats["itens_removidos"] += removed
                except _RETRYABLE:
                    stats["grupos_com_erro_concorrencia"] += 1

                groups_since_commit += 1
                if groups_since_commit >= _GROUP_COMMIT_EVERY:
                    db.commit()
                    groups_since_commit = 0
                    print(
                        f"  ... (commit parcial) {stats['itens_removidos']} itens removidos até agora",
                        file=sys.stderr,
                    )

            db.commit()
            db.expunge_all()
            groups_since_commit = 0
            stats["titulos_processados"] += len(chunk)
            if (i // _TITLE_CHUNK) % progress_every == 0:
                print(
                    f"  ... {stats['titulos_processados']}/{total_titles} títulos, "
                    f"{stats['itens_removidos']} itens removidos até agora",
                    file=sys.stderr,
                )

        return stats
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Consolidação de episódios duplicados concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
