"""Health-check disparado manualmente pelo botão do dashboard — mesma lógica
do worker/app/jobs/healthcheck.py (que roda sozinho a cada
HEALTHCHECK_INTERVAL_MIN), só que sob demanda e com progresso pra tela.
Fica na API porque é aqui que o dashboard já fala; evita ter que expor um
endpoint no container do worker só pra isso.

Testa TV ao vivo (streams) e VOD (vod_items com link) juntos — filme/série
costuma usar link direto .mp4/.ts, sem manifesto .m3u8 por cima; ver a causa
raiz #3/#4 em stream_validation.py pra detecção desses formatos.

Também grava o resultado em `worker_runs` (mesma tabela que o worker usa),
então o "Jobs do worker" do dashboard reflete essa execução manual como se
fosse mais uma rodada normal do healthcheck."""

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .db import SessionLocal
from .job_registry import is_cancelled, register
from .models import Stream, VodStream, WorkerRun
from .stream_validation import stream_is_really_playable

HEALTHCHECK_TIMEOUT_SEC = 6
# cada mirror bate num servidor DIFERENTE (não é uma API central tipo TMDB) —
# não existe um rate-limit compartilhado a respeitar, então concorrência alta
# é segura. Subido de 15 pra 60 em 2026-09-13 pra dar conta de 1M+ mirrors
# num tempo razoável quando o botão "rodar tudo" é usado.
HEALTHCHECK_MAX_WORKERS = 60

# achado real em 2026-09-13: carregar TODOS os vod_streams (1,1 milhão+) como
# objetos ORM de uma vez só estourou a memória da VPS e derrubou o container
# (OOM killer) — a thread do job morreu junto, sem nem gravar erro. Processa
# em pedaços: cada pedaço é testado, gravado e DESCARTADO da memória antes do
# próximo, então o pico de memória fica limitado a um pedaço, não à tabela
# inteira, mesmo cobrindo tudo no final.
VOD_CHUNK_SIZE = 20000


def _check_stream(row_id: int, url: str, referrer: str | None, user_agent: str | None) -> tuple[int, bool]:
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
    if referrer:
        headers["Referer"] = referrer
    healthy = stream_is_really_playable(url, HEALTHCHECK_TIMEOUT_SEC, headers)
    return row_id, healthy


def _record_worker_run(status: str, summary: str, duration: float):
    db = SessionLocal()
    try:
        row = db.query(WorkerRun).filter(WorkerRun.job_name == "healthcheck").first()
        if row is None:
            row = WorkerRun(job_name="healthcheck")
            db.add(row)
        row.last_run_at = datetime.now(timezone.utc)
        row.status = status
        row.summary = summary
        row.duration_seconds = int(duration)
        db.commit()
    except Exception:
        db.rollback()
        traceback.print_exc()  # nunca deixa o tracking derrubar o job em si
    finally:
        db.close()


# --- job em background com progresso (mesmo padrão do genre_classifier.py) ---

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_healthcheck_job() -> str:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "total": 0,
            "processed": 0,
            "healthy": 0,
            "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    register("Health-check", job_id, get_healthcheck_job)

    def _check_chunk(db, rows, kind: str) -> int:
        """Testa um pedaço (lista de objetos Stream ou VodStream), grava o
        resultado e devolve quantos ficaram saudáveis. `rows` some da memória
        assim que a função retorna (só o `processed`/`healthy` acumulado no
        job persiste)."""
        if not rows:
            return 0
        tasks = (
            [(s.id, s.url, s.referrer, s.user_agent) for s in rows]
            if kind == "stream"
            else [(s.id, s.url, None, None) for s in rows]
        )
        results: dict[int, bool] = {}
        with ThreadPoolExecutor(max_workers=HEALTHCHECK_MAX_WORKERS) as pool:
            futures = {pool.submit(_check_stream, rid, url, ref, ua): rid for rid, url, ref, ua in tasks}
            for future in as_completed(futures):
                rid, healthy = future.result()
                results[rid] = healthy
                with _jobs_lock:
                    _jobs[job_id]["processed"] += 1
                    if healthy:
                        _jobs[job_id]["healthy"] += 1

        now = datetime.now(timezone.utc)
        healthy_count = 0
        for row in rows:
            healthy = results.get(row.id, False)
            row.is_healthy = healthy
            row.last_checked_at = now
            row.consecutive_failures = 0 if healthy else row.consecutive_failures + 1
            if healthy:
                healthy_count += 1
        db.commit()
        return healthy_count

    def _worker():
        start = time.monotonic()
        db = SessionLocal()
        try:
            streams = db.query(Stream).all()  # canais: só ~1200 linhas, cabe de boa
            vod_total = db.query(VodStream.id).count()
            total = len(streams) + vod_total
            with _jobs_lock:
                _jobs[job_id]["total"] = total

            if total == 0:
                with _jobs_lock:
                    _jobs[job_id]["status"] = "done"
                _record_worker_run("ok", "streams=0, vod_itens=0, saudaveis=0", time.monotonic() - start)
                return

            healthy_count = _check_chunk(db, streams, "stream")
            db.expunge_all()  # libera os objetos Stream já processados da memória

            vod_healthy_count = 0
            vod_processed = 0
            cancelled = False
            last_id = 0
            # paginação por id (keyset), não por last_checked_at: tentamos
            # ordenar pelos mais desatualizados primeiro, mas atualizar a
            # MESMA coluna que ordena o próximo SELECT é frágil (empate de
            # timestamp em updates rápidos already causou loop infinito
            # reprocessando o mesmo pedaço sem nunca avançar — achado real
            # testando local). Por id é determinístico: cada pedaço sempre
            # avança, sem depender de quando cada linha foi tocada.
            while True:
                chunk = (
                    db.query(VodStream)
                    .filter(VodStream.id > last_id)
                    .order_by(VodStream.id)
                    .limit(VOD_CHUNK_SIZE)
                    .all()
                )
                if not chunk:
                    break
                last_id = chunk[-1].id
                vod_healthy_count += _check_chunk(db, chunk, "vod")
                vod_processed += len(chunk)
                db.expunge_all()  # descarta o pedaço já gravado antes de buscar o próximo
                if is_cancelled(job_id):
                    cancelled = True
                    with _jobs_lock:
                        _jobs[job_id]["status"] = "cancelled"
                    _record_worker_run("error", "cancelado pelo admin", time.monotonic() - start)
                    break

            if cancelled:
                return

            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["healthy"] = healthy_count + vod_healthy_count
            _record_worker_run(
                "ok",
                f"streams={len(streams)}, saudaveis={healthy_count}, "
                f"vod_mirrors={vod_processed}, vod_saudaveis={vod_healthy_count} (manual)",
                time.monotonic() - start,
            )
        except Exception as e:
            db.rollback()
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)
            _record_worker_run("error", f"{type(e).__name__}: {e}"[:500], time.monotonic() - start)
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True, name=f"healthcheck-{job_id[:8]}").start()
    return job_id


def get_healthcheck_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
