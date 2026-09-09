import logging

from ..db import SessionLocal
from ..epg_sources import EPG_SOURCE_URLS, fetch_and_parse, normalize_channel_name
from ..job_tracking import track_job
from ..models import Channel, Program

logger = logging.getLogger("iptv-worker.fetch_epg")


@track_job("fetch_epg")
def run():
    logger.info("Buscando EPG de %d fonte(s) (BrazilTVEPG)...", len(EPG_SOURCE_URLS))

    db = SessionLocal()
    try:
        # mapa nome-normalizado -> channel_id, construído 1x e reaproveitado pra
        # todas as fontes desse ciclo (cruzamento por igualdade exata, sem fuzzy)
        our_channels = db.query(Channel.id, Channel.name).all()
        name_to_channel_id: dict[str, int] = {}
        for channel_id, name in our_channels:
            key = normalize_channel_name(name)
            if key and key not in name_to_channel_id:
                name_to_channel_id[key] = channel_id

        total_matched_channels = 0
        total_programs_inserted = 0

        for source_name, url in EPG_SOURCE_URLS.items():
            try:
                epg_channel_names, programmes = fetch_and_parse(source_name, url)

                # quais canais desse EPG batem com algum canal nosso
                matched: dict[str, int] = {}
                for epg_name in epg_channel_names:
                    key = normalize_channel_name(epg_name)
                    channel_id = name_to_channel_id.get(key)
                    if channel_id is not None:
                        matched[epg_name] = channel_id

                matched_channel_ids = set(matched.values())
                logger.info(
                    "[%s] %d/%d canais do EPG casaram com o catálogo",
                    source_name,
                    len(matched_channel_ids),
                    len(epg_channel_names),
                )

                if matched_channel_ids:
                    # substitui por completo a programação desses canais nessa
                    # fonte — mais simples e correto que tentar diff incremental
                    # num dado que já é essencialmente uma janela rolante
                    db.query(Program).filter(Program.channel_id.in_(matched_channel_ids)).delete(
                        synchronize_session=False
                    )

                inserted_here = 0
                for p in programmes:
                    channel_id = matched.get(p.channel_name_raw)
                    if channel_id is None:
                        continue
                    db.add(
                        Program(
                            channel_id=channel_id,
                            title=p.title,
                            subtitle=p.subtitle,
                            description=p.description,
                            category=p.category,
                            start_time=p.start,
                            end_time=p.end,
                        )
                    )
                    inserted_here += 1

                db.commit()
                total_matched_channels += len(matched_channel_ids)
                total_programs_inserted += inserted_here
                logger.info("[%s] %d programa(s) inserido(s)", source_name, inserted_here)
            except Exception:
                db.rollback()
                logger.exception("[%s] erro ao processar fonte de EPG, seguindo pras próximas", source_name)

        logger.info(
            "Fetch de EPG concluído. %d canal(is) com programação, %d programa(s) no total.",
            total_matched_channels,
            total_programs_inserted,
        )
        return {"canais_com_epg": total_matched_channels, "programas": total_programs_inserted}
    finally:
        db.close()
