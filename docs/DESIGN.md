# Design

This project is split into two deliberately separate parts: a detection pipeline that emits structured events, and a production-oriented API that treats those events as the source of truth. That separation is important for the challenge because the official clips are not always available during development, while the API still needs deterministic tests, replay, and scoring-harness compatibility.

The API is a FastAPI service backed by SQLite through SQLAlchemy. SQLite is enough for the take-home scale, keeps `docker compose up` simple, and is explicitly allowed by the FAQ. The database stores events idempotently by `event_id` and keeps POS transactions in a separate table. POS data is loaded at startup from `data/raw/pos_transactions.csv` when present. Store layout data is loaded from `data/raw/store_layout.json`; the code accepts common shapes such as top-level `stores`, keyed store dictionaries, or direct zone lists.

Ingestion accepts either a raw JSON array or `{ "events": [...] }`, validates every event with Pydantic, and returns accepted, duplicate, and per-record validation error counts. This means one malformed event does not poison the whole batch. The API returns structured error bodies for bad requests and database failures and avoids leaking stack traces. Request logging is implemented as middleware and records `trace_id`, `store_id`, endpoint, latency, event count, and status code.

Metrics are computed from the latest event day for the store, rather than the machine clock. This makes the API work against historical challenge clips while still behaving like a real-time system as new events arrive. Conversion rate follows the statement: a visitor with a billing-zone event in the five minutes before a POS transaction counts as converted. Staff events are excluded from visitor, dwell, funnel, and conversion calculations.

The detection path is pragmatic. If `sample_events.jsonl` is present, replay mode gives a deterministic end-to-end demo. With video clips, the pipeline uses YOLOv8 person tracking and maps track centroids into configured zones. It emits entries, zone transitions, and recurring dwell events. The pipeline keeps confidence values, uses stable visitor tokens per track, and leaves room for improving staff classification and cross-camera re-identification once the official footage is available.

The first sample ZIP available during implementation only contained five generic MP4 files named `CAM 1.mp4` through `CAM 5.mp4`; it did not include the promised layout, POS, sample events, or assertion files. The June 3 Resource Center update added Store 1 and Store 2 ZIPs, layout PNGs, sample POS, and sample events, but those sample events use operational field names such as `id_token`, `store_code`, `event_timestamp`, `zone_entered`, and `queue_completed` rather than the canonical event schema in the PDF. To keep the submission runnable against both the statement and the real attachments, ingestion normalizes the Resource Center samples into the canonical schema before validation and storage.

The detection pipeline has a fallback camera map and fallback zones. `CAM 3` and `entry *.mp4` are treated as entry threshold cameras, `CAM 5` and `billing_area.mp4` as billing, `CAM 4` as stock/back-room staff movement, and `CAM 1`/`CAM 2`/`zone.mp4` as floor coverage. Store 1 maps to `ST1008`, and Store 2 maps to `ST1076`, matching the Resource Center sample POS/events. When a proper `store_layout.json` is present, that file overrides the fallback regions. This is not as strong as calibrated homography and re-identification, but it means the raw clips still produce challenge-shaped events instead of an empty file.

## AI-Assisted Decisions

AI shaped three areas of the design. First, it helped convert the PDF problem statement into a concrete acceptance checklist: required endpoints, event schema, edge cases, and documentation requirements. I kept the checklist but made the implementation smaller and more testable than a full production CV system because the dataset was not present yet.

Second, AI suggested prioritising the analytics API before tuning detection. I agreed because the scoring gate requires `docker compose up`, ingest, metrics, docs, and tests before detection quality is evaluated. That choice also makes replay mode possible.

Third, AI suggested PostgreSQL as a production-like option. I overrode that and chose SQLite because the challenge FAQ accepts it, the project has no existing infrastructure, and avoiding a second service makes the submission easier to run on a clean machine.
