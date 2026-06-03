# PROMPT: Generate API tests for event ingestion validation, malformed records, idempotency, and batch limits in the Store Intelligence challenge.
# CHANGES MADE: Added partial-success assertions, duplicate-event replay, structured error checks, and a 500-event boundary test aligned with the problem statement.

from __future__ import annotations

from tests.conftest import sample_event


def test_ingest_accepts_partial_batch_and_is_idempotent(app_factory):
    with app_factory() as (client, _app):
        valid = sample_event()
        invalid = {"event_id": "bad-event", "store_id": "STORE_BLR_002"}

        response = client.post("/events/ingest", json={"events": [valid, invalid]})

        assert response.status_code == 200
        body = response.json()
        assert body["received"] == 2
        assert body["accepted"] == 1
        assert body["duplicates"] == 0
        assert body["partial_success"] is True
        assert body["errors"][0]["index"] == 1

        replay = client.post("/events/ingest", json={"events": [valid]}).json()
        assert replay["accepted"] == 0
        assert replay["duplicates"] == 1


def test_ingest_accepts_raw_array_payload(app_factory):
    with app_factory() as (client, _app):
        response = client.post("/events/ingest", json=[sample_event()])

        assert response.status_code == 200
        assert response.json()["accepted"] == 1


def test_ingest_rejects_malformed_container_with_structured_error(app_factory):
    with app_factory() as (client, _app):
        response = client.post("/events/ingest", json={"not_events": []})

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "BAD_REQUEST"
        assert "Traceback" not in response.text


def test_ingest_rejects_batches_over_500(app_factory):
    with app_factory() as (client, _app):
        events = [sample_event(visitor_id=f"VIS_{index:03d}") for index in range(501)]

        response = client.post("/events/ingest", json={"events": events})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "BATCH_TOO_LARGE"


def test_ingest_accepts_resource_center_event_shape(app_factory):
    resource_events = [
        {
            "event_type": "entry",
            "id_token": "ID_60001",
            "store_code": "store_1076",
            "camera_id": "cam1",
            "event_timestamp": "2026-03-08T18:10:05.120000",
            "is_staff": False,
            "gender_pred": "F",
            "age_pred": 28,
            "age_bucket": "25-34",
        },
        {
            "queue_event_id": "a1e5c1d3-9e14-4df1-bd2c-4ab5cbf55f91",
            "event_type": "queue_abandoned",
            "track_id": 101,
            "store_id": "ST1076",
            "camera_id": "PURPLLE_MUM_1076_CAM6",
            "zone_id": "PURPLLE_MUM_1076_Z_BILLING_01",
            "zone_name": "Billing Counter Queue",
            "zone_type": "BILLING",
            "queue_join_ts": "2026-03-08T18:12:58.240000",
            "queue_exit_ts": "2026-03-08T18:14:02.880000",
            "wait_seconds": 65,
            "queue_position_at_join": 4,
            "abandoned": True,
        },
    ]

    with app_factory() as (client, _app):
        result = client.post("/events/ingest", json={"events": resource_events}).json()

        assert result["accepted"] == 2
        metrics = client.get("/stores/ST1076/metrics").json()
        assert metrics["unique_visitors"] == 2
        assert metrics["queue_depth"] == 4
        assert metrics["billing_queue_abandonment_rate"] == 1.0


def test_resource_center_string_booleans_do_not_mark_everyone_staff(app_factory):
    events = [
        {
            "event_type": "entry",
            "id_token": "ID_CUSTOMER",
            "store_code": "store_1076",
            "camera_id": "cam1",
            "event_timestamp": "2026-03-08T18:10:05.120000",
            "is_staff": "false",
        },
        {
            "event_type": "entry",
            "id_token": "ID_STAFF",
            "store_code": "store_1076",
            "camera_id": "cam1",
            "event_timestamp": "2026-03-08T18:11:05.120000",
            "is_staff": "true",
        },
    ]

    with app_factory() as (client, _app):
        result = client.post("/events/ingest", json={"events": events}).json()

        assert result["accepted"] == 2
        assert client.get("/stores/ST1076/metrics").json()["unique_visitors"] == 1


def test_resource_center_bad_numeric_fields_are_partial_errors(app_factory):
    valid = {
        "event_type": "entry",
        "id_token": "ID_60001",
        "store_code": "store_1076",
        "camera_id": "cam1",
        "event_timestamp": "2026-03-08T18:10:05.120000",
        "is_staff": False,
    }
    invalid = {
        "event_type": "queue_abandoned",
        "track_id": 101,
        "store_id": "ST1076",
        "camera_id": "CAM6",
        "zone_id": "BILLING",
        "queue_exit_ts": "2026-03-08T18:14:02.880000",
        "wait_seconds": "not-a-number",
        "is_staff": False,
    }

    with app_factory() as (client, _app):
        result = client.post("/events/ingest", json={"events": [valid, invalid]}).json()

        assert result["accepted"] == 1
        assert result["partial_success"] is True
        assert result["errors"][0]["code"] == "NORMALIZATION_ERROR"
