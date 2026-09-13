"""Importa títulos VOD (filmes/séries) de um CSV pra dentro das tabelas
vod_titles/vod_items. Idempotente: rodar de novo com o mesmo arquivo (ou uma
versão atualizada, com mais links preenchidos) atualiza em vez de duplicar.

Uso via linha de comando (de dentro do container da API):
    python -m app.import_vod /app/data/titulos.csv

Também pode ser usado via upload no painel web (/admin.html), que dispara um
job em background (`start_import_job`) com progresso consultável — arquivos
grandes (milhares de linhas) demoram, e sem isso a tela ficava sem nenhum
feedback (achado real em 2026-09-09).

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
  autorização/link pra aquele episódio específico — dá pra rodar a importação
  de novo depois só preenchendo essa coluna, sem redigitar o resto

Uma linha com stream_url em branco NUNCA apaga um link que já estava salvo no
banco de uma importação anterior — só atualiza quando o CSV traz um valor.
"""

import csv
import io
import sys
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import joinedload

from .db import SessionLocal
from .models import VodItem, VodTitle
from .vod_mirrors import upsert_mirror

REQUIRED_COLUMNS = {"type", "title"}
VALID_TYPES = {"movie", "series"}

# a cada quantas linhas o progresso é atualizado — não precisa ser em toda
# linha, isso só adicionaria overhead sem ganho perceptível pro usuário
_PROGRESS_EVERY = 25


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


def _import_rows(rows: list[dict], db, on_progress=None) -> dict:
    """Núcleo da importação, reutilizado pela CLI e pelo job de upload.
    `rows` já vem parseado (csv.DictReader). Não abre/fecha a sessão do banco —
    quem chama decide o ciclo de vida da `db`.

    Otimização importante: os itens (episódios/filme) de cada título são
    carregados em memória de uma vez só na primeira vez que o título é tocado
    nessa importação, em vez de 1 consulta ao banco por LINHA do CSV. Pra um
    CSV de alguns milhares de linhas, isso é a diferença entre alguns segundos
    e vários minutos (achado real testando um CSV de 30MB/15000 linhas)."""
    stats = {"titulos_novos": 0, "titulos_atualizados": 0, "itens_novos": 0, "itens_atualizados": 0, "linhas_ignoradas": []}
    title_cache: dict[tuple[str, str], VodTitle] = {}
    # title_id -> {(season, episode): VodItem} — carregado 1x por título, não por linha
    items_cache: dict[int, dict[tuple, VodItem]] = {}

    total = len(rows)
    for i, row in enumerate(rows, start=2):  # linha 1 é o cabeçalho
        if on_progress and (i % _PROGRESS_EVERY == 0):
            on_progress(i - 1, total)

        vod_type = _clean(row.get("type"))
        title_name = _clean(row.get("title"))

        if vod_type not in VALID_TYPES or not title_name:
            stats["linhas_ignoradas"].append(i)
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
            items_cache[vod_title.id] = {}
        else:
            changed = False
            for field, value in (("description", description), ("poster_url", poster_url), ("genre", genre), ("year", year)):
                if value is not None and getattr(vod_title, field) != value:
                    setattr(vod_title, field, value)
                    changed = True
            if changed:
                stats["titulos_atualizados"] += 1

        title_cache[key] = vod_title

        if vod_title.id not in items_cache:
            existing_items = (
                db.query(VodItem)
                .options(joinedload(VodItem.streams))
                .filter(VodItem.title_id == vod_title.id)
                .all()
            )
            items_cache[vod_title.id] = {(it.season_number, it.episode_number): it for it in existing_items}

        season = _clean_int(row.get("season_number"))
        episode = _clean_int(row.get("episode_number"))
        episode_title = _clean(row.get("episode_title"))
        stream_url = _clean(row.get("stream_url"))

        item_key = (season, episode)
        item = items_cache[vod_title.id].get(item_key)
        if item is None:
            item = VodItem(
                title_id=vod_title.id,
                season_number=season,
                episode_number=episode,
                episode_title=episode_title,
            )
            db.add(item)
            db.flush()  # garante item.id pro mirror abaixo
            upsert_mirror(db, item, stream_url)
            items_cache[vod_title.id][item_key] = item
            stats["itens_novos"] += 1
        else:
            changed = False
            if episode_title is not None and item.episode_title != episode_title:
                item.episode_title = episode_title
                changed = True
            # link em branco no CSV NUNCA apaga um mirror já salvo; um link
            # DIFERENTE do que já existe vira mirror adicional, não substitui
            # (o mesmo episódio às vezes tem fontes diferentes que caem em
            # horários diferentes — manter os dois aumenta a chance de sempre
            # ter um funcionando)
            if upsert_mirror(db, item, stream_url):
                changed = True
            if changed:
                stats["itens_atualizados"] += 1

    if on_progress:
        on_progress(total, total)

    return stats


def _parse_rows(csv_file) -> list[dict]:
    reader = csv.DictReader(csv_file)
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"coluna(s) obrigatória(s) faltando no CSV: {', '.join(sorted(missing))}")
    return list(reader)


def import_rows_from_text(text: str) -> dict:
    """Import síncrono direto (sem job/progresso) — usado só em testes/scripts
    pequenos. O endpoint web usa `start_import_job` (ver abaixo)."""
    rows = _parse_rows(io.StringIO(text))
    if not rows:
        return {"titulos_novos": 0, "titulos_atualizados": 0, "itens_novos": 0, "itens_atualizados": 0, "linhas_ignoradas": []}

    db = SessionLocal()
    try:
        stats = _import_rows(rows, db)
        db.commit()
        return stats
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- job em background com progresso (usado pelo upload via painel web) ---
#
# Estado em memória do próprio processo — válido porque a API roda como 1
# único processo uvicorn (sem múltiplos workers). Se isso mudar, precisa virar
# uma tabela no banco ou Redis.

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_import_job(text: str) -> str:
    """Valida o CSV (rápido, pode levantar ValueError) e dispara o processamento
    de verdade numa thread separada. Devolve um job_id pra consultar progresso
    via `get_import_job`."""
    rows = _parse_rows(io.StringIO(text))

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "total": len(rows),
            "processed": 0,
            "stats": None,
            "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

    def _on_progress(processed, total):
        with _jobs_lock:
            _jobs[job_id]["processed"] = processed
            _jobs[job_id]["total"] = total

    def _worker():
        db = SessionLocal()
        try:
            stats = _import_rows(rows, db, on_progress=_on_progress)
            db.commit()
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["stats"] = stats
                _jobs[job_id]["processed"] = _jobs[job_id]["total"]
        except Exception as e:
            db.rollback()
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True, name=f"import-csv-{job_id[:8]}").start()
    return job_id


def get_import_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None


def import_csv(path: str):
    with open(path, newline="", encoding="utf-8-sig") as f:
        try:
            rows = _parse_rows(f)
        except ValueError as e:
            print(f"ERRO: {e}")
            sys.exit(1)

    if not rows:
        print("CSV vazio, nada a importar.")
        return

    db = SessionLocal()
    try:
        stats = _import_rows(rows, db)
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
