"""Limpeza do ano que vem colado no FIM do nome do título ("Slender Man -
2018", "X (2021)", "X (2021) (2021)"). Achado real em 2026-09-23: ~27 mil
títulos tinham isso, o TMDB não achava capa e o catálogo mostrava o mesmo
filme duas vezes ("Filme" e "Filme - 2018").

Só tira ano de 1901 a 2099 entre parênteses ou depois de " - " e só no FIM.
Ano solto ("Wonder Woman 1984"), hífen colado ("A-2000 Feet") e ano no meio
do nome ficam como estão. Nunca devolve título vazio."""

import re

_Y = r"(19(?:0[1-9]|[1-9]\d)|20\d\d)"
_YEAR_JUNK = re.compile(rf"(?:\s*\(\s*{_Y}\s*\)|\s+[-–—]\s*{_Y})\s*$")


def split_trailing_year(title: str, year=None):
    """(título_limpo, ano). O ano já existente vence; o do nome só entra se
    `year` for vazio."""
    t = title.strip()
    found = None
    while True:
        m = _YEAR_JUNK.search(t)
        if not m or not t[: m.start()].strip():
            break
        found = found or int(m.group(1) or m.group(2))
        t = t[: m.start()].strip()
    return t, (year or found)
