from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics import (
    abandonment_rate,
    analytics_day,
    average_dwell_by_zone,
    converted_visitors,
    current_queue_depth,
    events_for_window,
    pos_for_window,
    unique_visitors,
)
from app.database import get_session
from app.utils import isoformat


router = APIRouter(tags=["metrics"])


@router.get("/stores/{store_id}/metrics")
def store_metrics(store_id: str, db: Session = Depends(get_session)) -> dict:
    start, end = analytics_day(db, store_id)
    events = events_for_window(db, store_id, start, end)
    transactions = pos_for_window(db, store_id, start, end)
    visitors = unique_visitors(events)
    converted = converted_visitors(events, transactions)
    conversion_rate = round(len(converted) / len(visitors), 4) if visitors else 0.0

    return {
        "store_id": store_id,
        "window_start": isoformat(start),
        "window_end": isoformat(end),
        "unique_visitors": len(visitors),
        "conversion_rate": conversion_rate,
        "converted_visitors": len(converted),
        "avg_dwell_ms_per_zone": average_dwell_by_zone(events),
        "queue_depth": current_queue_depth(events),
        "billing_queue_abandonment_rate": abandonment_rate(events),
        "transactions": len(transactions),
        "real_time": True,
    }

