"""Shared data generation helpers for the SDP schema-evolution demo.

Pure stdlib so it imports and runs anywhere (plain python, notebooks, bundles).
"""

import json
import os


def v1_records() -> list[dict]:
    """Clean v1 orders: amount is a stringified number, name is `cust_name`."""
    return [
        {"order_id": "o-001", "cust_name": "Alice", "amount": "125.50", "order_ts": "2026-07-01T09:15:00"},
        {"order_id": "o-002", "cust_name": "Bob", "amount": "42.00", "order_ts": "2026-07-02T11:30:00"},
        {"order_id": "o-003", "cust_name": "Carol", "amount": "310.75", "order_ts": "2026-07-03T14:05:00"},
        {"order_id": "o-004", "cust_name": "Dan", "amount": "18.99", "order_ts": "2026-07-04T16:45:00"},
        {"order_id": "o-005", "cust_name": "Eve", "amount": "205.20", "order_ts": "2026-07-05T08:00:00"},
    ]


def v2_records() -> list[dict]:
    """Drifted v2 orders: `cust_name`->`customer_name`, amount float, + `loyalty_tier`."""
    return [
        {"order_id": "o-101", "customer_name": "Frank", "amount": 88.40, "loyalty_tier": "gold", "order_ts": "2026-07-14T09:00:00"},
        {"order_id": "o-102", "customer_name": "Grace", "amount": 512.00, "loyalty_tier": "silver", "order_ts": "2026-07-14T12:20:00"},
        {"order_id": "o-103", "customer_name": "Heidi", "amount": 27.35, "loyalty_tier": "bronze", "order_ts": "2026-07-15T10:10:00"},
        {"order_id": "o-104", "customer_name": "Ivan", "amount": 149.99, "loyalty_tier": "gold", "order_ts": "2026-07-15T15:40:00"},
        {"order_id": "o-105", "customer_name": "Judy", "amount": 63.10, "loyalty_tier": "bronze", "order_ts": "2026-07-16T08:55:00"},
    ]


def write_json(records: list[dict], dest_dir: str, filename: str) -> str:
    """Write records as newline-delimited JSON to dest_dir/filename. Returns full path.

    Uses plain file IO: on serverless a /Volumes path is a normal FUSE path.
    """
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, filename)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    return path


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p1 = write_json(v1_records(), tmp, "orders_v1.json")
        p2 = write_json(v2_records(), tmp, "orders_v2.json")

        for path, expected in ((p1, v1_records()), (p2, v2_records())):
            assert os.path.exists(path), f"missing file: {path}"
            with open(path) as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
            assert len(lines) == len(expected), f"line count mismatch in {path}"
            for ln in lines:
                json.loads(ln)  # each line must be valid JSON

    print("self-check OK: v1 and v2 files written, line counts and JSON valid")
