import logging

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler

from .config import EPG_FETCH_INTERVAL_MIN, FETCH_CHANNELS_INTERVAL_MIN, HEALTHCHECK_INTERVAL_MIN
from .jobs import fetch_channels, fetch_epg, fetch_fast_meta, healthcheck

logger = logging.getLogger("iptv-worker.scheduler")


def run_forever():
    # 1 thread só: os jobs rodam UM DE CADA VEZ, nunca em paralelo.
    # Achado em 2026-09-14: fetch_epg e fetch_fast_meta estão no mesmo
    # intervalo (3h) e começavam com 15s de diferença, mas o fetch_epg leva
    # ~2min — os dois se atropelavam apagando/inserindo na MESMA tabela
    # (programs, `DELETE ... WHERE channel_id IN (...)` nos dois), e o
    # fetch_fast_meta morria com "Deadlock found when trying to get lock".
    # Serializar também tira o pico de CPU de dois jobs pesados juntos.
    scheduler = BlockingScheduler(timezone="UTC", executors={"default": ThreadPoolExecutor(1)})

    scheduler.add_job(
        fetch_channels.run,
        "interval",
        minutes=FETCH_CHANNELS_INTERVAL_MIN,
        id="fetch_channels",
        next_run_time=_now(),  # roda uma vez já na subida
    )
    scheduler.add_job(
        healthcheck.run,
        "interval",
        minutes=HEALTHCHECK_INTERVAL_MIN,
        id="healthcheck",
        next_run_time=_now_plus_seconds(30),  # dá tempo do fetch inicial popular o banco
    )
    scheduler.add_job(
        fetch_epg.run,
        "interval",
        minutes=EPG_FETCH_INTERVAL_MIN,
        id="fetch_epg",
        next_run_time=_now_plus_seconds(45),  # depois do fetch_channels ter os canais no banco
    )
    scheduler.add_job(
        fetch_fast_meta.run,
        "interval",
        minutes=EPG_FETCH_INTERVAL_MIN,
        id="fetch_fast_meta",
        next_run_time=_now_plus_seconds(60),
    )

    logger.info(
        "Scheduler iniciado. fetch_channels a cada %dmin, healthcheck a cada %dmin, "
        "fetch_epg/fetch_fast_meta a cada %dmin.",
        FETCH_CHANNELS_INTERVAL_MIN,
        HEALTHCHECK_INTERVAL_MIN,
        EPG_FETCH_INTERVAL_MIN,
    )
    scheduler.start()


def _now():
    import datetime

    return datetime.datetime.now(datetime.timezone.utc)


def _now_plus_seconds(seconds: int):
    import datetime

    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
