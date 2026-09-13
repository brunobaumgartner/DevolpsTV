"""Remove o prefixo decorativo ".:" do início de `vod_titles.title` (achado em
2026-09-13, mesma fonte contaminada que gerava canais-separador tipo
".: DEPORTES :."-- aqui não é um título-lixo inteiro, é um prefixo em cima de
um filme/série de verdade: ".:101 Dálmatas" é o MESMO filme que "101
Dálmatas").

A maioria (809 de 817 na 1ª checagem) COLIDE com um título já existente sem o
prefixo -- ou seja, é uma DUPLICATA, não só sujeira de formatação. Por isso
não dá pra só fazer UPDATE title = TRIM(title, '.:') direto (deixaria 2 cards
do mesmo filme no catálogo): quando existe o título "limpo" do MESMO type,
migra os itens/mirrors do duplicado pra ele (mesma técnica de merge do
consolidate_episodes.py) e apaga o duplicado; quando não existe, só renomeia.

Idempotente: rodar de novo não muda nada (não sobra título com o prefixo)."""

from .db import SessionLocal
from .models import VodItem, VodTitle

_PREFIX = ".:"


def _clean(title: str) -> str:
    return title[len(_PREFIX):].strip()


def run(db=None) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    stats = {"candidatos": 0, "mesclados_em_titulo_existente": 0, "renomeados": 0, "itens_movidos": 0}
    try:
        sujos = db.query(VodTitle).filter(VodTitle.title.like(f"{_PREFIX}%")).all()
        stats["candidatos"] = len(sujos)

        # 1ª passada: só migra os itens (FK) e marca quem virou merge -- NÃO
        # apaga o título ainda (mesmo padrão seguro do consolidate_episodes.py:
        # bulk delete depois, filtrado por "não tem mais itens", em vez de
        # db.delete() no objeto, que dispararia o cascade "delete-orphan" do
        # ORM em cima de itens que acabaram de ser movidos pra outro título)
        mesclados_ids = []
        for sujo in sujos:
            clean_title = _clean(sujo.title)
            if not clean_title:
                continue
            bom = (
                db.query(VodTitle)
                .filter(VodTitle.type == sujo.type, VodTitle.title == clean_title)
                .filter(VodTitle.id != sujo.id)
                .first()
            )
            if bom is not None:
                n = (
                    db.query(VodItem)
                    .filter(VodItem.title_id == sujo.id)
                    .update({VodItem.title_id: bom.id}, synchronize_session=False)
                )
                stats["itens_movidos"] += n
                mesclados_ids.append(sujo.id)
                stats["mesclados_em_titulo_existente"] += 1
            else:
                sujo.title = clean_title
                stats["renomeados"] += 1
        db.commit()

        if mesclados_ids:
            db.query(VodTitle).filter(
                VodTitle.id.in_(mesclados_ids), ~VodTitle.items.any()
            ).delete(synchronize_session=False)
            db.commit()

        return stats
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Limpeza de prefixo '.:' concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
