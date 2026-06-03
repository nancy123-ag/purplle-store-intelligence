# PROMPT: Add anomaly tests for queue spikes, dead zones, and conversion drops compared with recent baseline behavior.
# CHANGES MADE: Created compact synthetic event histories that prove each anomaly path without relying on hidden challenge videos.

from __future__ import annotations

from tests.conftest import sample_event


def anomaly_types(payload):
    return {item["type"]: item for item in payload["anomalies"]}


def test_anomalies_detect_queue_spike(app_factory, post_events):
    with app_factory() as (client, _app):
        post_events(
            client,
            [
                sample_event(
                    event_type="BILLING_QUEUE_JOIN",
                    timestamp="2026-03-03T14:10:00Z",
                    zone_id="BILLING",
                    metadata={"queue_depth": 9},
                )
            ],
        )

        anomalies = anomaly_types(client.get("/stores/STORE_BLR_002/anomalies").json())
        assert anomalies["BILLING_QUEUE_SPIKE"]["severity"] == "CRITICAL"


def test_anomalies_detect_dead_zone_from_layout(app_factory, post_events):
    with app_factory() as (client, _app):
        post_events(
            client,
            [
                sample_event(
                    event_type="ZONE_ENTER",
                    timestamp="2026-03-03T14:35:00Z",
                    zone_id="SKINCARE",
                )
            ],
        )

        payload = client.get("/stores/STORE_BLR_002/anomalies").json()
        dead_zones = {item["zone_id"] for item in payload["anomalies"] if item["type"] == "DEAD_ZONE"}
        assert "MAKEUP" in dead_zones


def test_anomalies_detect_conversion_drop_against_7_day_average(app_factory, post_events):
    pos_rows = []
    events = []
    for day in range(1, 8):
        visitor = f"VIS_PRIOR_{day}"
        date = f"2026-03-0{day}"
        pos_rows.append(
            {
                "store_id": "STORE_BLR_002",
                "transaction_id": f"TXN_{day}",
                "timestamp": f"{date}T14:05:00Z",
                "basket_value_inr": "500.00",
            }
        )
        events.extend(
            [
                sample_event(visitor_id=visitor, timestamp=f"{date}T14:00:00Z"),
                sample_event(
                    visitor_id=visitor,
                    event_type="BILLING_QUEUE_JOIN",
                    timestamp=f"{date}T14:04:00Z",
                    zone_id="BILLING",
                    metadata={"queue_depth": 1},
                ),
            ]
        )
    events.append(sample_event(visitor_id="VIS_CURRENT", timestamp="2026-03-08T14:00:00Z"))

    with app_factory(pos_rows=pos_rows) as (client, _app):
        post_events(client, events)

        anomalies = anomaly_types(client.get("/stores/STORE_BLR_002/anomalies").json())
        assert anomalies["CONVERSION_DROP"]["severity"] in {"WARN", "CRITICAL"}
        assert anomalies["CONVERSION_DROP"]["baseline_7_day_avg"] == 1.0

