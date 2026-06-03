from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_layout(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.exists():
        return {}
    with candidate.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def store_config(layout: dict[str, Any], store_id: str) -> dict[str, Any]:
    if not layout:
        return {}
    if store_id in layout and isinstance(layout[store_id], dict):
        return layout[store_id]
    stores = layout.get("stores")
    if isinstance(stores, list):
        for store in stores:
            if isinstance(store, dict) and store.get("store_id") == store_id:
                return store
    if isinstance(stores, dict) and isinstance(stores.get(store_id), dict):
        return stores[store_id]
    return layout


def extract_zones(layout: dict[str, Any], store_id: str) -> list[dict[str, Any]]:
    config = store_config(layout, store_id)
    zones = config.get("zones", [])
    if isinstance(zones, dict):
        return [{"zone_id": key, **(value if isinstance(value, dict) else {})} for key, value in zones.items()]
    if isinstance(zones, list):
        normalized = []
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            zone_id = zone.get("zone_id") or zone.get("id") or zone.get("name") or zone.get("zone_name")
            if zone_id:
                normalized.append({"zone_id": str(zone_id), **zone})
        return normalized
    return []


def known_zone_ids(layout: dict[str, Any], store_id: str) -> set[str]:
    return {zone["zone_id"] for zone in extract_zones(layout, store_id) if zone.get("zone_id")}

