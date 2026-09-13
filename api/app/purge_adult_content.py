"""Apaga PERMANENTEMENTE todo conteúdo adulto do catálogo (VOD e canais) --
título inteiro + itens/episódios + links (cascade via FK ondelete=CASCADE no
banco). Pedido explícito do produto em 2026-09-13: em vez de só esconder
"Adulto" atrás da permissão por token (ver ADULT_GENRE/ADULT_CATEGORY), o
conteúdo é removido de vez.

Identifica um título/canal como adulto por duas vias (uma pega o que a outra
deixa passar):
1. genre/category já classificado como "Adulto" (normalize_genres.py,
   recover_adult_religious.py, consolidate_adult_channels.py).
2. O próprio TÍTULO tem marcador explícito -- achado real em 2026-09-13:
   milhares de títulos vieram do CSV original com um genre qualquer (ex:
   "Ação") mas o nome já denunciava o conteúdo ("[XXX] Dad Crush ...",
   "Adulto: ...", "XXX Anal Vids ..."). Título é sinal mais confiável que o
   genre bruto pra esse caso.

Idempotente: rodar de novo não dá erro (só não acha mais nada pra apagar)."""

import re

from sqlalchemy import or_

from .db import SessionLocal
from .models import Channel, VodTitle

ADULT_GENRE = "Adulto"
ADULT_CATEGORY = "Adulto"

# marcadores exatos (LIKE) -- casos com formato fixo de prefixo/sufixo
_TITLE_LIKE_MARKERS = ["%[XXX]%", "%[Adulto]%", "Adulto:%", "Adulto -%", "XXX %", "XXX", "Brasileirinhas%"]

# palavra isolada em qualquer posição do título, PT/EN e variações de acento
# (achado em 2026-09-13: "adult"/"porn" sozinhos não bateram em nenhum título
# legítimo do catálogo -- conferido antes de aplicar)
_TITLE_WORD_MARKERS = re.compile(
    r"\b(adult|adulto|adultos|porn|porno|pornô|pornografi\w*|pornographic|hentai|erotic|erótic\w*|nsfw)\b",
    re.IGNORECASE,
)
_TITLE_PLUS18 = re.compile(r"18\s*\+|\+\s*18")


def _title_is_adult(title: str) -> bool:
    return bool(_TITLE_WORD_MARKERS.search(title) or _TITLE_PLUS18.search(title))


def _adult_vod_query(db):
    like_filters = [VodTitle.title.like(p) for p in _TITLE_LIKE_MARKERS]
    candidates = db.query(VodTitle).filter(or_(VodTitle.genre == ADULT_GENRE, *like_filters)).all()
    ids = {t.id for t in candidates}
    # marcadores por palavra/regex não dá pra fazer direto em SQL portável --
    # varre em Python só os títulos que ainda não bateram no LIKE
    rest = db.query(VodTitle.id, VodTitle.title)
    if ids:
        rest = rest.filter(VodTitle.id.notin_(ids))
    for tid, title in rest.all():
        if title and _title_is_adult(title):
            ids.add(tid)
    return db.query(VodTitle).filter(VodTitle.id.in_(ids))


def run(db=None) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    try:
        titulos_apagados = _adult_vod_query(db).delete(synchronize_session=False)
        canais_apagados = (
            db.query(Channel).filter(Channel.category == ADULT_CATEGORY).delete(synchronize_session=False)
        )
        db.commit()
        return {"titulos_vod_apagados": titulos_apagados, "canais_apagados": canais_apagados}
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Remoção de conteúdo adulto concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
