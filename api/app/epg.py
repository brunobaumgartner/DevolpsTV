from datetime import datetime, timedelta, timezone

from sqlalchemy import and_
from sqlalchemy.orm import Session

from .models import Program


def now_playing_map(db: Session, channel_ids: list[int]) -> dict[int, Program]:
    """channel_id -> programa que está passando agora, só pros canais que
    tiverem. Os horários no banco são gravados em UTC (ver worker/epg_sources.py)."""
    if not channel_ids:
        return {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = (
        db.query(Program)
        .filter(Program.channel_id.in_(channel_ids))
        .filter(Program.start_time <= now, Program.end_time > now)
        .all()
    )
    return {row.channel_id: row for row in rows}


def upcoming_programs(db: Session, channel_id: int, hours: int = 12):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    horizon = now + timedelta(hours=hours)
    return (
        db.query(Program)
        .filter(Program.channel_id == channel_id)
        .filter(Program.end_time > now, Program.start_time < horizon)
        .order_by(Program.start_time)
        .all()
    )
