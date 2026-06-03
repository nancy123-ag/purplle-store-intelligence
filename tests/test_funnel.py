# PROMPT: Build funnel tests that verify session-level counting, re-entry deduplication, staff exclusion, and purchase correlation.
# CHANGES MADE: Asserted the stage counts directly instead of only checking response shape, because re-entry inflation is a named challenge edge case.

from __future__ import annotations

from tests.conftest import sample_event


def stage_counts(payload):
    return {stage["stage"]: stage["count"] for stage in payload["stages"]}


def test_funnel_deduplicates_reentry_and_counts_purchase(app_factory, post_events):
    pos_rows = [
        {
            "store_id": "STORE_BLR_002",
            "transaction_id": "TXN_2",
            "timestamp": "2026-03-03T14:05:00Z",
            "basket_value_inr": "1200.00",
        }
    ]
    with app_factory(pos_rows=pos_rows) as (client, _app):
        post_events(
            client,
            [
                sample_event(visitor_id="VIS_A", timestamp="2026-03-03T14:00:00Z"),
                sample_event(visitor_id="VIS_A", event_type="REENTRY", timestamp="2026-03-03T14:01:00Z"),
                sample_event(
                    visitor_id="VIS_A",
                    event_type="ZONE_ENTER",
                    timestamp="2026-03-03T14:02:00Z",
                    zone_id="SKINCARE",
                ),
                sample_event(
                    visitor_id="VIS_A",
                    event_type="BILLING_QUEUE_JOIN",
                    timestamp="2026-03-03T14:04:00Z",
                    zone_id="BILLING",
                    metadata={"queue_depth": 1},
                ),
            ],
        )

        funnel = client.get("/stores/STORE_BLR_002/funnel").json()
        counts = stage_counts(funnel)
        assert counts == {"ENTRY": 1, "ZONE_VISIT": 1, "BILLING_QUEUE": 1, "PURCHASE": 1}
        assert funnel["unit"] == "session"
        assert funnel["reentries_deduplicated"] is True


def test_funnel_excludes_staff_from_all_stages(app_factory, post_events):
    with app_factory() as (client, _app):
        post_events(
            client,
            [
                sample_event(visitor_id="STAFF_A", is_staff=True),
                sample_event(
                    visitor_id="STAFF_A",
                    is_staff=True,
                    event_type="ZONE_ENTER",
                    zone_id="BILLING",
                    timestamp="2026-03-03T14:02:00Z",
                ),
            ],
        )

        counts = stage_counts(client.get("/stores/STORE_BLR_002/funnel").json())
        assert counts == {"ENTRY": 0, "ZONE_VISIT": 0, "BILLING_QUEUE": 0, "PURCHASE": 0}

