import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from ..config import HEALTHCHECK_MAX_WORKERS, HEALTHCHECK_TIMEOUT_SEC
from ..db import SessionLocal
from ..job_tracking import track_job
from ..models import Stream
from ..stream_validation import stream_is_really_playable

logger = logging.getLogger("iptv-worker.healthcheck")


def _check_stream(stream_id: int, url: str, referrer: str | None, user_agent: str | None) -> tuple[int, bool]:
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
    if referrer:
        headers["Referer"] = referrer

    healthy = stream_is_really_playable(url, HEALTHCHECK_TIMEOUT_SEC, headers)
    return stream_id, healthy


@track_job("healthcheck")
def run():
    db = SessionLocal()
    try:
        streams = db.query(Stream).all()
        if not streams:
            logger.info("Nenhum stream cadastrado ainda, pulando health-check.")
            return {"streams": 0, "saudaveis": 0}

        logger.info("Testando %d streams (max_workers=%d)...", len(streams), HEALTHCHECK_MAX_WORKERS)

        tasks = [(s.id, s.url, s.referrer, s.user_agent) for s in streams]
        results: dict[int, bool] = {}

        with ThreadPoolExecutor(max_workers=HEALTHCHECK_MAX_WORKERS) as pool:
            futures = [pool.submit(_check_stream, *task) for task in tasks]
            for future in as_completed(futures):
                stream_id, healthy = future.result()
                results[stream_id] = healthy

        now = datetime.now(timezone.utc)
        healthy_count = 0
        for stream in streams:
            healthy = results.get(stream.id, False)
            stream.is_healthy = healthy
            stream.last_checked_at = now
            stream.consecutive_failures = 0 if healthy else stream.consecutive_failures + 1
            if healthy:
                healthy_count += 1

        db.commit()
        logger.info("Health-check concluído: %d/%d streams saudáveis.", healthy_count, len(streams))
        return {"streams": len(streams), "saudaveis": healthy_count}
    except Exception:
        db.rollback()
        logger.exception("Erro ao rodar health-check")
        raise
    finally:
        db.close()
