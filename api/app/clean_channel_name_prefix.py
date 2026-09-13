"""Remove prefixo decorativo de país/fonte do NOME do canal -- ex:
"[PT] GLOBO HD" -> "GLOBO HD", "BR | Globo News-" -> "Globo News", "AR: NBA TV
HD" -> "NBA TV HD". Só limpa o TEXTO exibido; não mexe em category, tvg_id
nem streams -- cada canal continua sendo o registro que já era (mesmo
critério de "não fundir sem certeza" usado nos scripts de VOD: "Globo RJ" e
"Globo SP" são emissoras DIFERENTES, então isso não tenta unificá-las, só
limpa a decoração do nome de cada uma).

A lista de códigos (`_KNOWN_PREFIXES`) foi levantada olhando os prefixos que
de fato aparecem com alta frequência no catálogo em 2026-09-13 -- não é um
regex genérico tipo "2-4 letras maiúsculas + separador", porque isso bateria
em coisa como "CSI: Miami" (nome de série de verdade, não prefixo de país) e
removeria errado. Só remove quando o prefixo bate exatamente com um código
conhecido dessa lista.

Idempotente: rodar de novo não muda nada (nome já limpo não bate no padrão)."""

import re

from .db import SessionLocal
from .models import Channel

# códigos de país/idioma/fonte vistos com alta frequência como prefixo
# decorativo (":", "|" ou "[...]" no início do nome) -- levantado com
# SUBSTRING_INDEX + GROUP BY contra o catálogo real em 2026-09-13
_KNOWN_PREFIXES = [
    "TR", "AR", "ALB", "DE", "AF", "AL", "RUS", "FR", "RO", "IT", "BR", "UK",
    "GR", "SC", "NL", "PL", "ES", "YES", "USA", "HU", "UA", "IN", "BG", "CZ",
    "RU", "KURD", "CZE", "DK", "SLO", "CA", "ARG", "FI", "AT", "MKD", "KRD",
    "BE", "ULTHD", "NO", "KR", "PT", "MK", "AFG", "TN", "ALG", "SP", "MA",
    "AZ", "PK", "VIP", "DS", "ESP", "BD", "SWISS", "MEX", "NZ", "DOM", "IR",
    "KU", "MX", "IL", "SL", "CN", "COL", "JP", "EC", "VN", "PPV", "KOR",
    "DESP", "CL", "TH", "AU", "PH", "PY", "OSN", "PE", "EXYU", "CR", "PR",
    "CU", "CUR", "HND", "US", "AFQ", "VE", "UY", "LATINO",
]

_PREFIX_ALT = "|".join(re.escape(p) for p in sorted(_KNOWN_PREFIXES, key=len, reverse=True))
# "[CODE] resto" (colchete fechado sozinho já separa) OU "CODE: resto" /
# "CODE | resto" (precisa de ":"/"|" explícito) -- um só prefixo (a maioria
# dos casos reais tem só 1; "VIP|TR| resto" com 2 fica de fora de propósito,
# mais raro e mais arriscado de generalizar)
_PREFIX_RE = re.compile(
    rf"^\*?(?:\[(?:{_PREFIX_ALT})\]|(?:{_PREFIX_ALT})\s*[:|])\s*",
    re.IGNORECASE,
)
_TRAILING_JUNK_RE = re.compile(r"[\s\-]+$")


def clean_channel_name(name: str) -> str:
    if not name:
        return name
    cleaned = _PREFIX_RE.sub("", name.strip())
    cleaned = _TRAILING_JUNK_RE.sub("", cleaned)
    return cleaned.strip()


def run(db=None, chunk_size=5000) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    stats = {"canais_renomeados": 0}
    try:
        offset = 0
        while True:
            channels = (
                db.query(Channel)
                .order_by(Channel.id)
                .offset(offset)
                .limit(chunk_size)
                .all()
            )
            if not channels:
                break
            for channel in channels:
                new_name = clean_channel_name(channel.name)
                if new_name and new_name != channel.name:
                    channel.name = new_name
                    stats["canais_renomeados"] += 1
            db.commit()
            db.expunge_all()
            offset += chunk_size
        return stats
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Limpeza de prefixo de nome de canal concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
