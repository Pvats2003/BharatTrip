"""
Append-only approval log (plain code).

Every approved ticket or agent message is written as one row to a CSV file, so the record
survives page refreshes and can be handed to the next team. Production would use a database;
the file path is configurable with APPROVAL_LOG_PATH.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import os
import uuid
from datetime import datetime

import pandas as pd

PATH = os.environ.get("APPROVAL_LOG_PATH",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "approvals", "approval_log.csv"))
FIELDS = ["approval_id", "approved_at", "approved_by", "type", "action", "refund_id", "agent_reference",
          "agent", "route", "amount_inr", "payout_inr", "owner", "next_step", "true_state", "message",
          "channel", "received_on", "source_text", "dedupe_key"]


def dedupe_key(*parts) -> str:
    """Same item approved twice (double click, refresh) -> same key -> stored once."""
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def load(path: str = PATH) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=FIELDS)
    return pd.read_csv(path, dtype=str).fillna("")


def already_approved(key: str, path: str = PATH) -> bool:
    df = load(path)
    return bool(len(df)) and key in set(df["dedupe_key"])


def append(record: dict, key: str, path: str = PATH) -> tuple[bool, str]:
    """Write one approval. Returns (written, approval_id). Not written if the same item is already logged."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)          # one writer at a time
        try:
            f.seek(0)
            rows = list(csv.DictReader(f))
            for r in rows:
                if r.get("dedupe_key") == key:
                    return False, r.get("approval_id", "")
            approval_id = "APR-" + uuid.uuid4().hex[:8].upper()
            row = {k: "" for k in FIELDS}
            row.update({k: ("" if v is None else v) for k, v in record.items() if k in FIELDS})
            row.update(approval_id=approval_id, dedupe_key=key,
                       approved_at=record.get("approved_at") or datetime.now().isoformat(timespec="seconds"))
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if not rows and f.tell() == 0:
                w.writeheader()
            f.seek(0, os.SEEK_END)
            w.writerow(row)
            return True, approval_id
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
