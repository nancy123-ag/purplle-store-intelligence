from __future__ import annotations

import json
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import EventRecord, get_session
from app.models import IngestResult, StoreEvent


router = APIRouter(tags=["ingestion"])

RESOURCE_EVENT_TYPE_MAP = {
    "entry": "ENTRY",
    "exit": "EXIT",
    "zone_entered": "ZONE_ENTER",
    "zone_exited": "ZONE_EXIT",
    "queue_completed": "BILLING_QUEUE_JOIN",
    "queue_abandoned": "BILLING_QUEUE_ABANDON",
}


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n", ""}:
            return False
    raise ValueError(f"Cannot parse boolean value: {value!r}")


def _coerce_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _payload_to_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        return payload["events"]
    raise HTTPException(
        status_code=400,
        detail={
            "code": "BAD_REQUEST",
            "message": "Expected a JSON array of events or an object with an events array.",
        },
    )


def _deterministic_event_id(raw_event: dict[str, Any]) -> str:
    if raw_event.get("event_id"):
        return str(raw_event["event_id"])
    if raw_event.get("queue_event_id"):
        return str(raw_event["queue_event_id"])
    encoded = json.dumps(raw_event, sort_keys=True, separators=(",", ":"), default=str)
    return str(uuid5(NAMESPACE_URL, encoded))


def _normalize_resource_store_id(value: Any) -> str:
    store = str(value or "STORE_BLR_002").strip()
    match = re.fullmatch(r"store[_\s-]*(\d+)", store, flags=re.IGNORECASE)
    if match:
        return f"ST{match.group(1)}"
    return store.upper()


def _resource_timestamp(raw_event: dict[str, Any], source_type: str) -> Any:
    if source_type in {"entry", "exit"}:
        return raw_event.get("event_timestamp")
    if source_type in {"queue_completed", "queue_abandoned"}:
        if source_type == "queue_abandoned":
            return raw_event.get("queue_exit_ts") or raw_event.get("queue_join_ts")
        return raw_event.get("queue_join_ts") or raw_event.get("queue_served_ts") or raw_event.get("queue_exit_ts")
    return raw_event.get("event_time")


def normalize_raw_event(raw_event: Any) -> Any:
    if not isinstance(raw_event, dict):
        return raw_event
    if raw_event.get("event_id") and raw_event.get("visitor_id") and raw_event.get("timestamp"):
        return raw_event

    source_type = str(raw_event.get("event_type", "")).lower()
    mapped_type = RESOURCE_EVENT_TYPE_MAP.get(source_type)
    if not mapped_type:
        return raw_event

    visitor = raw_event.get("id_token") or raw_event.get("visitor_id") or raw_event.get("track_id")
    visitor_id = str(visitor) if visitor is not None else f"VIS_{_deterministic_event_id(raw_event)[:8]}"
    if visitor_id.isdigit():
        visitor_id = f"TRACK_{visitor_id}"

    store_id = _normalize_resource_store_id(raw_event.get("store_id") or raw_event.get("store_code"))
    queue_depth = raw_event.get("queue_depth")
    if queue_depth is None:
        queue_depth = raw_event.get("queue_position_at_join")
    timestamp = _resource_timestamp(raw_event, source_type)
    metadata = {
        "source_event_type": source_type,
        "queue_depth": queue_depth,
        "sku_zone": raw_event.get("zone_name") or raw_event.get("zone_type"),
        "session_seq": raw_event.get("session_seq"),
        "group_id": raw_event.get("group_id"),
        "group_size": raw_event.get("group_size"),
        "gender": raw_event.get("gender") or raw_event.get("gender_pred"),
        "age": raw_event.get("age") or raw_event.get("age_pred"),
        "age_bucket": raw_event.get("age_bucket"),
        "zone_type": raw_event.get("zone_type"),
        "is_revenue_zone": raw_event.get("is_revenue_zone"),
        "wait_seconds": raw_event.get("wait_seconds"),
        "queue_join_ts": raw_event.get("queue_join_ts"),
        "queue_served_ts": raw_event.get("queue_served_ts"),
        "queue_exit_ts": raw_event.get("queue_exit_ts"),
        "zone_hotspot_x": raw_event.get("zone_hotspot_x"),
        "zone_hotspot_y": raw_event.get("zone_hotspot_y"),
    }
    metadata = {key: value for key, value in metadata.items() if value is not None}
    dwell_ms = int(_coerce_float(raw_event.get("wait_seconds"), 0.0) * 1000) if source_type.startswith("queue_") else 0

    return {
        "event_id": _deterministic_event_id(raw_event),
        "store_id": store_id,
        "camera_id": str(raw_event.get("camera_id") or "CAM_UNKNOWN").upper(),
        "visitor_id": visitor_id,
        "event_type": mapped_type,
        "timestamp": timestamp,
        "zone_id": raw_event.get("zone_id"),
        "dwell_ms": dwell_ms,
        "is_staff": _coerce_bool(raw_event.get("is_staff", False)),
        "confidence": _coerce_float(raw_event.get("confidence"), 0.75),
        "metadata": metadata,
    }


def record_from_event(event: StoreEvent) -> EventRecord:
    return EventRecord(
        event_id=event.event_id,
        store_id=event.store_id,
        camera_id=event.camera_id,
        visitor_id=event.visitor_id,
        event_type=event.event_type.value,
        timestamp=event.timestamp,
        zone_id=event.zone_id,
        dwell_ms=event.dwell_ms,
        is_staff=event.is_staff,
        confidence=event.confidence,
        event_metadata=event.metadata.model_dump(mode="json"),
        raw_payload=event.model_dump(mode="json"),
    )


def ingest_batch(db: Session, raw_events: list[dict[str, Any]]) -> IngestResult:
    accepted = 0
    duplicates = 0
    errors: list[dict[str, Any]] = []
    seen_in_batch: set[str] = set()

    for index, raw_event in enumerate(raw_events):
        try:
            normalized_event = normalize_raw_event(raw_event)
        except (TypeError, ValueError) as exc:
            errors.append(
                {
                    "index": index,
                    "event_id": raw_event.get("event_id") if isinstance(raw_event, dict) else None,
                    "code": "NORMALIZATION_ERROR",
                    "details": [{"msg": str(exc)}],
                }
            )
            continue
        try:
            event = StoreEvent.model_validate(normalized_event)
        except ValidationError as exc:
            errors.append(
                {
                    "index": index,
                    "event_id": normalized_event.get("event_id") if isinstance(normalized_event, dict) else None,
                    "code": "VALIDATION_ERROR",
                    "details": exc.errors(),
                }
            )
            continue

        if event.event_id in seen_in_batch or db.get(EventRecord, event.event_id):
            duplicates += 1
            seen_in_batch.add(event.event_id)
            continue

        db.add(record_from_event(event))
        seen_in_batch.add(event.event_id)
        accepted += 1

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        accepted = 0
        duplicates = 0
        for raw_event in raw_events:
            try:
                normalized_event = normalize_raw_event(raw_event)
            except (TypeError, ValueError):
                continue
            try:
                event = StoreEvent.model_validate(normalized_event)
            except ValidationError:
                continue
            if db.get(EventRecord, event.event_id):
                duplicates += 1
                continue
            db.add(record_from_event(event))
            accepted += 1
            db.commit()

    return IngestResult(
        received=len(raw_events),
        accepted=accepted,
        duplicates=duplicates,
        errors=errors,
        partial_success=bool(errors and (accepted or duplicates)),
    )


@router.post("/events/ingest", response_model=IngestResult)
async def ingest_events(request: Request, db: Session = Depends(get_session)) -> IngestResult:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_JSON", "message": "Request body must be valid JSON."},
        ) from exc

    raw_events = _payload_to_events(payload)
    request.state.event_count = len(raw_events)
    if len(raw_events) > 500:
        raise HTTPException(
            status_code=422,
            detail={"code": "BATCH_TOO_LARGE", "message": "At most 500 events can be ingested per request."},
        )
    return ingest_batch(db, raw_events)
