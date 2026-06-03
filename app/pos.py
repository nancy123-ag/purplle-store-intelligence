from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.database import PosTransaction
from app.utils import ensure_utc


def parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return ensure_utc(parsed)


def parse_pos_timestamp(row: dict[str, str]) -> datetime:
    if row.get("timestamp"):
        return parse_timestamp(row["timestamp"])
    if row.get("order_date") and row.get("order_time"):
        value = f"{row['order_date'].strip()} {row['order_time'].strip()}"
        for fmt in ("%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return ensure_utc(datetime.strptime(value, fmt))
            except ValueError:
                continue
    raise ValueError("POS row must include timestamp or order_date/order_time")


def load_pos_csv(db: Session, path: str | None) -> int:
    if not path:
        return 0
    candidate = Path(path)
    if not candidate.exists():
        return 0

    loaded = 0
    with candidate.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            transaction_id = row.get("transaction_id") or row.get("txn_id") or row.get("order_id")
            if not transaction_id or db.get(PosTransaction, transaction_id):
                continue
            db.add(
                PosTransaction(
                    transaction_id=transaction_id,
                    store_id=row["store_id"],
                    timestamp=parse_pos_timestamp(row),
                    basket_value_inr=float(row.get("basket_value_inr") or row.get("amount") or row.get("total_amount") or 0.0),
                )
            )
            loaded += 1
    db.commit()
    return loaded
