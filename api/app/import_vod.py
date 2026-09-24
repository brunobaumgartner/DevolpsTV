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
- language: opcional, idioma do título — aceita código ou nome ("pt",
  "Português", "portuguese"). Valor não reconhecido é ignorado (ver
  app/languages.py pra lista aceita)
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
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import tuple_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload

from . import languages
from .title_clean import split_trailing_year
from .db import SessionLocal
from .models import VodItem, VodTitle
from .vod_mirrors import upsert_mirror

# codigos de erro do MySQL pra "outro processo brigou pela mesma linha" —
# deadlock (1213) e timeout de lock (1205). Não é bug, é esperado quando o
# health-check (ou outro import) mexe nas mesmas tabelas ao mesmo tempo —
# a prática padrão é tentar a transação inteira de novo, não desistir.
_RETRYABLE_ERRNOS = {1213, 1205}
_MAX_RETRIES = 4


def _run_with_deadlock_retry(rows, db, on_progress=None) -> dict:
    """Roda `_import_rows` + commit, tentando de novo do zero se o MySQL
    abortar a transação por deadlock/lock-timeout. Achado real em 2026-09-13:
    health-check manual + esta importação rodando ao mesmo tempo derrubaram 4
    arquivos seguidos (cada um perdendo TODO o trabalho, já que é 1 transação
    só por arquivo) — sem isso, um pico de concorrência qualquer no futuro
    (ex: vários usuários reais navegando) perderia importações inteiras."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            stats = _import_rows(rows, db, on_progress=on_progress)
            db.commit()
            return stats
        except OperationalError as e:
            db.rollback()
            errno = e.orig.args[0] if e.orig and e.orig.args else None
            if errno not in _RETRYABLE_ERRNOS or attempt == _MAX_RETRIES:
                raise
            time.sleep(attempt * 2)  # backoff: 2s, 4s, 6s...


# tamanho do lote pro IN(...) do preload em massa — evita 1 query gigante
# numa importação com dezenas de milhares de títulos distintos
_PRELOAD_CHUNK = 2000


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]

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


def _clean_language(value):
    """Normaliza pro código canônico (aceita "pt", "Português", "portuguese").
    Valor não reconhecido é ignorado em vez de derrubar o arquivo inteiro —
    uma célula torta no meio de 20 mil linhas não pode matar a importação."""
    try:
        return languages.aceita(_clean(value))
    except ValueError:
        return None


def _preload_titles(db, rows) -> dict[tuple[str, str], VodTitle]:
    """1 (ou poucas) consulta(s) pra achar TODOS os títulos do arquivo que já
    existem no banco, em vez de 1 SELECT por linha nova. Achado real: era o
    maior gargalo da importação (cada linha nova fazia SELECT + INSERT +
    flush só pra confirmar que era mesmo novo)."""
    wanted = {
        (_clean(r.get("type")), _clean(r.get("title")))
        for r in rows
        if _clean(r.get("type")) in VALID_TYPES and _clean(r.get("title"))
    }
    if not wanted:
        return {}
    wanted = list(wanted)
    found: dict[tuple[str, str], VodTitle] = {}
    for chunk in _chunks(wanted, _PRELOAD_CHUNK):
        rows_found = (
            db.query(VodTitle)
            .filter(tuple_(VodTitle.type, VodTitle.title).in_(chunk))
            .all()
        )
        for t in rows_found:
            found[(t.type, t.title)] = t
    return found


def _preload_items(db, title_cache: dict[tuple, VodTitle]) -> dict[tuple, dict[tuple, VodItem]]:
    """Idem, pros itens dos títulos que JÁ existiam (título novo não tem itens
    ainda, óbvio) — 1 consulta pra todos em vez de 1 por título."""
    existing_ids = [t.id for t in title_cache.values() if t.id is not None]
    if not existing_ids:
        return {}
    id_to_key = {t.id: key for key, t in title_cache.items()}
    result: dict[tuple, dict[tuple, VodItem]] = {}
    for chunk in _chunks(existing_ids, _PRELOAD_CHUNK):
        items = (
            db.query(VodItem)
            .options(joinedload(VodItem.streams))
            .filter(VodItem.title_id.in_(chunk))
            .all()
        )
        for it in items:
            key = id_to_key[it.title_id]
            result.setdefault(key, {})[(it.season_number, it.episode_number)] = it
    return result


def _import_rows(rows: list[dict], db, on_progress=None) -> dict:
    """Núcleo da importação, reutilizado pela CLI e pelo job de upload.
    `rows` já vem parseado (csv.DictReader). Não abre/fecha a sessão do banco —
    quem chama decide o ciclo de vida da `db`.

    Otimização importante: título e itens já existentes são carregados em
    lote ANTES do loop (`_preload_titles`/`_preload_items`), não 1 consulta
    por linha — pra um CSV com dezenas de milhares de linhas isso é a
    diferença entre minutos e segundos (achado real em 2026-09-13: ~6-7min
    por arquivo de ~15-20mil linhas, majoritariamente esperando ida-e-volta
    no banco). Título/item novo entra via `parent.filhos.append(...)` (o
    relacionamento do SQLAlchemy resolve a FK sozinho no flush final), nunca
    via `db.flush()` manual no meio do loop — cada flush explícito é uma
    viagem extra ao banco, e a única coisa que ele garantia (o ID do pai) o
    relacionamento já resolve de graça."""
    stats = {"titulos_novos": 0, "titulos_atualizados": 0, "itens_novos": 0, "itens_atualizados": 0, "linhas_ignoradas": []}

    for r in rows:
        name = _clean(r.get("title"))
        if name:
            r["title"], y = split_trailing_year(name, _clean_int(r.get("year")))
            if y and _clean_int(r.get("year")) is None:
                r["year"] = str(y)

    title_cache = _preload_titles(db, rows)
    items_cache = _preload_items(db, title_cache)

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

        description = _clean(row.get("description"))
        poster_url = _clean(row.get("poster_url"))
        genre = _clean(row.get("genre"))
        language = _clean_language(row.get("language"))
        year = _clean_int(row.get("year"))

        if vod_title is None:
            vod_title = VodTitle(
                type=vod_type,
                title=title_name,
                description=description,
                poster_url=poster_url,
                genre=genre,
                language=language,
                year=year,
            )
            db.add(vod_title)
            stats["titulos_novos"] += 1
            title_cache[key] = vod_title
            items_cache[key] = {}
        else:
            changed = False
            for field, value in (
                ("description", description),
                ("poster_url", poster_url),
                ("genre", genre),
                ("language", language),
                ("year", year),
            ):
                if value is not None and getattr(vod_title, field) != value:
                    setattr(vod_title, field, value)
                    changed = True
            if changed:
                stats["titulos_atualizados"] += 1

        season = _clean_int(row.get("season_number"))
        episode = _clean_int(row.get("episode_number"))
        episode_title = _clean(row.get("episode_title"))
        stream_url = _clean(row.get("stream_url"))

        item_key = (season, episode)
        title_items = items_cache.setdefault(key, {})
        item = title_items.get(item_key)
        if item is None:
            item = VodItem(season_number=season, episode_number=episode, episode_title=episode_title)
            vod_title.items.append(item)  # FK resolvida pelo relacionamento, sem flush
            upsert_mirror(db, item, stream_url)
            title_items[item_key] = item
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
        return _run_with_deadlock_retry(rows, db)
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
            stats = _run_with_deadlock_retry(rows, db, on_progress=_on_progress)
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
        stats = _run_with_deadlock_retry(rows, db)
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
