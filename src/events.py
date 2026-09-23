"""JSONL event log — engineering observability only (doc §17).

The log is for debugging/auditing. It is NEVER read back to reconstruct
mastery: Anki remains the single source of truth for scheduling.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import EVENTS_LOG_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log_event(event: str, **fields) -> dict:
    """Append one JSONL record. Never raises into the caller's flow."""
    rec = {"ts": _now_iso(), "event": event}
    rec.update(fields)
    path = Path(EVENTS_LOG_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        # Logging must never break a learning session.
        pass
    return rec


def read_events(limit: int | None = None) -> list[dict]:
    path = Path(EVENTS_LOG_PATH)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:] if limit else out
