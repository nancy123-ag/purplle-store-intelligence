# Choices

## 1. Detection Model

I chose YOLOv8 through `ultralytics` as the detector/tracker entry point when optional CV dependencies are installed. The alternative options were MediaPipe, RT-DETR, a custom OpenCV motion detector, or a VLM-driven frame classifier. YOLOv8 is the most practical first choice for this challenge because it has a mature person class, straightforward tracking support, and enough examples for retail CCTV-style footage. It also keeps the pipeline local and explainable. A VLM may help classify zones or staff uniforms later, but using one as the primary detector would be slower, harder to reproduce, and more expensive.

The AI suggestion was to start with YOLOv8 plus ByteTrack-style tracking, then add appearance embeddings only after the API and event contract were solid. I accepted that sequence. The current implementation is intentionally conservative. It emits confidence values and does not hide uncertain detections. Track IDs become visitor tokens inside each camera stream. Zone assignment is done by centroid-in-zone checks using `store_layout.json`.

The provided sample ZIP did not include layout metadata, so I added a fallback camera map for `CAM 1` through `CAM 5` and default zones for entry, floor, billing, and stock-room views. That will not solve every cross-camera re-identification case, but it gives a working baseline that can be evaluated and improved against the supplied clips. The next improvement would be adding appearance embeddings for cross-camera deduplication and a staff-uniform classifier.

## 2. Event Schema

The AI suggestion was to keep the top-level event schema strict and put optional detector-specific diagnostics in `metadata`. I kept that because the hidden tests are likely to validate exact field names while the detection layer still needs room for queue depth, SKU zone, session sequence, and model notes. The API rejects unknown top-level fields for canonical events, while the `metadata` object is allowed to carry extra keys.

After the June 3 Resource Center update, I added a compatibility adapter at ingestion rather than weakening the canonical Pydantic model. The actual sample file uses fields such as `id_token`, `store_code`, `event_timestamp`, `zone_entered`, `queue_completed`, and `queue_abandoned`. The adapter maps those rows into the same internal event contract and records the original meaning in metadata. This preserves strict API internals while making the project runnable against the official sample assets.

The schema includes low-confidence detections instead of filtering them out. This was a deliberate choice because the scoring text asks whether low-confidence detections are flagged rather than silently dropped or falsely elevated. Keeping confidence in every event lets the API, dashboard, and reviewer reason about uncertainty.

Visitor IDs are treated as visit-session tokens. Re-entry events do not create a new funnel visitor when the same visitor token is reused. Staff events are still stored, but all business metrics filter `is_staff=true`.

## 3. API And Storage

The AI suggestion for the API was a FastAPI service with PostgreSQL and precomputed rollups. I kept FastAPI but chose SQLite + SQLAlchemy for this take-home. FastAPI is a natural fit because Pydantic validation is already central to the event contract, and Python aligns with CV tooling. SQLite is not the most scalable production database, but it is reliable for the take-home, works in one container, and is accepted by the FAQ. SQLAlchemy keeps the code portable if the storage layer later moves to PostgreSQL.

The API computes metrics live from stored events instead of writing precomputed aggregates. For the challenge scale this is simpler, more transparent, and less likely to return stale data. If this were running at 40 stores continuously, I would add incremental rollups for hot endpoints while preserving raw events for audit and recomputation.

The ingestion endpoint returns partial success instead of failing the whole batch on one malformed record. That makes the system operationally safer for streaming pipelines where occasional bad detections should be visible but not block all analytics.
