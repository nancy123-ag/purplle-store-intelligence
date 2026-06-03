# PROMPT: Build reusable tests for a FastAPI + SQLite Store Intelligence API that can validate ingestion and analytics without the official video dataset.
# CHANGES MADE: Kept the fixtures deterministic, isolated every test in a temporary SQLite database, and generated challenge-shaped events by helper instead of copying production fixtures.

from __future__ import annotations

import csv
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import create_app


@pytest.fixture()
def app_factory(tmp_path):
    @contextmanager
    def _make(pos_rows=None, layout=None):
        root = tmp_path / str(uuid4())
        root.mkdir()
        pos_path = root / "pos_transactions.csv"
        layout_path = root / "store_layout.json"

        rows = pos_rows or []
        with pos_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["store_id", "transaction_id", "timestamp", "basket_value_inr"],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        with layout_path.open("w", encoding="utf-8") as handle:
            json.dump(
                layout
                or {
                    "stores": [
                        {
                            "store_id": "STORE_BLR_002",
                            "zones": [
                                {"zone_id": "SKINCARE", "name": "Skincare"},
                                {"zone_id": "MAKEUP", "name": "Makeup"},
                                {"zone_id": "BILLING", "name": "Billing"},
                            ],
                        }
                    ]
                },
                handle,
            )

        app = create_app(
            database_url=f"sqlite:///{root / 'test.db'}",
            pos_path=str(pos_path),
            layout_path=str(layout_path),
        )
        with TestClient(app) as client:
            yield client, app

    return _make


def sample_event(**overrides):
    payload = {
        "event_id": str(uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_001",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.91,
        "metadata": {"session_seq": 1, "sku_zone": None, "queue_depth": None},
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def post_events():
    def _post(client, events):
        response = client.post("/events/ingest", json={"events": events})
        assert response.status_code == 200, response.text
        return response.json()

    return _post
