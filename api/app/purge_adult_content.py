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

from sqlalchemy import or_

from .db import SessionLocal
from .models import Channel, VodTitle

ADULT_GENRE = "Adulto"
ADULT_CATEGORY = "Adulto"

_TITLE_MARKERS = ["%[XXX]%", "%[Adulto]%", "Adulto:%", "Adulto -%", "XXX %", "XXX"]


def _adult_vod_query(db):
    return db.query(VodTitle).filter(
        or_(VodTitle.genre == ADULT_GENRE, *[VodTitle.title.like(p) for p in _TITLE_MARKERS])
    )


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
