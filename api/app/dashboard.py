"""Agregações pro dashboard de monitoramento (/dashboard.html). Tudo aqui é
leitura pura — nenhuma dessas consultas altera dados."""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from .categories_pt import category_label as _cat_label
from .models import AccessToken, Channel, Program, Stream, VodItem, VodTitle, WorkerRun


def get_dashboard_stats(db: Session) -> dict:
    total_channels = db.query(func.count(Channel.id)).filter(Channel.is_active.is_(True)).scalar() or 0
    total_streams = db.query(func.count(Stream.id)).scalar() or 0
    healthy_streams = db.query(func.count(Stream.id)).filter(Stream.is_healthy.is_(True)).scalar() or 0

    # streams por idioma (lang_label NULL = "Português": canal de país lusófono
    # ou fonte brasileira sem info de feed do iptv-org)
    lang_rows = (
        db.query(func.coalesce(Stream.lang_label, "Português"), func.count(Stream.id))
        .group_by(func.coalesce(Stream.lang_label, "Português"))
        .order_by(func.count(Stream.id).desc())
        .all()
    )
    streams_by_language = [{"language": lang, "count": count} for lang, count in lang_rows]

    # canais ativos que tem pelo menos 1 stream saudavel (o que de fato aparece na playlist)
    channels_with_healthy = (
        db.query(func.count(func.distinct(Stream.channel_id)))
        .join(Channel, Channel.id == Stream.channel_id)
        .filter(Channel.is_active.is_(True), Stream.is_healthy.is_(True))
        .scalar()
        or 0
    )

    broadcast_tv_count = (
        db.query(func.count(Channel.id)).filter(Channel.is_active.is_(True), Channel.is_broadcast_tv.is_(True)).scalar() or 0
    )

    category_rows = (
        db.query(Channel.category, func.count(Channel.id))
        .filter(Channel.is_active.is_(True))
        .group_by(Channel.category)
        .order_by(func.count(Channel.id).desc())
        .all()
    )
    by_category = [
        {"category": _cat_label(cat) or "Sem categoria", "count": count}
        for cat, count in category_rows
    ]

    total_programs = db.query(func.count(Program.id)).scalar() or 0
    channels_with_epg = db.query(func.count(func.distinct(Program.channel_id))).scalar() or 0

    total_vod_titles = db.query(func.count(VodTitle.id)).scalar() or 0
    vod_movies = db.query(func.count(VodTitle.id)).filter(VodTitle.type == "movie").scalar() or 0
    vod_series = db.query(func.count(VodTitle.id)).filter(VodTitle.type == "series").scalar() or 0
    total_vod_items = db.query(func.count(VodItem.id)).scalar() or 0
    vod_items_with_link = db.query(func.count(VodItem.id)).filter(VodItem.stream_url.isnot(None)).scalar() or 0

    movies_by_genre_rows = (
        db.query(VodTitle.genre, func.count(VodTitle.id))
        .filter(VodTitle.type == "movie")
        .group_by(VodTitle.genre)
        .order_by(func.count(VodTitle.id).desc())
        .all()
    )
    movies_by_genre = [{"genre": g or "sem gênero", "count": c} for g, c in movies_by_genre_rows]

    series_by_genre_rows = (
        db.query(VodTitle.genre, func.count(VodTitle.id))
        .filter(VodTitle.type == "series")
        .group_by(VodTitle.genre)
        .order_by(func.count(VodTitle.id).desc())
        .all()
    )
    series_by_genre = [{"genre": g or "sem gênero", "count": c} for g, c in series_by_genre_rows]

    active_tokens = db.query(func.count(AccessToken.id)).filter(AccessToken.is_active.is_(True)).scalar() or 0

    worker_runs = db.query(WorkerRun).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    jobs = []
    for run in worker_runs:
        age_seconds = (now - run.last_run_at).total_seconds() if run.last_run_at else None
        jobs.append(
            {
                "job_name": run.job_name,
                "last_run_at": run.last_run_at.isoformat() if run.last_run_at else None,
                "status": run.status,
                "summary": run.summary,
                "duration_seconds": run.duration_seconds,
                "age_seconds": age_seconds,
            }
        )

    return {
        "channels": {
            "total_active": total_channels,
            "with_healthy_stream": channels_with_healthy,
            "broadcast_tv": broadcast_tv_count,
            "by_category": by_category,
        },
        "streams": {
            "total": total_streams,
            "healthy": healthy_streams,
            "unhealthy": total_streams - healthy_streams,
            "by_language": streams_by_language,
        },
        "epg": {
            "total_programs": total_programs,
            "channels_with_epg": channels_with_epg,
        },
        "vod": {
            "total_titles": total_vod_titles,
            "movies": vod_movies,
            "series": vod_series,
            "total_items": total_vod_items,
            "items_with_link": vod_items_with_link,
            "movies_by_genre": movies_by_genre,
            "series_by_genre": series_by_genre,
        },
        "access_tokens": active_tokens,
        "worker_jobs": jobs,
    }
