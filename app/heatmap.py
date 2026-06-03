from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.analytics import analytics_day, events_for_window, unique_visitors
from app.database import get_session
from app.store_config import known_zone_ids
from app.utils import isoformat


router = APIRouter(tags=["heatmap"])


@router.get("/stores/{store_id}/heatmap")
def store_heatmap(store_id: str, request: Request, db: Session = Depends(get_session)) -> dict:
    start, end = analytics_day(db, store_id)
    events = [event for event in events_for_window(db, store_id, start, end) if not event.is_staff]
    configured_zones = known_zone_ids(getattr(request.app.state, "layout", {}), store_id)

    visits: dict[str, set[str]] = defaultdict(set)
    dwell: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if not event.zone_id:
            continue
        if event.event_type in {"ZONE_ENTER", "ZONE_DWELL", "BILLING_QUEUE_JOIN"}:
            visits[event.zone_id].add(event.visitor_id)
        if event.event_type == "ZONE_DWELL":
            dwell[event.zone_id].append(event.dwell_ms)

    all_zones = configured_zones | set(visits) | set(dwell)
    max_visits = max((len(visitors) for visitors in visits.values()), default=0)
    max_dwell = max((sum(values) / len(values) for values in dwell.values() if values), default=0)

    cells = []
    for zone_id in sorted(all_zones):
        visit_count = len(visits.get(zone_id, set()))
        avg_dwell = round(sum(dwell.get(zone_id, [])) / len(dwell[zone_id]), 2) if dwell.get(zone_id) else 0.0
        visit_score = visit_count / max_visits if max_visits else 0.0
        dwell_score = avg_dwell / max_dwell if max_dwell else 0.0
        score = round((0.7 * visit_score + 0.3 * dwell_score) * 100, 2)
        cells.append(
            {
                "zone_id": zone_id,
                "visit_frequency": visit_count,
                "avg_dwell_ms": avg_dwell,
                "score": score,
            }
        )

    session_count = len(unique_visitors(events))
    return {
        "store_id": store_id,
        "window_start": isoformat(start),
        "window_end": isoformat(end),
        "data_confidence": "LOW" if session_count < 20 else "HIGH",
        "session_count": session_count,
        "zones": cells,
    }

