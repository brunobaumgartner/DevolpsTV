"""Detecta nomes de canal que são, na verdade, lixo vindo da playlist M3U
original — separador de seção, aviso da fonte, ou decoração — não um canal de
verdade. Achado em 2026-09-13: entradas como '----- (AL) ALBANIA CHANNEL-----',
'-- Ultima actualizacion: 18-02-2016 --', '_Lion9-', '[COLOR red]...[/COLOR]'
foram importadas como "canais" e apareciam na listagem sem nenhum conteúdo de
verdade por trás. As mesmas regras usadas pra desativar as 116 entradas já
existentes no banco (ver histórico) — reaproveitadas aqui pra barrar na
importação, em vez de precisar de faxina manual de novo a cada CSV novo."""

import re

# pega "-----X-----" / "K----J" (3+ traços em qualquer lugar) e qualquer nome
# que COMECE com "--" (regra simplificada em 2026-09-13: nenhum canal de
# verdade começa com traço duplo -- "--Adultos--", "--Cable--", "--Honduras--"
# e variantes sem fechamento tipo "--Alguma coisa" caem todas aqui)
_DASH_SEPARATOR = re.compile(r"-{3,}")
_UPDATE_NOTICE = re.compile(r"actualizacion|atualiza|tildes omitidas|limitacion del sistema", re.IGNORECASE)
_BBCODE = re.compile(r"^\s*\[color", re.IGNORECASE)


def is_junk_channel_name(name: str | None) -> bool:
    if not name:
        return False
    stripped = name.strip()
    if stripped.startswith("--") or stripped.startswith(".:"):
        return True
    if _DASH_SEPARATOR.search(stripped):
        return True
    if _UPDATE_NOTICE.search(stripped):
        return True
    if _BBCODE.search(stripped):
        return True
    # todo nome decorativo visto até agora começando com "_" era lixo
    # (_Lion9-, _一dei_, _白1_..., _isly) -- nenhum canal de verdade usa esse
    # padrão, então tratar qualquer "_..." como lixo é seguro
    if stripped.startswith("_"):
        return True
    if "祝" in stripped:
        return True
    return False
