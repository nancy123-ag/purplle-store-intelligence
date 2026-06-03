from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Iterable

import requests


def read_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def chunks(items: list[dict], size: int) -> Iterable[list[dict]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def post_events(events: list[dict], url: str, batch_size: int, delay_seconds: float) -> None:
    session = requests.Session()
    total_accepted = 0
    total_duplicates = 0
    total_errors = 0
    for batch in chunks(events, batch_size):
        response = session.post(url, json={"events": batch}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        total_accepted += payload.get("accepted", 0)
        total_duplicates += payload.get("duplicates", 0)
        total_errors += len(payload.get("errors", []))
        print(
            json.dumps(
                {
                    "sent": len(batch),
                    "accepted": payload.get("accepted", 0),
                    "duplicates": payload.get("duplicates", 0),
                    "errors": len(payload.get("errors", [])),
                }
            )
        )
        if delay_seconds:
            time.sleep(delay_seconds)
    print(json.dumps({"accepted": total_accepted, "duplicates": total_duplicates, "errors": total_errors}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay JSONL event files into the Store Intelligence API.")
    parser.add_argument("--sample", required=True, help="Path to sample_events.jsonl or pipeline output JSONL.")
    parser.add_argument("--url", default="http://localhost:8000/events/ingest", help="Ingest endpoint URL.")
    parser.add_argument("--batch-size", type=int, default=100, help="Events per request, max 500.")
    parser.add_argument("--delay-seconds", type=float, default=0.0, help="Delay between batches for simulated real time.")
    args = parser.parse_args(argv)

    path = Path(args.sample)
    if not path.exists():
        print(f"Event file not found: {path}", file=sys.stderr)
        return 2
    events = list(read_jsonl(path))
    if args.batch_size > 500:
        print("batch-size must be <= 500", file=sys.stderr)
        return 2
    post_events(events, args.url, args.batch_size, args.delay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

