# PROMPT: Write metrics tests for empty stores, all-staff traffic, zero purchases, conversion correlation, dwell, and queue depth.
# CHANGES MADE: Used POS time-window correlation and staff filtering explicitly so the tests match the challenge's north-star conversion metric.

from __future__ import annotations

from app.database import PosTransaction
from app.pos import load_pos_csv
from tests.conftest import sample_event


def test_metrics_handle_empty_store(app_factory):
    with app_factory() as (client, _app):
        response = client.get("/stores/STORE_BLR_002/metrics")

        assert response.status_code == 200
        assert response.json()["unique_visitors"] == 0
        assert response.json()["conversion_rate"] == 0.0
        assert response.json()["queue_depth"] == 0


def test_metrics_exclude_all_staff_events(app_factory, post_events):
    with app_factory() as (client, _app):
        post_events(
            client,
            [
                sample_event(visitor_id="STAFF_1", is_staff=True),
                sample_event(
                    visitor_id="STAFF_1",
                    is_staff=True,
                    event_type="ZONE_DWELL",
                    zone_id="SKINCARE",
                    dwell_ms=30000,
                ),
            ],
        )

        metrics = client.get("/stores/STORE_BLR_002/metrics").json()
        assert metrics["unique_visitors"] == 0
        assert metrics["avg_dwell_ms_per_zone"] == {}


def test_metrics_conversion_uses_billing_window_and_pos(app_factory, post_events):
    pos_rows = [
        {
            "store_id": "STORE_BLR_002",
            "transaction_id": "TXN_1",
            "timestamp": "2026-03-03T14:04:00Z",
            "basket_value_inr": "750.00",
        }
    ]
    with app_factory(pos_rows=pos_rows) as (client, _app):
        post_events(
            client,
            [
                sample_event(visitor_id="VIS_A", timestamp="2026-03-03T14:00:00Z"),
                sample_event(
                    visitor_id="VIS_A",
                    event_type="ZONE_ENTER",
                    camera_id="CAM_BILLING_01",
                    timestamp="2026-03-03T14:02:00Z",
                    zone_id="BILLING",
                    metadata={"sku_zone": "BILLING", "session_seq": 2},
                ),
            ],
        )

        metrics = client.get("/stores/STORE_BLR_002/metrics").json()
        assert metrics["unique_visitors"] == 1
        assert metrics["converted_visitors"] == 1
        assert metrics["conversion_rate"] == 1.0
        assert metrics["transactions"] == 1


def test_metrics_do_not_convert_queue_abandon_events(app_factory, post_events):
    pos_rows = [
        {
            "store_id": "STORE_BLR_002",
            "transaction_id": "TXN_ABANDON",
            "timestamp": "2026-03-03T14:05:00Z",
            "basket_value_inr": "750.00",
        }
    ]
    with app_factory(pos_rows=pos_rows) as (client, _app):
        post_events(
            client,
            [
                sample_event(visitor_id="VIS_A", timestamp="2026-03-03T14:00:00Z"),
                sample_event(
                    visitor_id="VIS_A",
                    event_type="BILLING_QUEUE_ABANDON",
                    camera_id="CAM_BILLING_01",
                    timestamp="2026-03-03T14:04:00Z",
                    zone_id="BILLING",
                    metadata={"queue_depth": 1},
                ),
            ],
        )

        metrics = client.get("/stores/STORE_BLR_002/metrics").json()
        assert metrics["converted_visitors"] == 0
        assert metrics["conversion_rate"] == 0.0


def test_metrics_zero_purchases_and_queue_dwell(app_factory, post_events):
    with app_factory() as (client, _app):
        post_events(
            client,
            [
                sample_event(visitor_id="VIS_A"),
                sample_event(
                    visitor_id="VIS_A",
                    event_type="ZONE_DWELL",
                    camera_id="CAM_FLOOR_01",
                    timestamp="2026-03-03T14:01:00Z",
                    zone_id="SKINCARE",
                    dwell_ms=45000,
                ),
                sample_event(
                    visitor_id="VIS_B",
                    event_type="BILLING_QUEUE_JOIN",
                    camera_id="CAM_BILLING_01",
                    timestamp="2026-03-03T14:02:00Z",
                    zone_id="BILLING",
                    metadata={"queue_depth": 4, "session_seq": 1},
                ),
            ],
        )

        metrics = client.get("/stores/STORE_BLR_002/metrics").json()
        assert metrics["conversion_rate"] == 0.0
        assert metrics["queue_depth"] == 4
        assert metrics["avg_dwell_ms_per_zone"]["SKINCARE"] == 45000


def test_metrics_queue_depth_uses_max_depth_at_latest_timestamp(app_factory, post_events):
    with app_factory() as (client, _app):
        post_events(
            client,
            [
                sample_event(
                    visitor_id="VIS_A",
                    event_type="BILLING_QUEUE_JOIN",
                    camera_id="CAM_BILLING_01",
                    timestamp="2026-03-03T14:02:00Z",
                    zone_id="BILLING",
                    metadata={"queue_depth": 2},
                ),
                sample_event(
                    visitor_id="VIS_B",
                    event_type="BILLING_QUEUE_JOIN",
                    camera_id="CAM_BILLING_01",
                    timestamp="2026-03-03T14:02:00Z",
                    zone_id="BILLING",
                    metadata={"queue_depth": 5},
                ),
            ],
        )

        assert client.get("/stores/STORE_BLR_002/metrics").json()["queue_depth"] == 5


def test_pos_loader_accepts_resource_center_order_columns(app_factory, tmp_path):
    pos_path = tmp_path / "pos.csv"
    pos_path.write_text(
        "order_id,order_date,order_time,store_id,product_id,brand_name,total_amount\n"
        "1,10-04-2026,12:15:05,ST1008,399945,Faces Canada,302.33\n",
        encoding="utf-8",
    )

    with app_factory() as (_client, _app):
        from app import database

        assert database.SessionLocal is not None
        with database.SessionLocal() as db:
            assert load_pos_csv(db, str(pos_path)) == 1
            transaction = db.get(PosTransaction, "1")
            assert transaction is not None
            assert transaction.store_id == "ST1008"
            assert transaction.basket_value_inr == 302.33
