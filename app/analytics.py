from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from statistics import mean
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import EventRecord, PosTransaction
from app.utils import ensure_utc, get_metadata_value, isoformat, utc_now


BILLING_HINTS = ("BILLING", "CHECKOUT", "POS", "CASH", "COUNTER", "QUEUE")


def is_billing_event(event: EventRecord) -> bool:
    zone = (event.zone_id or "").upper()
    sku_zone = str(get_metadata_value(event.event_metadata, "sku_zone", "")).upper()
    return event.event_type in {"BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON"} or any(
        hint in zone or hint in sku_zone for hint in BILLING_HINTS
    )


def latest_event_timestamp(db: Session, store_id: str | None = None) -> datetime | None:
    query = select(EventRecord).order_by(EventRecord.timestamp.desc()).limit(1)
    if store_id:
        query = query.where(EventRecord.store_id == store_id)
    record = db.execute(query).scalar_one_or_none()
    return ensure_utc(record.timestamp) if record else None


def analytics_day(db: Session, store_id: str) -> tuple[datetime, datetime]:
    latest = latest_event_timestamp(db, store_id) or utc_now()
    start = datetime.combine(ensure_utc(latest).date(), time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def events_for_window(db: Session, store_id: str, start: datetime, end: datetime) -> list[EventRecord]:
    return list(
        db.execute(
            select(EventRecord)
            .where(EventRecord.store_id == store_id)
            .where(EventRecord.timestamp >= start)
            .where(EventRecord.timestamp < end)
            .order_by(EventRecord.timestamp.asc())
        ).scalars()
    )


def pos_for_window(db: Session, store_id: str, start: datetime, end: datetime) -> list[PosTransaction]:
    return list(
        db.execute(
            select(PosTransaction)
            .where(PosTransaction.store_id == store_id)
            .where(PosTransaction.timestamp >= start)
            .where(PosTransaction.timestamp < end)
            .order_by(PosTransaction.timestamp.asc())
        ).scalars()
    )


def non_staff_events(events: Iterable[EventRecord]) -> list[EventRecord]:
    return [event for event in events if not event.is_staff]


def unique_visitors(events: Iterable[EventRecord]) -> set[str]:
    return {event.visitor_id for event in events if not event.is_staff}


def converted_visitors(events: Iterable[EventRecord], transactions: Iterable[PosTransaction]) -> set[str]:
    billing_events = [
        event
        for event in non_staff_events(events)
        if is_billing_event(event) and event.event_type != "BILLING_QUEUE_ABANDON"
    ]
    converted: set[str] = set()
    for transaction in transactions:
        txn_ts = ensure_utc(transaction.timestamp)
        window_start = txn_ts - timedelta(minutes=5)
        candidates = [
            event
            for event in billing_events
            if window_start <= ensure_utc(event.timestamp) <= txn_ts
        ]
        if candidates:
            best = max(candidates, key=lambda event: ensure_utc(event.timestamp))
            converted.add(best.visitor_id)
    return converted


def current_queue_depth(events: Iterable[EventRecord]) -> int:
    depth = 0
    latest_ts = None
    for event in events:
        queue_depth = get_metadata_value(event.event_metadata, "queue_depth")
        if queue_depth is None:
            continue
        event_ts = ensure_utc(event.timestamp)
        if latest_ts is None or event_ts > latest_ts:
            latest_ts = event_ts
            depth = int(queue_depth)
        elif event_ts == latest_ts:
            depth = max(depth, int(queue_depth))
    return max(depth, 0)


def average_dwell_by_zone(events: Iterable[EventRecord]) -> dict[str, float]:
    dwell: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if event.is_staff or event.event_type != "ZONE_DWELL" or not event.zone_id:
            continue
        dwell[event.zone_id].append(event.dwell_ms)
    return {zone: round(mean(values), 2) for zone, values in dwell.items() if values}


def abandonment_rate(events: Iterable[EventRecord]) -> float:
    joins = {event.visitor_id for event in events if not event.is_staff and event.event_type == "BILLING_QUEUE_JOIN"}
    abandons = {event.visitor_id for event in events if not event.is_staff and event.event_type == "BILLING_QUEUE_ABANDON"}
    queue_visitors = joins | abandons
    if not queue_visitors:
        return 0.0
    return round(len(abandons) / len(queue_visitors), 4)


def conversion_rate_for_day(db: Session, store_id: str, start: datetime, end: datetime) -> float:
    events = events_for_window(db, store_id, start, end)
    visitors = unique_visitors(events)
    if not visitors:
        return 0.0
    converted = converted_visitors(events, pos_for_window(db, store_id, start, end))
    return round(len(converted) / len(visitors), 4)


def event_summary(event: EventRecord) -> dict:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "timestamp": isoformat(event.timestamp),
        "visitor_id": event.visitor_id,
        "zone_id": event.zone_id,
        "is_staff": event.is_staff,
        "confidence": event.confidence,
        "metadata": event.event_metadata,
    }
