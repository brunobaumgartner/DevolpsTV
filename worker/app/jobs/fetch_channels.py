import logging

from ..db import SessionLocal
from ..job_tracking import track_job
from ..models import Channel, Stream
from ..sources import ALL_SOURCES, is_broadcast_tv

logger = logging.getLogger("iptv-worker.fetch_channels")


@track_job("fetch_channels")
def run():
    logger.info("Buscando canais/streams de %d fonte(s) configurada(s)...", len(ALL_SOURCES))

    total_new_channels = 0
    total_new_streams = 0

    db = SessionLocal()
    try:
        channel_by_tvg_id: dict[str, Channel] = {c.tvg_id: c for c in db.query(Channel).all()}

        for loader in ALL_SOURCES:
            source_name = loader.__name__
            new_channels = 0
            new_streams = 0

            try:
                for entry in loader():
                    channel = channel_by_tvg_id.get(entry.tvg_id)
                    if channel is None:
                        channel = Channel(tvg_id=entry.tvg_id, name=entry.name)
                        db.add(channel)
                        db.flush()  # garante channel.id disponível pro Stream abaixo
                        channel_by_tvg_id[entry.tvg_id] = channel
                        new_channels += 1

                    # a fonte que "descobriu" o canal primeiro (ordem de ALL_SOURCES)
                    # já preencheu os metadados; fontes seguintes só completam o
                    # que ainda estiver vazio, nunca sobrescrevem
                    if not channel.logo_url and entry.logo_url:
                        channel.logo_url = entry.logo_url
                    if not channel.category and entry.category:
                        channel.category = entry.category
                    if not channel.is_broadcast_tv:
                        channel.is_broadcast_tv = is_broadcast_tv(entry.name)
                    channel.is_active = True

                    existing_stream = next((s for s in channel.streams if s.url == entry.url), None)
                    if existing_stream is None:
                        new_stream = Stream(channel_id=channel.id, url=entry.url)
                        db.add(new_stream)
                        channel.streams.append(new_stream)
                        new_streams += 1

                db.commit()  # commita por fonte: se uma fonte falhar, não perde as anteriores
                logger.info("[%s] +%d canal(is) novo(s), +%d stream(s) novo(s)", source_name, new_channels, new_streams)
                total_new_channels += new_channels
                total_new_streams += new_streams
            except Exception:
                db.rollback()
                logger.exception("[%s] erro ao processar fonte, seguindo pras próximas", source_name)

        logger.info("Fetch concluído. Total de canais conhecidos: %d", len(channel_by_tvg_id))
        return {
            "canais_conhecidos": len(channel_by_tvg_id),
            "canais_novos": total_new_channels,
            "streams_novos": total_new_streams,
        }
    finally:
        db.close()
