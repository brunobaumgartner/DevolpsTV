import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from ..config import HEALTHCHECK_MAX_WORKERS, HEALTHCHECK_TIMEOUT_SEC
from ..db import SessionLocal
from ..job_tracking import track_job
from ..models import Stream, VodStream
from ..stream_validation import stream_is_really_playable

logger = logging.getLogger("iptv-worker.healthcheck")

# o catálogo VOD tem centenas de milhares de itens — testar todos a cada
# ciclo levaria horas. Cada rodada pega só um LOTE dos mais desatualizados
# (nunca checados ou checados há +VOD_STALE_HOURS). Assim o catálogo inteiro
# roda em ~1 dia sem cada ciclo estourar o tempo.
VOD_BATCH = 4000
VOD_STALE_HOURS = 18


def _check_stream(row_id: int, url: str, referrer: str | None, user_agent: str | None) -> tuple[int, bool]:
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
    if referrer:
        headers["Referer"] = referrer

    healthy = stream_is_really_playable(url, HEALTHCHECK_TIMEOUT_SEC, headers)
    return row_id, healthy


@track_job("healthcheck")
def run():
    db = SessionLocal()
    try:
        streams = db.query(Stream).all()
        # VOD: só um lote rotativo dos mirrors mais desatualizados por ciclo
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=VOD_STALE_HOURS)
        vod_streams = (
            db.query(VodStream)
            .filter(or_(VodStream.last_checked_at.is_(None), VodStream.last_checked_at < cutoff))
            .order_by(VodStream.last_checked_at.is_(None).desc(), VodStream.last_checked_at.asc())
            .limit(VOD_BATCH)
            .all()
        )

        if not streams and not vod_streams:
            logger.info("Nenhum link cadastrado ainda, pulando health-check.")
            return {"streams": 0, "saudaveis": 0, "vod_itens": 0, "vod_saudaveis": 0}

        logger.info(
            "Testando %d streams + %d mirrors VOD (max_workers=%d)...",
            len(streams), len(vod_streams), HEALTHCHECK_MAX_WORKERS,
        )

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
        logger.info(
            "Health-check concluído: %d/%d streams saudáveis, %d/%d mirrors VOD saudáveis.",
            healthy_count, len(streams), vod_healthy_count, len(vod_streams),
        )
        return {
            "streams": len(streams),
            "saudaveis": healthy_count,
            "vod_itens": len(vod_streams),
            "vod_saudaveis": vod_healthy_count,
        }
    except Exception:
        db.rollback()
        logger.exception("Erro ao rodar health-check")
        raise
    finally:
        db.close()
