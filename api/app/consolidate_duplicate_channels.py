"""Unifica canais duplicados -- o MESMO canal importado de várias fontes como
registros separados (achado em 2026-09-13: "AMC" aparecia 12x seguidas na
listagem; "Multishow", "Multishow HD", "Multishow 4K", "Multishow FHD H265"
eram registros separados do mesmo canal). Mantém um só e move os links dos
outros pra ele como mirrors -- o player já testa todos e fica com o primeiro
que funcionar, então qualidade/formato do link não precisa ser um canal à
parte (pedido explícito do produto em 2026-09-13: "esse 4k, fhd, h265...
tudo tem que ser o mesmo, testar todos na hora de apresentar").

Por isso a normalização REMOVE indicador de qualidade/formato/fonte do nome
antes de comparar (4K, HD, SD, FHD, UHD, H265, H264, HEVC, resoluções tipo
1080p, e marcadores de fonte alternativa como "[Alter]"/"VIP"/"Backup") --
"Multishow", "Multishow HD" e "Multishow 4K" todos viram a mesma chave
"multishow" e são unificados num canal só.

O que continua SEPARADO de propósito (não é qualidade, é conteúdo
diferente): região/idioma -- "AMC (BR)" != "AMC (BALKAN)" -- e praça de
uma rede regional -- "Globo RJ" != "Globo SP". Esses tokens não estão na
lista de qualidade, então sobrevivem à normalização e mantêm os grupos
separados. Na dúvida (token desconhecido), não remove -- juntar dois canais
que são realmente diferentes é muito pior que deixar uma duplicata na lista.
"""

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

# tokens de qualidade/formato/fonte -- removidos do FIM do nome, um por vez,
# enquanto o último token bater aqui (nunca esvazia tudo: se só sobrar
# qualidade, ela fica). "full" sozinho fica de fora de propósito (risco de
# corromper nome de canal de verdade); "full hd" por extenso ainda cai pelo
# "hd" isolado, só não remove o "full" que sobra ao lado -- lacuna aceita.
_QUALITY_TOKENS = {
    "4k", "8k", "uhd", "fhd", "hd", "sd",
    "h265", "h264", "hevc", "avc",
    "1080p", "1080i", "720p", "576p", "480p", "360p", "320p", "240p",
    "alter", "alt", "backup", "vip",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_channel_name(name: str) -> str:
    if not name:
        return ""
    n = _TRAILING_DUP_MARK.sub("", name.strip())
    n = _strip_accents(n).lower()
    # abre colchete/parêntese/underscore/hífen em espaço -- "[Alter]" e
    # "(BR)" viram tokens soltos "alter"/"br" pra avaliar cada um contra a
    # lista de qualidade (região como "br" não está na lista, sobrevive)
    n = re.sub(r"[\[\]()_\-]+", " ", n)
    tokens = n.split()
    while len(tokens) > 1 and tokens[-1] in _QUALITY_TOKENS:
        tokens.pop()
    return " ".join(tokens)


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
