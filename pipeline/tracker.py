from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Zone:
    zone_id: str
    polygon: list[tuple[float, float]] | None = None
    rect: tuple[float, float, float, float] | None = None
    sku_zone: str | None = None


@dataclass
class TrackState:
    track_id: int
    visitor_id: str
    first_seen: datetime
    last_seen: datetime
    last_centroid: tuple[float, float] | None = None
    current_zone: str | None = None
    zone_entered_at: datetime | None = None
    dwell_emitted_at: datetime | None = None
    session_seq: int = 0
    emitted_entry: bool = False
    emitted_exit: bool = False
    in_billing_queue: bool = False


@dataclass
class StoreTracker:
    store_id: str
    camera_id: str
    tracks: dict[int, TrackState] = field(default_factory=dict)

    def visitor_for_track(self, track_id: int, timestamp: datetime) -> TrackState:
        if track_id not in self.tracks:
            self.tracks[track_id] = TrackState(
                track_id=track_id,
                visitor_id=f"VIS_{self.store_id}_{track_id:06d}",
                first_seen=timestamp,
                last_seen=timestamp,
            )
        state = self.tracks[track_id]
        state.last_seen = timestamp
        return state


def point_in_rect(point: tuple[float, float], rect: tuple[float, float, float, float]) -> bool:
    x, y = point
    left, top, right, bottom = rect
    return left <= x <= right and top <= y <= bottom


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def normalize_zones(layout: dict[str, Any], store_id: str) -> list[Zone]:
    from app.store_config import extract_zones

    zones = []
    for zone in extract_zones(layout, store_id):
        zone_id = str(zone["zone_id"])
        rect = None
        polygon = None
        if "rect" in zone and isinstance(zone["rect"], list) and len(zone["rect"]) == 4:
            left, top, width, height = [float(value) for value in zone["rect"]]
            rect = (left, top, left + width, top + height)
        elif all(key in zone for key in ("x1", "y1", "x2", "y2")):
            rect = (float(zone["x1"]), float(zone["y1"]), float(zone["x2"]), float(zone["y2"]))
        if "polygon" in zone and isinstance(zone["polygon"], list):
            polygon = [(float(pair[0]), float(pair[1])) for pair in zone["polygon"] if len(pair) == 2]
        zones.append(Zone(zone_id=zone_id, rect=rect, polygon=polygon, sku_zone=zone.get("sku_zone") or zone.get("name")))
    return zones


def default_zones_for_camera(camera_id: str, width: int = 1920, height: int = 1080) -> list[Zone]:
    camera = camera_id.upper()
    full_frame = (0.0, 0.0, float(width), float(height))
    if "BILLING" in camera:
        return [Zone(zone_id="BILLING", rect=full_frame, sku_zone="BILLING")]
    if "STOCK" in camera or "BACK" in camera:
        return [Zone(zone_id="STOCKROOM", rect=full_frame, sku_zone="STOCKROOM")]
    if "ENTRY" in camera:
        return [Zone(zone_id="ENTRY_THRESHOLD", rect=full_frame, sku_zone="ENTRY")]
    if "FLOOR_02" in camera:
        return [
            Zone(zone_id="MAKEUP", rect=(0.0, 0.0, width * 0.65, float(height)), sku_zone="MAKEUP"),
            Zone(zone_id="HAIRCARE", rect=(width * 0.65, 0.0, float(width), float(height)), sku_zone="HAIRCARE"),
        ]
    if "FLOOR" in camera:
        return [
            Zone(zone_id="PROMO_ISLAND", rect=(width * 0.32, height * 0.48, width * 0.72, float(height)), sku_zone="PROMO"),
            Zone(zone_id="SKINCARE", rect=(0.0, 0.0, width * 0.7, float(height)), sku_zone="SKINCARE"),
            Zone(zone_id="MAKEUP", rect=(width * 0.7, 0.0, float(width), float(height)), sku_zone="MAKEUP"),
        ]
    return []


def zone_for_point(point: tuple[float, float], zones: list[Zone]) -> Zone | None:
    for zone in zones:
        if zone.polygon and point_in_polygon(point, zone.polygon):
            return zone
        if zone.rect and point_in_rect(point, zone.rect):
            return zone
    return None
