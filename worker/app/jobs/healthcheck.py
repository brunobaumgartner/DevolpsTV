import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from ..config import HEALTHCHECK_MAX_WORKERS, HEALTHCHECK_TIMEOUT_SEC
from ..db import SessionLocal
from ..job_tracking import track_job
from ..models import Stream, VodStream
from ..stream_validation import INCONCLUSIVO, MORTO, OK, check_stream

logger = logging.getLogger("iptv-worker.healthcheck")

# o catálogo VOD tem centenas de milhares de itens — testar todos a cada
# ciclo levaria horas. Cada rodada pega só um LOTE dos mais desatualizados
# (nunca checados ou checados há +VOD_STALE_HOURS), priorizando os que nunca
# foram vistos. Com 578 mil mirrors e 1 rodada por hora, uma passada completa
# leva ~2,5 dias — de propósito: o teste de VOD a partir da VPS é quase todo
# inconclusivo (ver stream_validation.check_stream), então correr mais rápido
# só gastaria CPU sem produzir informação melhor.
VOD_BATCH = 10000
VOD_STALE_HOURS = 18


def _check_stream(row_id: int, url: str, referrer: str | None, user_agent: str | None) -> tuple[int, str]:
    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent
    if referrer:
        headers["Referer"] = referrer

    return row_id, check_stream(url, HEALTHCHECK_TIMEOUT_SEC, headers)


def _aplicar(rows, results, kind, now) -> dict:
    """Grava o resultado de cada link. INCONCLUSIVO vira is_healthy=NULL
    (desconhecido) em vez de False: o teste sai do IP da VPS, e link que
    responde página/403 aqui pode estar perfeito no navegador do usuário
    (comprovado em 2026-09-14). Só MORTO conta como falha de verdade."""
    contagem = {OK: 0, MORTO: 0, INCONCLUSIVO: 0}
    for row in rows:
        estado = results.get((kind, row.id), INCONCLUSIVO)
        contagem[estado] += 1
        row.last_checked_at = now
        if estado == OK:
            row.is_healthy = True
            row.consecutive_failures = 0
        elif estado == MORTO:
            row.is_healthy = False
            row.consecutive_failures = row.consecutive_failures + 1
        else:
            row.is_healthy = None  # não sabemos — quem decide é o cliente
    return contagem


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
        results: dict[tuple[str, int], str] = {}

        with ThreadPoolExecutor(max_workers=HEALTHCHECK_MAX_WORKERS) as pool:
            futures = {
                pool.submit(_check_stream, row_id, url, referrer, user_agent): (kind, row_id)
                for kind, row_id, url, referrer, user_agent in tasks
            }
            for future in as_completed(futures):
                kind, row_id = futures[future]
                _, estado = future.result()
                results[(kind, row_id)] = estado

        now = datetime.now(timezone.utc)
        ch = _aplicar(streams, results, "stream", now)
        vod = _aplicar(vod_streams, results, "vod", now)

        db.commit()
        logger.info(
            "Health-check concluído. Canais: %d ok, %d mortos, %d inconclusivos. "
            "VOD: %d ok, %d mortos, %d inconclusivos.",
            ch[OK], ch[MORTO], ch[INCONCLUSIVO], vod[OK], vod[MORTO], vod[INCONCLUSIVO],
        )
        return {
            "streams": len(streams),
            "saudaveis": ch[OK],
            "mortos": ch[MORTO],
            "inconclusivos": ch[INCONCLUSIVO],
            "vod_itens": len(vod_streams),
            "vod_saudaveis": vod[OK],
            "vod_mortos": vod[MORTO],
            "vod_inconclusivos": vod[INCONCLUSIVO],
        }
    except Exception:
        db.rollback()
        logger.exception("Erro ao rodar health-check")
        raise
    finally:
        db.close()
