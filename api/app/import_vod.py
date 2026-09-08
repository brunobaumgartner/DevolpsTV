"""Importa títulos VOD (filmes/séries) de um CSV pra dentro das tabelas
vod_titles/vod_items. Idempotente: rodar de novo com o mesmo arquivo (ou uma
versão atualizada, com mais links preenchidos) atualiza em vez de duplicar.

Uso (de dentro do container da API):
    python -m app.import_vod /app/data/titulos.csv

Formato do CSV (cabeçalho obrigatório, nessa ordem ou não — é lido por nome
de coluna):

    type,title,description,poster_url,genre,year,season_number,episode_number,episode_title,stream_url

- type: "movie" ou "series" (obrigatório)
- title: nome do título (obrigatório) — linhas com o mesmo title+type viram
  episódios do MESMO título, não títulos duplicados
- description, poster_url, genre, year: opcionais, só pro título (repetir ou
  deixar em branco nas linhas de episódio, tanto faz)
- season_number, episode_number, episode_title: só fazem sentido pra "series"
  (deixe em branco pra "movie")
- stream_url: o link do stream. Pode deixar em branco se ainda não tem
  autorização/link pra aquele episódio específico — dá pra rodar o script de
  novo depois só preenchendo essa coluna, sem redigitar o resto

Uma linha com stream_url em branco NUNCA apaga um link que já estava salvo no
banco de uma importação anterior — só atualiza quando o CSV traz um valor.
"""

import csv
import sys

from .db import SessionLocal
from .models import VodItem, VodTitle

REQUIRED_COLUMNS = {"type", "title"}
VALID_TYPES = {"movie", "series"}


def _clean(value):
    """CSV sempre devolve string; normaliza célula vazia pra None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _clean_int(value):
    value = _clean(value)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def import_csv(path: str):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            print(f"ERRO: coluna(s) obrigatória(s) faltando no CSV: {', '.join(sorted(missing))}")
            sys.exit(1)

        rows = list(reader)

    if not rows:
        print("CSV vazio, nada a importar.")
        return

    db = SessionLocal()
    stats = {"titulos_novos": 0, "titulos_atualizados": 0, "itens_novos": 0, "itens_atualizados": 0, "linhas_ignoradas": 0}
    title_cache: dict[tuple[str, str], VodTitle] = {}

    try:
        for i, row in enumerate(rows, start=2):  # linha 1 é o cabeçalho
            vod_type = _clean(row.get("type"))
            title_name = _clean(row.get("title"))

            if vod_type not in VALID_TYPES or not title_name:
                print(f"  [linha {i}] ignorada: 'type' deve ser 'movie' ou 'series', e 'title' é obrigatório")
                stats["linhas_ignoradas"] += 1
                continue

            key = (vod_type, title_name)
            vod_title = title_cache.get(key)
            if vod_title is None:
                vod_title = db.query(VodTitle).filter(VodTitle.type == vod_type, VodTitle.title == title_name).first()

            description = _clean(row.get("description"))
            poster_url = _clean(row.get("poster_url"))
            genre = _clean(row.get("genre"))
            year = _clean_int(row.get("year"))

            if vod_title is None:
                vod_title = VodTitle(
                    type=vod_type, title=title_name, description=description, poster_url=poster_url, genre=genre, year=year
                )
                db.add(vod_title)
                db.flush()  # garante vod_title.id pros itens abaixo
                stats["titulos_novos"] += 1
            else:
                changed = False
                for field, value in (("description", description), ("poster_url", poster_url), ("genre", genre), ("year", year)):
                    if value is not None and getattr(vod_title, field) != value:
                        setattr(vod_title, field, value)
                        changed = True
                if changed:
                    stats["titulos_atualizados"] += 1

            title_cache[key] = vod_title

            season = _clean_int(row.get("season_number"))
            episode = _clean_int(row.get("episode_number"))
            episode_title = _clean(row.get("episode_title"))
            stream_url = _clean(row.get("stream_url"))

            item = (
                db.query(VodItem)
                .filter(VodItem.title_id == vod_title.id, VodItem.season_number == season, VodItem.episode_number == episode)
                .first()
            )
            if item is None:
                item = VodItem(
                    title_id=vod_title.id,
                    season_number=season,
                    episode_number=episode,
                    episode_title=episode_title,
                    stream_url=stream_url,
                )
                db.add(item)
                stats["itens_novos"] += 1
            else:
                changed = False
                if episode_title is not None and item.episode_title != episode_title:
                    item.episode_title = episode_title
                    changed = True
                # stream_url em branco no CSV NUNCA apaga um link já salvo
                if stream_url is not None and item.stream_url != stream_url:
                    item.stream_url = stream_url
                    changed = True
                if changed:
                    stats["itens_atualizados"] += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("Importação concluída:")
    print(f"  Títulos novos:      {stats['titulos_novos']}")
    print(f"  Títulos atualizados: {stats['titulos_atualizados']}")
    print(f"  Itens novos:        {stats['itens_novos']}")
    print(f"  Itens atualizados:  {stats['itens_atualizados']}")
    if stats["linhas_ignoradas"]:
        print(f"  Linhas ignoradas (erro de formato): {stats['linhas_ignoradas']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python -m app.import_vod <caminho_do_csv>")
        sys.exit(1)
    import_csv(sys.argv[1])
