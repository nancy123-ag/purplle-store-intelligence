# Store Intelligence API

Offline retail analytics pipeline for the Purplle/Apex Retail challenge. The project accepts raw CCTV-derived behavioural events, computes live store metrics, and exposes the required REST API surface.

## Setup In 5 Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

## Docker

```bash
docker compose up --build
```

This starts the API on port `8000` and stores SQLite data under `./data`. On Windows, start Docker Desktop first and make sure the Linux engine is running before executing the command.

## Submission Notes

The final June 3, 2026 challenge document asks for a private GitHub repository and a reviewer invite for `purplletechchallenge2026@hackerearth.com`. The repository should stay private because the CCTV footage license is challenge-use only and the clips must not be redistributed.

## Dataset Layout

Place the official challenge ZIP contents under:

```text
data/raw/
  sample_events.jsonl
  pos_transactions.csv
  store_layout.json
  assertions.py
  <store clip folders or video files>
```

The June 3 Resource Center assets use this shape:

```text
data/raw/resource_center/
  Store 1/
    Store 1 - layout.png
    CAM 1 - zone.mp4
    CAM 2 - zone.mp4
    CAM 3 - entry.mp4
    CAM 5 - billing.mp4
  Store 2/
    store 2 - layout.png
    entry 1.mp4
    entry 2.mp4
    zone.mp4
    billing_area.mp4
  sample_events.jsonl
  pos_transactions.csv
```

The original ZIP provided with this workspace only contained generic MP4 files:

```text
data/raw/CCTV Footage/
  CAM 1.mp4
  CAM 2.mp4
  CAM 3.mp4
  CAM 4.mp4
  CAM 5.mp4
```

The pipeline handles both metadata-free shapes by applying a built-in camera map: `CAM 1` and `CAM 2` are floor cameras, `CAM 3`/`entry *.mp4` are entry cameras, `CAM 4` is treated as stock/back-room staff movement, and `CAM 5`/`billing_area.mp4` are billing cameras. If `store_layout.json` is missing and only layout PNGs are available, fallback frame regions are used so the clips still produce zone and billing queue events. The Resource Center folders map to `ST1008` for Store 1 and `ST1076` for Store 2.

On Windows PowerShell, extract the provided ZIP with:

```powershell
New-Item -ItemType Directory -Force data/raw
tar -xf "$env:USERPROFILE\Downloads\CCTV Footage-20260529T160731Z-3-00144614ea.zip" -C data/raw
```

For the June 3 Resource Center ZIPs:

```powershell
New-Item -ItemType Directory -Force data/raw/resource_center
tar -xf "$env:USERPROFILE\Downloads\Store 1-20260602T101818Z-3-001ec38db8.zip" -C data/raw/resource_center
tar -xf "$env:USERPROFILE\Downloads\Store 2-20260602T101819Z-3-001099f208.zip" -C data/raw/resource_center
Copy-Item "$env:USERPROFILE\Downloads\sample_eventsbe42122.jsonl" data/raw/resource_center/sample_events.jsonl
Copy-Item "$env:USERPROFILE\Downloads\POS - sample transactionsb1e826f.csv" data/raw/resource_center/pos_transactions.csv
```

The API loads `data/raw/pos_transactions.csv` and `data/raw/store_layout.json` at startup when present. It also accepts the Resource Center POS columns (`order_id`, `order_date`, `order_time`, `total_amount`) and the Resource Center sample event shapes (`entry`, `zone_entered`, `queue_completed`, etc.) by normalising them into the canonical event schema during ingestion. If metadata files are absent, endpoints still run and return empty or low-confidence analytics.

## Run The Detection Pipeline

For the official clips:

```bash
python -m pipeline.detect --input data/raw --output data/events/events.jsonl
```

Before clips arrive, the deterministic replay path copies `sample_events.jsonl` into the pipeline output:

```bash
pipeline/run.sh --input data/raw --output data/events/events.jsonl --prefer-sample
```

The CV path uses YOLOv8 person tracking when `ultralytics` and OpenCV are installed. It maps tracked person centroids into zones from `store_layout.json`, emits `ENTRY`, `ZONE_ENTER`, `ZONE_EXIT`, and `ZONE_DWELL` events, and keeps confidence values instead of suppressing uncertain detections.

Install optional CV dependencies before processing real clips:

```bash
pip install -r requirements-cv.txt
```

For a quick smoke test on the provided clips, process only the first few seconds per camera:

```bash
python -m pipeline.detect --input data/raw --output data/events/smoke.jsonl --max-seconds 10 --frame-stride 10
```

For the full sample set, omit `--max-seconds`. Use `--frame-stride 5` or `--frame-stride 10` if you need a faster demo run on CPU.

## Feed Events Into The API

```bash
python -m pipeline.emit --sample data/events/events.jsonl --url http://localhost:8000/events/ingest
```

You can also replay the official sample file directly:

```bash
python -m pipeline.emit --sample data/raw/sample_events.jsonl --url http://localhost:8000/events/ingest
```

## Live Dashboard

```bash
python -m app.dashboard --store-id STORE_BLR_002
```

The dashboard polls the local API at `http://localhost:8000` and reads `/metrics`, `/anomalies`, and `/health`, so it updates as replayed or live pipeline events are ingested.

## API Endpoints

- `POST /events/ingest` accepts a JSON array or `{ "events": [...] }`, max 500 events. It validates each event, deduplicates by `event_id`, and reports partial failures without returning a 5xx.
- `GET /stores/{id}/metrics` returns unique visitors, conversion rate, converted visitors, dwell, queue depth, and abandonment rate.
- `GET /stores/{id}/funnel` returns session-level Entry -> Zone Visit -> Billing Queue -> Purchase counts.
- `GET /stores/{id}/heatmap` returns zone visit frequency and average dwell normalized to a 0-100 score.
- `GET /stores/{id}/anomalies` returns queue spike, conversion drop, and dead-zone anomalies with severity and suggested action.
- `GET /health` returns DB health, last event timestamps, lag, and stale-feed warnings.

## Event Schema

Each event must include:

```json
{
  "event_id": "uuid-v4",
  "store_id": "STORE_BLR_002",
  "camera_id": "CAM_ENTRY_01",
  "visitor_id": "VIS_c8a2f1",
  "event_type": "ZONE_DWELL",
  "timestamp": "2026-03-03T14:22:10Z",
  "zone_id": "SKINCARE",
  "dwell_ms": 8400,
  "is_staff": false,
  "confidence": 0.91,
  "metadata": {
    "queue_depth": null,
    "sku_zone": "MOISTURISER",
    "session_seq": 5
  }
}
```

Supported event types are `ENTRY`, `EXIT`, `ZONE_ENTER`, `ZONE_EXIT`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`, `BILLING_QUEUE_ABANDON`, and `REENTRY`.
