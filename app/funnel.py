from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics import analytics_day, converted_visitors, events_for_window, is_billing_event, pos_for_window
from app.database import get_session
from app.utils import isoformat


router = APIRouter(tags=["funnel"])


def _dropoff(previous: int, current: int) -> float:
    if previous <= 0:
        return 0.0
    return round(max(previous - current, 0) / previous, 4)


@router.get("/stores/{store_id}/funnel")
def store_funnel(store_id: str, db: Session = Depends(get_session)) -> dict:
    start, end = analytics_day(db, store_id)
    events = [event for event in events_for_window(db, store_id, start, end) if not event.is_staff]

    entry_visitors = {
        event.visitor_id for event in events if event.event_type in {"ENTRY", "REENTRY"}
    } or {event.visitor_id for event in events}
    zone_visitors = {
        event.visitor_id
        for event in events
        if event.event_type in {"ZONE_ENTER", "ZONE_DWELL", "ZONE_EXIT"} and event.zone_id
    }
    billing_visitors = {event.visitor_id for event in events if is_billing_event(event)}
    purchased_visitors = converted_visitors(events, pos_for_window(db, store_id, start, end))

    stages = [
        {"stage": "ENTRY", "count": len(entry_visitors), "dropoff_from_previous": 0.0},
        {"stage": "ZONE_VISIT", "count": len(zone_visitors), "dropoff_from_previous": _dropoff(len(entry_visitors), len(zone_visitors))},
        {
            "stage": "BILLING_QUEUE",
            "count": len(billing_visitors),
            "dropoff_from_previous": _dropoff(len(zone_visitors), len(billing_visitors)),
        },
        {
            "stage": "PURCHASE",
            "count": len(purchased_visitors),
            "dropoff_from_previous": _dropoff(len(billing_visitors), len(purchased_visitors)),
        },
    ]

    return {
        "store_id": store_id,
        "window_start": isoformat(start),
        "window_end": isoformat(end),
        "unit": "session",
        "reentries_deduplicated": True,
        "stages": stages,
    }

