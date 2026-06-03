from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.models import EventType, StoreEvent
from app.pos import parse_timestamp
from app.store_config import load_layout
from pipeline.tracker import StoreTracker, default_zones_for_camera, normalize_zones, zone_for_point


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
GENERIC_CAMERA_MAP = {
    1: "CAM_FLOOR_01",
    2: "CAM_FLOOR_02",
    3: "CAM_ENTRY_01",
    4: "CAM_STOCK_01",
    5: "CAM_BILLING_01",
}
RESOURCE_STORE_MAP = {
    "STORE 1": "ST1008",
    "STORE_1": "ST1008",
    "STORE-1": "ST1008",
    "STORE 2": "ST1076",
    "STORE_2": "ST1076",
    "STORE-2": "ST1076",
}
BILLING_ZONE_HINTS = ("BILLING", "CHECKOUT", "POS", "CASH", "COUNTER", "QUEUE")


def infer_store_id(path: Path) -> str:
    for part in reversed(path.parts):
        upper = part.upper()
        if upper in RESOURCE_STORE_MAP:
            return RESOURCE_STORE_MAP[upper]
        if upper.startswith("STORE_"):
            return upper.split(".")[0]
    return "STORE_BLR_002"


def infer_camera_id(path: Path) -> str:
    stem = path.stem.upper()
    if "ENTRY" in stem:
        return "CAM_ENTRY_01"
    if "BILL" in stem or "CHECKOUT" in stem:
        return "CAM_BILLING_01"
    if "FLOOR" in stem or "MAIN" in stem or "ZONE" in stem:
        return "CAM_FLOOR_01"
    generic = re.search(r"\bCAM[\s_-]*(\d+)\b", stem)
    if generic:
        mapped = GENERIC_CAMERA_MAP.get(int(generic.group(1)))
        if mapped:
            return mapped
    normalized = re.sub(r"[^A-Z0-9]+", "_", stem).strip("_") or "UNKNOWN"
    return f"CAM_{normalized[:32]}"


def is_billing_zone(zone_id: str | None, sku_zone: str | None = None) -> bool:
    text = f"{zone_id or ''} {sku_zone or ''}".upper()
    return any(hint in text for hint in BILLING_ZONE_HINTS)


def is_entry_camera(camera_id: str) -> bool:
    return "ENTRY" in camera_id.upper()


def is_staff_camera(camera_id: str) -> bool:
    camera = camera_id.upper()
    return "STOCK" in camera or "BACK" in camera


def entry_threshold_crossing(previous_x: float | None, current_x: float, frame_width: int) -> EventType | None:
    threshold_x = frame_width * 0.58
    if previous_x is None:
        return EventType.ENTRY if current_x <= threshold_x else None
    if previous_x > threshold_x >= current_x:
        return EventType.ENTRY
    if previous_x <= threshold_x < current_x:
        return EventType.EXIT
    return None


def write_event(handle, **payload) -> None:
    event = StoreEvent.model_validate(payload)
    handle.write(json.dumps(event.model_dump(mode="json"), separators=(",", ":")) + "\n")


def copy_sample_events(input_dir: Path, output_path: Path) -> bool:
    sample = input_dir / "sample_events.jsonl"
    if not sample.exists():
        matches = list(input_dir.rglob("sample_events.jsonl"))
        sample = matches[0] if matches else sample
    if sample.exists():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sample, output_path)
        return True
    return False


def video_fps(cv2_module, video: Path) -> float:
    capture = cv2_module.VideoCapture(str(video))
    try:
        fps = float(capture.get(cv2_module.CAP_PROP_FPS) or 0.0)
        return fps if fps > 0 else 15.0
    finally:
        capture.release()


def process_videos(
    input_dir: Path,
    output_path: Path,
    layout_path: Path | None,
    start_time: datetime,
    frame_stride: int = 1,
    max_seconds: float | None = None,
) -> int:
    try:
        import cv2
        from ultralytics import YOLO
    except Exception as exc:
        raise RuntimeError(
            "Video processing requires opencv-python-headless and ultralytics. "
            "Install requirements-cv.txt or use replay mode with sample_events.jsonl."
        ) from exc

    videos = [path for path in input_dir.rglob("*") if path.suffix.lower() in VIDEO_EXTENSIONS]
    if not videos:
        raise RuntimeError(f"No video clips found under {input_dir}")

    layout = load_layout(str(layout_path)) if layout_path else {}
    model = YOLO("yolov8n.pt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    emitted = 0

    with output_path.open("w", encoding="utf-8") as handle:
        for video in videos:
            store_id = infer_store_id(video)
            camera_id = infer_camera_id(video)
            tracker = StoreTracker(store_id=store_id, camera_id=camera_id)
            fps = video_fps(cv2, video)
            zones = normalize_zones(layout, store_id) or default_zones_for_camera(camera_id)
            frame_index = 0
            active_billing_visitors: set[str] = set()

            for result in model.track(
                source=str(video),
                classes=[0],
                stream=True,
                persist=False,
                verbose=False,
                conf=0.25,
                vid_stride=max(frame_stride, 1),
            ):
                if max_seconds is not None and frame_index / fps > max_seconds:
                    break
                boxes = getattr(result, "boxes", None)
                if boxes is None or boxes.id is None:
                    frame_index += max(frame_stride, 1)
                    continue
                frame_height, frame_width = getattr(result, "orig_shape", (1080, 1920))[:2]
                timestamp = start_time + timedelta(seconds=frame_index / fps)
                xyxy = boxes.xyxy.cpu().tolist()
                ids = boxes.id.int().cpu().tolist()
                confs = boxes.conf.cpu().tolist()

                for box, track_id, confidence in zip(xyxy, ids, confs):
                    state = tracker.visitor_for_track(int(track_id), timestamp)
                    state.session_seq += 1
                    left, top, right, bottom = box
                    centroid = ((left + right) / 2, (top + bottom) / 2)
                    zone = zone_for_point(centroid, zones)
                    is_staff = is_staff_camera(camera_id)

                    if is_entry_camera(camera_id):
                        entry_or_exit = entry_threshold_crossing(
                            state.last_centroid[0] if state.last_centroid else None,
                            centroid[0],
                            frame_width,
                        )
                    else:
                        entry_or_exit = None

                    if entry_or_exit == EventType.ENTRY and not state.emitted_entry:
                        write_event(
                            handle,
                            event_id=str(uuid4()),
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=state.visitor_id,
                            event_type=EventType.ENTRY,
                            timestamp=timestamp,
                            zone_id=None,
                            dwell_ms=0,
                            is_staff=is_staff,
                            confidence=float(confidence),
                            metadata={"session_seq": state.session_seq},
                        )
                        state.emitted_entry = True
                        state.emitted_exit = False
                        emitted += 1
                    elif entry_or_exit == EventType.ENTRY and state.emitted_exit:
                        write_event(
                            handle,
                            event_id=str(uuid4()),
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=state.visitor_id,
                            event_type=EventType.REENTRY,
                            timestamp=timestamp,
                            zone_id=None,
                            dwell_ms=0,
                            is_staff=is_staff,
                            confidence=float(confidence),
                            metadata={"session_seq": state.session_seq},
                        )
                        state.emitted_exit = False
                        emitted += 1
                    elif entry_or_exit == EventType.EXIT and state.emitted_entry and not state.emitted_exit:
                        write_event(
                            handle,
                            event_id=str(uuid4()),
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=state.visitor_id,
                            event_type=EventType.EXIT,
                            timestamp=timestamp,
                            zone_id=None,
                            dwell_ms=0,
                            is_staff=is_staff,
                            confidence=float(confidence),
                            metadata={"session_seq": state.session_seq},
                        )
                        state.emitted_exit = True
                        emitted += 1

                    if zone and zone.zone_id != state.current_zone:
                        if state.current_zone:
                            dwell_ms = int((timestamp - (state.zone_entered_at or timestamp)).total_seconds() * 1000)
                            write_event(
                                handle,
                                event_id=str(uuid4()),
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=state.visitor_id,
                                event_type=EventType.ZONE_EXIT,
                                timestamp=timestamp,
                                zone_id=state.current_zone,
                                dwell_ms=max(dwell_ms, 0),
                                is_staff=is_staff,
                                confidence=float(confidence),
                                metadata={"session_seq": state.session_seq},
                            )
                            emitted += 1
                            if state.in_billing_queue and is_billing_zone(state.current_zone):
                                active_billing_visitors.discard(state.visitor_id)
                                state.in_billing_queue = False
                        write_event(
                            handle,
                            event_id=str(uuid4()),
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=state.visitor_id,
                            event_type=EventType.ZONE_ENTER,
                            timestamp=timestamp,
                            zone_id=zone.zone_id,
                            dwell_ms=0,
                            is_staff=is_staff,
                            confidence=float(confidence),
                            metadata={"sku_zone": zone.sku_zone, "session_seq": state.session_seq},
                        )
                        state.current_zone = zone.zone_id
                        state.zone_entered_at = timestamp
                        state.dwell_emitted_at = timestamp
                        emitted += 1
                        if is_billing_zone(zone.zone_id, zone.sku_zone) and not state.in_billing_queue:
                            active_billing_visitors.add(state.visitor_id)
                            state.in_billing_queue = True
                            write_event(
                                handle,
                                event_id=str(uuid4()),
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=state.visitor_id,
                                event_type=EventType.BILLING_QUEUE_JOIN,
                                timestamp=timestamp,
                                zone_id=zone.zone_id,
                                dwell_ms=0,
                                is_staff=is_staff,
                                confidence=float(confidence),
                                metadata={
                                    "queue_depth": len(active_billing_visitors),
                                    "sku_zone": zone.sku_zone,
                                    "session_seq": state.session_seq,
                                },
                            )
                            emitted += 1

                    if zone and state.zone_entered_at and timestamp - state.zone_entered_at >= timedelta(seconds=30):
                        if not state.dwell_emitted_at or timestamp - state.dwell_emitted_at >= timedelta(seconds=30):
                            dwell_ms = int((timestamp - state.zone_entered_at).total_seconds() * 1000)
                            write_event(
                                handle,
                                event_id=str(uuid4()),
                                store_id=store_id,
                                camera_id=camera_id,
                                visitor_id=state.visitor_id,
                                event_type=EventType.ZONE_DWELL,
                                timestamp=timestamp,
                                zone_id=zone.zone_id,
                                dwell_ms=dwell_ms,
                                is_staff=is_staff,
                                confidence=float(confidence),
                                metadata={"sku_zone": zone.sku_zone, "session_seq": state.session_seq},
                            )
                            state.dwell_emitted_at = timestamp
                            emitted += 1
                    state.last_centroid = centroid
                frame_index += max(frame_stride, 1)
    return emitted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Store Intelligence events from raw CCTV clips.")
    parser.add_argument("--input", default="data/raw", help="Dataset directory containing clips and metadata.")
    parser.add_argument("--output", default="data/events/events.jsonl", help="Output JSONL event path.")
    parser.add_argument("--layout", default=None, help="Optional store_layout.json path.")
    parser.add_argument("--start-time", default="2026-03-03T14:00:00Z", help="Clip start timestamp used for frame offsets.")
    parser.add_argument("--prefer-sample", action="store_true", help="Copy sample_events.jsonl if present instead of CV processing.")
    parser.add_argument("--frame-stride", type=int, default=1, help="Process every Nth frame. Use 5-10 for quick demos.")
    parser.add_argument("--max-seconds", type=float, default=None, help="Optional seconds per clip to process for smoke tests.")
    args = parser.parse_args(argv)

    input_dir = Path(args.input)
    output_path = Path(args.output)
    if args.prefer_sample and copy_sample_events(input_dir, output_path):
        print(f"Copied sample events to {output_path}")
        return 0
    if not input_dir.exists():
        print(f"Input directory does not exist: {input_dir}", file=sys.stderr)
        return 2
    if copy_sample_events(input_dir, output_path) and not any(input_dir.rglob("*.mp4")):
        print(f"No clips found; copied sample events to {output_path}")
        return 0

    layout_path = Path(args.layout) if args.layout else input_dir / "store_layout.json"
    start_time = parse_timestamp(args.start_time)
    emitted = process_videos(
        input_dir,
        output_path,
        layout_path if layout_path.exists() else None,
        start_time,
        frame_stride=max(args.frame_stride, 1),
        max_seconds=args.max_seconds,
    )
    print(json.dumps({"output": str(output_path), "events_emitted": emitted}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
