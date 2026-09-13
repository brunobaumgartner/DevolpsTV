"""Detecta nomes de canal que são, na verdade, lixo vindo da playlist M3U
original — separador de seção, aviso da fonte, ou decoração — não um canal de
verdade. Achado em 2026-09-13: entradas como '----- (AL) ALBANIA CHANNEL-----',
'-- Ultima actualizacion: 18-02-2016 --', '_Lion9-', '[COLOR red]...[/COLOR]'
foram importadas como "canais" e apareciam na listagem sem nenhum conteúdo de
verdade por trás. As mesmas regras usadas pra desativar as 116 entradas já
existentes no banco (ver histórico) — reaproveitadas aqui pra barrar na
importação, em vez de precisar de faxina manual de novo a cada CSV novo."""

import re

_DASH_SEPARATOR = re.compile(r"-{3,}")
_UPDATE_NOTICE = re.compile(r"actualizacion|atualiza", re.IGNORECASE)
_BBCODE = re.compile(r"^\s*\[color", re.IGNORECASE)
_UNDERSCORE_WRAPPED = re.compile(r"^_[^_]*_$")


def is_junk_channel_name(name: str | None) -> bool:
    if not name:
        return False
    stripped = name.strip()
    if _DASH_SEPARATOR.search(stripped):
        return True
    if _UPDATE_NOTICE.search(stripped):
        return True
    if _BBCODE.search(stripped):
        return True
    if stripped.startswith("_") and (stripped.endswith("-") or _UNDERSCORE_WRAPPED.match(stripped)):
        return True
    if "祝" in stripped:
        return True
    return False
