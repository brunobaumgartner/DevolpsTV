"""Unifica canais duplicados -- o MESMO canal importado de várias fontes como
registros separados (achado em 2026-09-13: "AMC" aparecia 12x seguidas na
listagem; "BAND CAMPINAS HD", "Band Campinas HD", "BAND CAMPINAS HD¹" e
"BAND CAMPINAS HD²" eram 4 registros do mesmo canal). Mantém um só e move os
links dos outros pra ele como mirrors.

Critério DELIBERADAMENTE conservador -- só unifica quando o nome normalizado
é IDÊNTICO. O que NÃO é unificado, de propósito:
  - região/versão diferente: "AMC (BR)" != "AMC (BALKAN)"
  - qualidade diferente: "BAND CAMPINAS HD" != "BAND CAMPINAS SD"
  - praças diferentes da mesma rede: "Globo RJ" != "Globo SP"
Na dúvida, não funde -- juntar dois canais que são realmente diferentes é
muito pior que deixar uma duplicata na lista.

A normalização remove: caixa, acento, espaço repetido e o sufixo de
desambiguação que a própria fonte usa (¹ ² ³ ... e " 2"/" (2)" no fim)."""

import re
import sys
import unicodedata
from collections import defaultdict

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.exc import StaleDataError

from .db import SessionLocal
from .models import Channel, Program, Stream

_RETRYABLE = (StaleDataError, OperationalError)
_COMMIT_EVERY = 200

# sobrescritos que as fontes usam pra desambiguar nome repetido (¹²³⁴⁵⁶⁷⁸⁹)
_SUPERSCRIPTS = "¹²³⁴⁵⁶⁷⁸⁹⁰"
_TRAILING_DUP_MARK = re.compile(rf"[\s\-]*(?:[{_SUPERSCRIPTS}]+|\((?:\d{{1,2}})\))\s*$")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_channel_name(name: str) -> str:
    if not name:
        return ""
    n = _TRAILING_DUP_MARK.sub("", name.strip())
    n = _strip_accents(n).lower()
    # achado em 2026-09-13: "Multishow_HD" não batia com "MULTISHOW HD" porque
    # só espaço era tratado como separador -- underscore é usado do mesmo
    # jeito por várias fontes
    n = re.sub(r"[\s_]+", " ", n).strip()
    return n


def _merge_group(db, channels: list[Channel]) -> int:
    """Mantém o canal de menor id, move os streams (sem duplicar URL) e o EPG
    dos outros pra ele, apaga os duplicados. Devolve quantos foram removidos."""
    channels.sort(key=lambda c: c.id)
    survivor, dupes = channels[0], channels[1:]
    dupe_ids = [c.id for c in dupes]
    if not dupe_ids:
        return 0

    existing_urls = {s.url for s in survivor.streams}
    dupe_streams = db.query(Stream).filter(Stream.channel_id.in_(dupe_ids)).all()
    ids_to_delete, ids_to_move = [], []
    for stream in dupe_streams:
        if stream.url in existing_urls:
            ids_to_delete.append(stream.id)
        else:
            ids_to_move.append(stream.id)
            existing_urls.add(stream.url)

    if ids_to_delete:
        db.query(Stream).filter(Stream.id.in_(ids_to_delete)).delete(synchronize_session=False)
    if ids_to_move:
        db.query(Stream).filter(Stream.id.in_(ids_to_move)).update(
            {Stream.channel_id: survivor.id}, synchronize_session=False
        )

    # o sobrevivente herda logo/descrição/categoria que só o duplicado tinha
    for dupe in dupes:
        if not survivor.logo_url and dupe.logo_url:
            survivor.logo_url = dupe.logo_url
        if not survivor.backdrop_url and dupe.backdrop_url:
            survivor.backdrop_url = dupe.backdrop_url
        if not survivor.description and dupe.description:
            survivor.description = dupe.description
        if not survivor.category and dupe.category:
            survivor.category = dupe.category
        if dupe.is_broadcast_tv and not survivor.is_broadcast_tv:
            survivor.is_broadcast_tv = True

    # EPG do duplicado só interessa se o sobrevivente não tiver nenhum
    if not db.query(Program.id).filter(Program.channel_id == survivor.id).first():
        db.query(Program).filter(Program.channel_id.in_(dupe_ids)).update(
            {Program.channel_id: survivor.id}, synchronize_session=False
        )

    db.query(Channel).filter(Channel.id.in_(dupe_ids)).delete(synchronize_session=False)
    return len(dupes)


def run(db=None, progress_every=20) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    stats = {"grupos_unificados": 0, "canais_removidos": 0, "grupos_com_erro": 0}
    try:
        rows = db.query(Channel.id, Channel.name).filter(Channel.is_active.is_(True)).all()
        grouped: dict[str, list[int]] = defaultdict(list)
        for cid, name in rows:
            key = normalize_channel_name(name)
            if key:
                grouped[key].append(cid)

        dupe_groups = [ids for ids in grouped.values() if len(ids) > 1]
        total = len(dupe_groups)
        print(f"grupos duplicados encontrados: {total}", file=sys.stderr)

        for i, ids in enumerate(dupe_groups, start=1):
            try:
                with db.begin_nested():
                    channels = db.query(Channel).filter(Channel.id.in_(ids)).all()
                    removed = _merge_group(db, channels)
                stats["grupos_unificados"] += 1
                stats["canais_removidos"] += removed
            except _RETRYABLE:
                stats["grupos_com_erro"] += 1

            if i % _COMMIT_EVERY == 0:
                db.commit()
                if (i // _COMMIT_EVERY) % progress_every == 0:
                    print(
                        f"  ... {i}/{total} grupos, {stats['canais_removidos']} canais removidos",
                        file=sys.stderr,
                    )
        db.commit()
        return stats
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Unificação de canais duplicados concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
