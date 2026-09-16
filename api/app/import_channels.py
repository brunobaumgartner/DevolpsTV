"""Importa canais de TV ao vivo de um CSV pra dentro das tabelas
channels/streams. Idempotente, mesmo espírito do import_vod.py: rodar de novo
com o mesmo arquivo (ou uma versão com mais links) atualiza em vez de
duplicar.

Formato do CSV (cabeçalho obrigatório, nessa ordem ou não — lido por nome de
coluna):

    tvg_id,name,category,logo_url,is_broadcast_tv,stream_url

- tvg_id: identificador único do canal (obrigatório) — linhas com o mesmo
  tvg_id não duplicam o canal, só adicionam o link como mais um mirror
- name: obrigatório na 1ª vez que o tvg_id aparece (cria o canal); nas linhas
  seguintes do mesmo canal pode deixar em branco
- category, logo_url: opcionais, só atualiza quando vem preenchido (nunca
  apaga um valor já salvo colocando célula vazia)
- language: opcional, idioma do canal — aceita código ou nome ("pt",
  "Português", "portuguese"). Valor não reconhecido é ignorado (ver
  app/languages.py pra lista aceita)
- is_broadcast_tv: "1"/"true"/"sim"/"yes" (qualquer outra coisa ou vazio =
  não). Uma vez marcado true pra aquele canal, fica true (mesma regra do
  formulário "Adicionar canal")
- stream_url: obrigatório — é o link em si. Uma linha por link/mirror
"""

import csv
import io
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.exc import OperationalError

from . import languages
from .channel_quality import is_junk_channel_name
from .db import SessionLocal
from .models import Channel, Stream

REQUIRED_COLUMNS = {"tvg_id", "stream_url"}
_TRUE_VALUES = {"1", "true", "sim", "yes"}
_PROGRESS_EVERY = 25

# mesma lógica do import_vod.py: deadlock (1213) e lock-timeout (1205) do
# MySQL são esperados quando outro processo (health-check, outro import) mexe
# nas mesmas tabelas ao mesmo tempo — tenta a transação inteira de novo em
# vez de perder o arquivo todo (achado real em 2026-09-13).
_RETRYABLE_ERRNOS = {1213, 1205}
_MAX_RETRIES = 4


def _run_with_deadlock_retry(rows, db, on_progress=None) -> dict:
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
            time.sleep(attempt * 2)


def _clean(value):
    if value is None:
        return None
    value = value.strip()
    return value or None


def _clean_bool(value):
    value = _clean(value)
    return bool(value) and value.lower() in _TRUE_VALUES


def _clean_language(value):
    """Idioma não reconhecido é ignorado em vez de derrubar o arquivo inteiro
    (mesma regra do import_vod)."""
    try:
        return languages.aceita(_clean(value))
    except ValueError:
        return None


_PRELOAD_CHUNK = 2000


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _preload_channels(db, rows) -> dict[str, Channel]:
    """1 (ou poucas) consulta(s) pra achar todos os canais do arquivo que já
    existem, em vez de 1 SELECT por linha nova (mesma otimização do
    import_vod.py — achado real em 2026-09-13)."""
    wanted = {_clean(r.get("tvg_id")).lower() for r in rows if _clean(r.get("tvg_id"))}
    if not wanted:
        return {}
    wanted = list(wanted)
    found: dict[str, Channel] = {}
    for chunk in _chunks(wanted, _PRELOAD_CHUNK):
        # func.lower() dos dois lados: explícito, não depende da collation do
        # banco ser case-insensitive por baixo dos panos (MySQL geralmente é,
        # mas não é garantido/portável confiar nisso implicitamente)
        for c in db.query(Channel).filter(func.lower(Channel.tvg_id).in_(chunk)).all():
            # chave normalizada (lower): a UNIQUE KEY do MySQL em tvg_id é
            # case-insensitive (collation padrão) — "ARTE.de" e "Arte.DE" são
            # o MESMO canal pro banco. Um dict Python é case-sensitive, então
            # sem normalizar a chave aqui, uma variação de maiúsculas no CSV
            # (não achada no cache) tentava INSERT de novo e batia na
            # constraint como duplicata — achado real em 2026-09-13, derrubou
            # 4 dos 9 arquivos de canal na importação em massa.
            found[c.tvg_id.lower()] = c
    return found


def _preload_streams(db, channel_cache: dict[str, Channel]) -> dict[str, dict[str, Stream]]:
    """Idem, pros streams dos canais que JÁ existiam. `channel_cache` já vem
    com chave normalizada (lower) de `_preload_channels`."""
    existing_ids = [c.id for c in channel_cache.values() if c.id is not None]
    if not existing_ids:
        return {}
    id_to_tvg = {c.id: tvg_key for tvg_key, c in channel_cache.items()}
    result: dict[str, dict[str, Stream]] = {}
    for chunk in _chunks(existing_ids, _PRELOAD_CHUNK):
        for s in db.query(Stream).filter(Stream.channel_id.in_(chunk)).all():
            result.setdefault(id_to_tvg[s.channel_id], {})[s.url] = s
    return result


def _import_rows(rows: list[dict], db, on_progress=None) -> dict:
    stats = {"canais_novos": 0, "canais_atualizados": 0, "links_novos": 0, "linhas_ignoradas": [], "linhas_lixo": []}

    channel_cache = _preload_channels(db, rows)
    streams_cache = _preload_streams(db, channel_cache)

    total = len(rows)
    for i, row in enumerate(rows, start=2):  # linha 1 é o cabeçalho
        if on_progress and (i % _PROGRESS_EVERY == 0):
            on_progress(i - 1, total)

        tvg_id = _clean(row.get("tvg_id"))
        stream_url = _clean(row.get("stream_url"))
        if not tvg_id or not stream_url:
            stats["linhas_ignoradas"].append(i)
            continue

        tvg_key = tvg_id.lower()  # normaliza pra bater com a UNIQUE KEY case-insensitive do banco
        channel = channel_cache.get(tvg_key)

        name = _clean(row.get("name"))
        category = _clean(row.get("category"))
        language = _clean_language(row.get("language"))
        logo_url = _clean(row.get("logo_url"))
        is_broadcast_tv = _clean_bool(row.get("is_broadcast_tv"))

        if channel is None:
            if not name:
                stats["linhas_ignoradas"].append(i)
                continue
            if is_junk_channel_name(name):
                # separador/aviso/decoração da playlist original, não canal de
                # verdade (ver channel_quality.py) -- nem cria a linha
                stats["linhas_lixo"].append(i)
                continue
            channel = Channel(
                tvg_id=tvg_id, name=name, category=category, language=language, logo_url=logo_url,
                is_broadcast_tv=is_broadcast_tv, is_active=True,
            )
            db.add(channel)  # sem flush: FK do stream resolvida via relacionamento abaixo
            stats["canais_novos"] += 1
            channel_cache[tvg_key] = channel
            streams_cache[tvg_key] = {}
        else:
            changed = False
            if name and channel.name != name and not is_junk_channel_name(name):
                channel.name = name
                changed = True
            if category and channel.category != category:
                channel.category = category
                changed = True
            if language and channel.language != language:
                channel.language = language
                changed = True
            if logo_url and channel.logo_url != logo_url:
                channel.logo_url = logo_url
                changed = True
            if is_broadcast_tv and not channel.is_broadcast_tv:
                channel.is_broadcast_tv = True
                changed = True
            if changed:
                stats["canais_atualizados"] += 1

        channel_streams = streams_cache.setdefault(tvg_key, {})
        if stream_url not in channel_streams:
            stream = Stream(url=stream_url)
            channel.streams.append(stream)  # FK resolvida pelo relacionamento, sem flush
            channel_streams[stream_url] = stream
            stats["links_novos"] += 1

    if on_progress:
        on_progress(total, total)

    return stats


def _parse_rows(csv_file) -> list[dict]:
    reader = csv.DictReader(csv_file)
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"coluna(s) obrigatória(s) faltando no CSV: {', '.join(sorted(missing))}")
    return list(reader)


# --- job em background com progresso (mesmo padrão do import_vod.py) ---

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_import_job(text: str) -> str:
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
        except Exception as e:
            db.rollback()
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True, name=f"import-channels-{job_id[:8]}").start()
    return job_id


def get_import_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
