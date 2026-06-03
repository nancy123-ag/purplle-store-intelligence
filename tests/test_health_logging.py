# PROMPT: Test production readiness behavior for health checks, stale feed warnings, structured DB errors, and request logging fields.
# CHANGES MADE: Used dependency override to simulate database failure safely and caplog to inspect JSON request logs.

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.database import get_session
from app.main import create_app
from tests.conftest import sample_event


def test_health_reports_stale_feed(app_factory, post_events):
    with app_factory() as (client, _app):
        post_events(client, [sample_event(timestamp="2020-01-01T00:00:00Z")])

        payload = client.get("/health").json()
        assert payload["status"] == "DEGRADED"
        assert payload["feeds"][0]["status"] == "STALE_FEED"


def test_database_unavailable_returns_structured_503(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'test.db'}", pos_path=str(tmp_path / "missing.csv"))

    def broken_session():
        raise OperationalError("SELECT 1", {}, Exception("db down"))
        yield

    app.dependency_overrides[get_session] = broken_session
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "Traceback" not in response.text


def test_request_logging_includes_required_fields(app_factory, caplog):
    caplog.set_level(logging.INFO, logger="store_intelligence.requests")
    with app_factory() as (client, _app):
        response = client.get("/stores/STORE_BLR_002/metrics", headers={"x-trace-id": "trace-test"})

    assert response.headers["x-trace-id"] == "trace-test"
    records = [json.loads(record.message) for record in caplog.records if record.name == "store_intelligence.requests"]
    assert records
    latest = records[-1]
    assert latest["trace_id"] == "trace-test"
    assert latest["store_id"] == "STORE_BLR_002"
    assert latest["endpoint"] == "/stores/STORE_BLR_002/metrics"
    assert latest["status_code"] == 200
    assert "latency_ms" in latest

