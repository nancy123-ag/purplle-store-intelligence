from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, select, text
from sqlalchemy.orm import Session

from app.analytics import latest_event_timestamp
from app.database import EventRecord, get_session
from app.utils import ensure_utc, isoformat, utc_now


router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_session)) -> dict:
    db.execute(text("SELECT 1"))
    stores = list(db.execute(select(distinct(EventRecord.store_id))).scalars())
    now = utc_now()
    feeds = []
    stale = False
    for store_id in stores:
        last_event = latest_event_timestamp(db, store_id)
        lag_seconds = None
        status = "NO_EVENTS"
        if last_event:
            lag_seconds = max(int((now - ensure_utc(last_event)).total_seconds()), 0)
            status = "STALE_FEED" if lag_seconds > int(timedelta(minutes=10).total_seconds()) else "OK"
            stale = stale or status == "STALE_FEED"
        feeds.append(
            {
                "store_id": store_id,
                "last_event_timestamp": isoformat(last_event),
                "lag_seconds": lag_seconds,
                "status": status,
            }
        )

    latest = latest_event_timestamp(db)
    return {
        "status": "DEGRADED" if stale else "OK",
        "database": "OK",
        "last_event_timestamp": isoformat(latest),
        "feeds": feeds,
    }

