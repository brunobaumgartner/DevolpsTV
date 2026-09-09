"""Registra a última execução de cada job (fetch_channels/healthcheck/fetch_epg)
numa linha em `worker_runs` — dá visibilidade pro dashboard sem precisar ler
log do container."""

import functools
import time
import traceback
from datetime import datetime, timezone

from .db import SessionLocal
from .models import WorkerRun


def track_job(job_name: str):
    """Decorator: roda a função normalmente, mas grava status/duração/erro no
    banco antes de devolver (ou relançar) a exceção."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = func(*args, **kwargs)
                _record(job_name, "ok", _summarize(result), time.monotonic() - start)
                return result
            except Exception as e:
                _record(job_name, "error", f"{type(e).__name__}: {e}"[:500], time.monotonic() - start)
                traceback.print_exc()
                raise

        return wrapper

    return decorator


def _summarize(result) -> str:
    if result is None:
        return ""
    if isinstance(result, dict):
        return ", ".join(f"{k}={v}" for k, v in result.items())[:500]
    return str(result)[:500]


def _record(job_name: str, status: str, summary: str, duration: float):
    db = SessionLocal()
    try:
        row = db.query(WorkerRun).filter(WorkerRun.job_name == job_name).first()
        now = datetime.now(timezone.utc)
        if row is None:
            row = WorkerRun(job_name=job_name)
            db.add(row)
        row.last_run_at = now
        row.status = status
        row.summary = summary
        row.duration_seconds = int(duration)
        db.commit()
    except Exception:
        db.rollback()
        # nunca deixa o tracking derrubar o job em si
        traceback.print_exc()
    finally:
        db.close()
