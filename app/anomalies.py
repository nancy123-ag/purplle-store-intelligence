from __future__ import annotations

from datetime import timedelta
from statistics import mean

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.analytics import (
    analytics_day,
    conversion_rate_for_day,
    current_queue_depth,
    events_for_window,
    latest_event_timestamp,
)
from app.database import get_session
from app.store_config import known_zone_ids
from app.utils import ensure_utc, isoformat


router = APIRouter(tags=["anomalies"])


@router.get("/stores/{store_id}/anomalies")
def store_anomalies(store_id: str, request: Request, db: Session = Depends(get_session)) -> dict:
    start, end = analytics_day(db, store_id)
    events = events_for_window(db, store_id, start, end)
    latest = latest_event_timestamp(db, store_id)
    active = []

    queue_depth = current_queue_depth(events)
    if queue_depth >= 8:
        active.append(
            {
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "CRITICAL",
                "observed_value": queue_depth,
                "suggested_action": "Open another billing counter or redirect staff to checkout.",
            }
        )
    elif queue_depth >= 5:
        active.append(
            {
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "WARN",
                "observed_value": queue_depth,
                "suggested_action": "Monitor the queue and prepare backup billing support.",
            }
        )

    current_cr = conversion_rate_for_day(db, store_id, start, end)
    prior_rates = []
    for offset in range(1, 8):
        day_start = start - timedelta(days=offset)
        prior_rates.append(conversion_rate_for_day(db, store_id, day_start, day_start + timedelta(days=1)))
    non_zero_prior = [rate for rate in prior_rates if rate > 0]
    if non_zero_prior:
        baseline = mean(non_zero_prior)
        if current_cr < baseline * 0.5:
            active.append(
                {
                    "type": "CONVERSION_DROP",
                    "severity": "CRITICAL" if current_cr < baseline * 0.25 else "WARN",
                    "observed_value": current_cr,
                    "baseline_7_day_avg": round(baseline, 4),
                    "suggested_action": "Inspect staffing, billing wait time, and stock availability in high-traffic zones.",
                }
            )

    if latest:
        nowish = ensure_utc(latest)
        visited_recently = {
            event.zone_id
            for event in events
            if event.zone_id
            and event.event_type in {"ZONE_ENTER", "ZONE_DWELL", "BILLING_QUEUE_JOIN"}
            and nowish - ensure_utc(event.timestamp) <= timedelta(minutes=30)
        }
        all_zones = known_zone_ids(getattr(request.app.state, "layout", {}), store_id) | {
            event.zone_id for event in events if event.zone_id
        }
        dead_zones = sorted(zone for zone in all_zones if zone not in visited_recently)
        for zone_id in dead_zones[:5]:
            active.append(
                {
                    "type": "DEAD_ZONE",
                    "severity": "INFO",
                    "zone_id": zone_id,
                    "suggested_action": "Check whether the camera, display, or staff coverage changed for this zone.",
                }
            )

    return {
        "store_id": store_id,
        "window_start": isoformat(start),
        "window_end": isoformat(end),
        "anomalies": active,
    }

