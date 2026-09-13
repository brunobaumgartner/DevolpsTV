"""Consolida as categorias de canal que indicam conteúdo adulto (achadas na
importação em massa: "FOR ADULTS", "XXX Adultos", "Canais | Adultos [24HR]"
etc.) num único valor "Adulto" -- o mesmo usado pelo bloqueio condicional em
routers/channels.py (ADULT_CATEGORY, só visível pro token com
sees_adult_content=True). Script de uso único, idempotente (rodar de novo com
os mesmos valores não muda nada)."""

from .db import SessionLocal
from .models import Channel

ADULT_CATEGORY = "Adulto"

_RAW_ADULT_CATEGORIES = [
    "FOR ADULTS",
    "XXX Adultos",
    "Canais | Adultos [24HR]",
    "XXX: CANAIS ADULTOS",
    "Canais | Adultos",
    "Adultos",
    "★XXX | 24hrs",
    "xxx",
    "adultos xxx",
    "videos xxx",
    "XXX: CANAIS ADULTOS LGBT",
]


def run(db=None) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    try:
        n = (
            db.query(Channel)
            .filter(Channel.category.in_(_RAW_ADULT_CATEGORIES))
            .update({Channel.category: ADULT_CATEGORY}, synchronize_session=False)
        )
        db.commit()
        return {"canais_recategorizados": n}
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Consolidação de categoria Adulto (canais) concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
