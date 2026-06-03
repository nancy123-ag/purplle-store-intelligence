# PROMPT: Validate the heatmap endpoint for zone frequency, average dwell, normalization, and low-data confidence.
# CHANGES MADE: Kept the scenario small but checked both layout-defined empty zones and event-derived zone scores.

from __future__ import annotations

from tests.conftest import sample_event


def test_heatmap_includes_zone_scores_and_low_confidence(app_factory, post_events):
    with app_factory() as (client, _app):
        post_events(
            client,
            [
                sample_event(event_type="ZONE_ENTER", zone_id="SKINCARE", visitor_id="VIS_A"),
                sample_event(
                    event_type="ZONE_DWELL",
                    zone_id="SKINCARE",
                    visitor_id="VIS_A",
                    timestamp="2026-03-03T14:01:00Z",
                    dwell_ms=60000,
                ),
            ],
        )

        payload = client.get("/stores/STORE_BLR_002/heatmap").json()
        zones = {zone["zone_id"]: zone for zone in payload["zones"]}
        assert payload["data_confidence"] == "LOW"
        assert zones["SKINCARE"]["visit_frequency"] == 1
        assert zones["SKINCARE"]["avg_dwell_ms"] == 60000
        assert zones["SKINCARE"]["score"] == 100
        assert "MAKEUP" in zones

