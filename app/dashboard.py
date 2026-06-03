from __future__ import annotations

import argparse
import json
import time
from typing import Any

import requests


def fetch(base_url: str, store_id: str) -> dict[str, Any]:
    metrics = requests.get(f"{base_url}/stores/{store_id}/metrics", timeout=5).json()
    anomalies = requests.get(f"{base_url}/stores/{store_id}/anomalies", timeout=5).json()
    health = requests.get(f"{base_url}/health", timeout=5).json()
    return {"metrics": metrics, "anomalies": anomalies, "health": health}


def render_plain(payload: dict[str, Any]) -> None:
    metrics = payload["metrics"]
    anomalies = payload["anomalies"].get("anomalies", [])
    print("\033[2J\033[H", end="")
    print("Store Intelligence Live Dashboard")
    print("=" * 40)
    print(f"Store: {metrics['store_id']}")
    print(f"Visitors: {metrics['unique_visitors']}")
    print(f"Conversion rate: {metrics['conversion_rate']:.2%}")
    print(f"Queue depth: {metrics['queue_depth']}")
    print(f"Abandonment rate: {metrics['billing_queue_abandonment_rate']:.2%}")
    print(f"Health: {payload['health']['status']}")
    print("\nAnomalies:")
    if not anomalies:
        print("  none")
    for anomaly in anomalies:
        print(f"  {anomaly['severity']} {anomaly['type']}: {anomaly['suggested_action']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Poll the API and display live store metrics.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--store-id", default="STORE_BLR_002")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    while True:
        try:
            payload = fetch(args.base_url.rstrip("/"), args.store_id)
            render_plain(payload)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}))
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

