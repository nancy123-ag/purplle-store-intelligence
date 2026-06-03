# PROMPT: Test the detection pipeline's deterministic replay path before official CCTV clips are available.
# CHANGES MADE: Exercised the run command's sample-events fallback, which keeps the repo demonstrable without downloading challenge assets.

from __future__ import annotations

import json
from pathlib import Path

from app.models import EventType
from pipeline.detect import entry_threshold_crossing, infer_camera_id, infer_store_id, is_billing_zone, main
from pipeline.tracker import default_zones_for_camera, zone_for_point
from tests.conftest import sample_event


def test_pipeline_prefer_sample_copies_jsonl(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sample_path = raw_dir / "sample_events.jsonl"
    event = sample_event()
    sample_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    output = tmp_path / "events" / "events.jsonl"

    exit_code = main(["--input", str(raw_dir), "--output", str(output), "--prefer-sample"])

    assert exit_code == 0
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8").strip())["event_id"] == event["event_id"]


def test_pipeline_maps_generic_challenge_camera_names():
    assert infer_camera_id(Path("CCTV Footage/CAM 1.mp4")) == "CAM_FLOOR_01"
    assert infer_camera_id(Path("CCTV Footage/CAM 3.mp4")) == "CAM_ENTRY_01"
    assert infer_camera_id(Path("CCTV Footage/CAM 5.mp4")) == "CAM_BILLING_01"
    assert infer_camera_id(Path("Store 2/entry 1.mp4")) == "CAM_ENTRY_01"
    assert infer_camera_id(Path("Store 2/billing_area.mp4")) == "CAM_BILLING_01"
    assert infer_camera_id(Path("Store 2/zone.mp4")) == "CAM_FLOOR_01"
    assert infer_camera_id(Path("front door.mp4")) == "CAM_FRONT_DOOR"


def test_pipeline_maps_resource_center_store_folders():
    assert infer_store_id(Path("data/raw/Store 1/CAM 1 - zone.mp4")) == "ST1008"
    assert infer_store_id(Path("data/raw/Store 2/entry 1.mp4")) == "ST1076"


def test_pipeline_fallback_zones_cover_metadata_free_clips():
    billing = default_zones_for_camera("CAM_BILLING_01")
    assert zone_for_point((100, 100), billing).zone_id == "BILLING"
    assert is_billing_zone("BILLING")

    floor = default_zones_for_camera("CAM_FLOOR_01")
    assert zone_for_point((1000, 900), floor).zone_id == "PROMO_ISLAND"


def test_entry_threshold_crossing_classifies_direction():
    assert entry_threshold_crossing(None, 100, 1920) == EventType.ENTRY
    assert entry_threshold_crossing(1500, 1000, 1920) == EventType.ENTRY
    assert entry_threshold_crossing(900, 1300, 1920) == EventType.EXIT
