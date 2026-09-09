import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from ..config import HEALTHCHECK_MAX_WORKERS, HEALTHCHECK_TIMEOUT_SEC
from ..db import SessionLocal
from ..job_tracking import track_job
from ..models import Stream, VodItem
from ..stream_validation import stream_is_really_playable

logger = logging.getLogger("iptv-worker.healthcheck")


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
        # VOD (filmes/séries) usa link direto (.mp4/.ts, sem referrer/user-agent
        # customizado) — testado junto aqui pra dar 1 visão só de saude de link
        vod_items = db.query(VodItem).filter(VodItem.stream_url.isnot(None)).all()

        if not streams and not vod_items:
            logger.info("Nenhum link cadastrado ainda, pulando health-check.")
            return {"streams": 0, "saudaveis": 0, "vod_itens": 0, "vod_saudaveis": 0}

        logger.info(
            "Testando %d streams + %d itens VOD (max_workers=%d)...",
            len(streams), len(vod_items), HEALTHCHECK_MAX_WORKERS,
        )

        tasks = [("stream", s.id, s.url, s.referrer, s.user_agent) for s in streams]
        tasks += [("vod", v.id, v.stream_url, None, None) for v in vod_items]
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
        for item in vod_items:
            healthy = results.get(("vod", item.id), False)
            item.is_healthy = healthy
            item.last_checked_at = now
            item.consecutive_failures = 0 if healthy else item.consecutive_failures + 1
            if healthy:
                vod_healthy_count += 1

        db.commit()
        logger.info(
            "Health-check concluído: %d/%d streams saudáveis, %d/%d itens VOD saudáveis.",
            healthy_count, len(streams), vod_healthy_count, len(vod_items),
        )
        return {
            "streams": len(streams),
            "saudaveis": healthy_count,
            "vod_itens": len(vod_items),
            "vod_saudaveis": vod_healthy_count,
        }
    except Exception:
        db.rollback()
        logger.exception("Erro ao rodar health-check")
        raise
    finally:
        db.close()
