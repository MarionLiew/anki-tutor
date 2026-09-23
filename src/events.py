"""JSONL event log — engineering observability only (doc §17).

The log is for debugging/auditing. It is NEVER read back to reconstruct
mastery: Anki remains the single source of truth for scheduling.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from config import EVENTS_LOG_PATH

# Debugging metadata only; never persist arbitrary caller payloads or exception text.
SAFE_FIELDS = {"session_id", "status", "concept", "concept_id", "concepts",
               "questions_used", "ease", "mode", "reason", "deck", "model"}
REASONS = {"user_request", "topic_switch", "session_complete", "budget_exhausted",
           "interrupted", "unknown"}
SAFE_EVENTS = {"session_saved", "session_closed", "session_started", "learning_entered",
               "learning_paused", "learning_resumed", "learning_exited", "ensure",
               "review_graded", "concept_retired", "passive_review_unreachable",
               "passive_review_no_due", "passive_review_started"}


def _safe_value(key: str, value):
    if key in {"questions_used", "ease"}:
        return value if type(value) is int else None
    if key == "reason":
        return value if value in REASONS else "unknown"
    if key == "concepts":
        return [v[:120] for v in value[:8] if isinstance(v, str)] if isinstance(value, list) else None
    return value[:120] if isinstance(value, str) else None


MAX_LOG_BYTES = 1024 * 1024
MAX_BACKUPS = 3


def _rotate(path: Path, incoming_bytes: int) -> None:
    if path.exists() and path.stat().st_size + incoming_bytes > MAX_LOG_BYTES:
        for index in range(MAX_BACKUPS, 1, -1):
            older = path.with_name(path.name + f".{index - 1}")
            newer = path.with_name(path.name + f".{index}")
            if older.exists():
                os.replace(older, newer)
        os.replace(path, path.with_name(path.name + ".1"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log_event(event: str, **fields) -> dict:
    """Append one JSONL record. Never raises into the caller's flow."""
    rec: dict[str, object] = {"ts": _now_iso(), "event": event if event in SAFE_EVENTS else "unknown"}
    for key, value in fields.items():
        if key in SAFE_FIELDS:
            safe = _safe_value(key, value)
            if safe is not None:
                rec[key] = safe
    path = Path(EVENTS_LOG_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        _rotate(path, len(line.encode("utf-8")))
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(line)
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
