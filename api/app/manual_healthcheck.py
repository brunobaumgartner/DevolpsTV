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
HEALTHCHECK_MAX_WORKERS = 15


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

    def _worker():
        start = time.monotonic()
        db = SessionLocal()
        try:
            streams = db.query(Stream).all()
            # cap: o catálogo VOD tem centenas de milhares de mirrors; testa um
            # lote dos mais desatualizados (o botão pode ser clicado de novo)
            vod_streams = (
                db.query(VodStream)
                .order_by(VodStream.last_checked_at.is_(None).desc(), VodStream.last_checked_at.asc())
                .limit(8000)
                .all()
            )
            total = len(streams) + len(vod_streams)
            with _jobs_lock:
                _jobs[job_id]["total"] = total

            if total == 0:
                with _jobs_lock:
                    _jobs[job_id]["status"] = "done"
                _record_worker_run("ok", "streams=0, vod_itens=0, saudaveis=0", time.monotonic() - start)
                return

            tasks = [("stream", s.id, s.url, s.referrer, s.user_agent) for s in streams]
            tasks += [("vod", v.id, v.url, None, None) for v in vod_streams]
            results: dict[tuple[str, int], bool] = {}

            with ThreadPoolExecutor(max_workers=HEALTHCHECK_MAX_WORKERS) as pool:
                futures = {
                    pool.submit(_check_stream, row_id, url, referrer, user_agent): (kind, row_id)
                    for kind, row_id, url, referrer, user_agent in tasks
                }
                for future in as_completed(futures):
                    kind, row_id = futures[future]
                    _, healthy = future.result()
                    results[(kind, row_id)] = healthy
                    with _jobs_lock:
                        _jobs[job_id]["processed"] += 1
                        if healthy:
                            _jobs[job_id]["healthy"] += 1
                    if _jobs[job_id]["processed"] % 100 == 0 and is_cancelled(job_id):
                        for f in futures:
                            f.cancel()
                        with _jobs_lock:
                            _jobs[job_id]["status"] = "cancelled"
                        _record_worker_run("error", "cancelado pelo admin", time.monotonic() - start)
                        return

            now = datetime.now(timezone.utc)
            healthy_count = 0
            for stream in streams:
                healthy = results.get(("stream", stream.id), False)
                stream.is_healthy = healthy
                stream.last_checked_at = now
                stream.consecutive_failures = 0 if healthy else stream.consecutive_failures + 1
                if healthy:
                    healthy_count += 1

            vod_healthy_count = 0
            for vs in vod_streams:
                healthy = results.get(("vod", vs.id), False)
                vs.is_healthy = healthy
                vs.last_checked_at = now
                vs.consecutive_failures = 0 if healthy else vs.consecutive_failures + 1
                if healthy:
                    vod_healthy_count += 1

            db.commit()
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["healthy"] = healthy_count + vod_healthy_count
            _record_worker_run(
                "ok",
                f"streams={len(streams)}, saudaveis={healthy_count}, "
                f"vod_mirrors={len(vod_streams)}, vod_saudaveis={vod_healthy_count} (manual)",
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
