"""Corrige um problema de dados encontrado em 2026-09-13: um CSV importado
trouxe episódios de série catalogados como `type='movie'` separados, um por
episódio, com o padrão de título "{Nome do Programa} S{temporada} E{episódio}"
— em vez de um único título `type='series'` com os episódios dentro.

Dois casos, conforme onde o nome do programa está disponível:

1. `genre` é literalmente o nome do programa (confirmado: fontes desse tipo
   usam o campo "gênero" do CSV pra AGRUPAR episódios visualmente, não como
   categoria de verdade — ex: genre="9-1-1", title="9-1-1 S01 E01"). Nesse
   caso o novo título de série fica com genre=NULL (não é gênero de verdade,
   fica pra classificação automática preencher depois).
2. `genre` é uma categoria real (Netflix, Amazon Prime, Novelas...) — extrai
   o nome do programa de dentro do próprio título (removendo o sufixo
   " Sxx Eyy") e MANTÉM o genre original na série nova/reaproveitada.

Idempotente: rodar de novo não duplica (títulos "filme" já migrados não
existem mais; séries já existentes são reaproveitadas por nome exato).
"""

import re
import sys
from collections import defaultdict

from sqlalchemy import func

from .db import SessionLocal
from .models import VodItem, VodTitle

EPISODE_RE = re.compile(r"^(.*?)\s+S(\d{1,3})\s*E(\d{1,4})$")
_DELETE_CHUNK = 2000


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def run(db=None, progress_every=5000):
    owns_session = db is None
    db = db or SessionLocal()
    stats = {
        "candidatos": 0,
        "parseados": 0,
        "programas_distintos": 0,
        "series_novas": 0,
        "series_reaproveitadas": 0,
        "itens_movidos": 0,
        "titulos_removidos": 0,
    }
    try:
        candidates = (
            db.query(VodTitle.id, VodTitle.title, VodTitle.genre)
            .filter(VodTitle.type == "movie")
            .filter(VodTitle.title.op("regexp")(r" S[0-9]+ *E[0-9]+$"))
            .all()
        )
        stats["candidatos"] = len(candidates)

        # (movie_title_id, nome_programa, temporada, episodio, genero_a_preservar)
        parsed = []
        for tid, title, genre in candidates:
            m = EPISODE_RE.match(title)
            if not m:
                continue
            prefix, season, episode = m.group(1).strip(), int(m.group(2)), int(m.group(3))
            if genre and title.startswith(genre + " S"):
                show_name = genre  # genero era na verdade o nome do programa
                keep_genre = None
            else:
                show_name = prefix
                keep_genre = genre  # genero real (ou None) -- preserva
            if not show_name:
                continue
            parsed.append((tid, show_name, season, episode, keep_genre))
        stats["parseados"] = len(parsed)

        by_show: dict[str, list[tuple[int, int, int, str | None]]] = defaultdict(list)
        for tid, show_name, season, episode, keep_genre in parsed:
            by_show[show_name].append((tid, season, episode, keep_genre))
        stats["programas_distintos"] = len(by_show)

        processed_movie_ids: list[int] = []
        done_shows = 0

        for show_name, items in by_show.items():
            series = (
                db.query(VodTitle)
                .filter(VodTitle.type == "series", VodTitle.title == show_name)
                .first()
            )
            if series is None:
                genre_for_new = next((g for _, _, _, g in items if g), None)
                series = VodTitle(type="series", title=show_name, genre=genre_for_new)
                db.add(series)
                db.flush()
                stats["series_novas"] += 1
            else:
                stats["series_reaproveitadas"] += 1

            movie_ids = [tid for tid, _, _, _ in items]
            movie_items = db.query(VodItem).filter(VodItem.title_id.in_(movie_ids)).all()
            season_by_tid = {tid: (s, e) for tid, s, e, _ in items}
            for mi in movie_items:
                season, episode = season_by_tid.get(mi.title_id, (mi.season_number, mi.episode_number))
                mi.title_id = series.id
                mi.season_number = season
                mi.episode_number = episode
                stats["itens_movidos"] += 1

            processed_movie_ids.extend(movie_ids)
            done_shows += 1
            if done_shows % progress_every == 0:
                db.commit()
                print(f"  ... {done_shows}/{len(by_show)} programas processados", file=sys.stderr)

        db.commit()

        # remove os titulos "filme" que ficaram sem nenhum item (todos os
        # processados) -- confirma "sem item" antes de apagar, por seguranca
        for chunk in _chunks(processed_movie_ids, _DELETE_CHUNK):
            ids_vazios = [
                tid
                for (tid,) in db.query(VodTitle.id)
                .filter(VodTitle.id.in_(chunk))
                .filter(~VodTitle.items.any())
                .all()
            ]
            if ids_vazios:
                db.query(VodTitle).filter(VodTitle.id.in_(ids_vazios)).delete(synchronize_session=False)
                stats["titulos_removidos"] += len(ids_vazios)
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
    print("Consolidação concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
