"""Explicit, local strategic goal choice; never inferred from study activity."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

CANDIDATES = ("alpha", "Polymarket", "gold")
TTL_DAYS = 30


def _path() -> Path:
    return Path(os.environ.get("ANKITUTOR_STATE", str(Path(__file__).resolve().parent.parent / "state"))) / "strategy.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read() -> Optional[dict]:
    path = _path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("strategy state is unreadable; refusing to overwrite") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("status") not in ("proposed", "confirmed", "expired") or data.get("candidate") not in CANDIDATES or not isinstance(data.get("revision"), int) or isinstance(data.get("revision"), bool) or data["revision"] < 1:
        raise ValueError("strategy state is invalid; refusing to overwrite")
    if not isinstance(data.get("deliverable"), str) or not isinstance(data.get("criterion"), str):
        raise ValueError("strategy outcome is missing; refusing to infer it")
    try:
        due = datetime.fromisoformat(data["review_due_at"])
        if due.tzinfo is None:
            raise ValueError("timezone required")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("strategy review date is invalid") from exc
    return data


def show() -> dict:
    data = _read()
    if data is None:
        return {"status": "unconfirmed", "candidate": None, "candidates": list(CANDIDATES)}
    result = dict(data)
    result["due_for_review"] = data["status"] == "confirmed" and _now() >= datetime.fromisoformat(data["review_due_at"])
    return result


def _write(data: dict) -> dict:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=str(path.parent), prefix=".strategy-", delete=False) as fh:
            name = fh.name
            os.fchmod(fh.fileno(), 0o600)
            json.dump(data, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return show()


def _short(value: str, name: str) -> str:
    value = value.strip()
    if not value or len(value) > 200 or "\n" in value or "\r" in value:
        raise ValueError(f"{name} must be a nonempty single line of at most 200 characters")
    return value


def propose(candidate: str, deliverable: str = "", criterion: str = "") -> dict:
    if candidate not in CANDIDATES:
        raise ValueError("candidate must be alpha, Polymarket, or gold")
    previous = _read()
    if previous and previous["status"] != "expired":
        raise ValueError("existing strategy: use revise or expire first")
    now = _now()
    return _write({"version": 1, "revision": (previous["revision"] + 1 if previous else 1), "status": "proposed", "candidate": candidate, "deliverable": _short(deliverable, "deliverable"), "criterion": _short(criterion, "criterion"), "updated_at": now.isoformat(), "review_due_at": (now + timedelta(days=TTL_DAYS)).isoformat()})


def confirm(revision: int) -> dict:
    data = _read()
    if not data or data["status"] != "proposed" or data["revision"] != revision:
        raise ValueError("confirmation requires the current proposed revision")
    now = _now()
    data.update(status="confirmed", updated_at=now.isoformat(), review_due_at=(now + timedelta(days=TTL_DAYS)).isoformat(), revision=revision + 1)
    return _write(data)


def revise(candidate: str, revision: int, deliverable: str = "", criterion: str = "") -> dict:
    if candidate not in CANDIDATES:
        raise ValueError("candidate must be alpha, Polymarket, or gold")
    data = _read()
    if not data or data["status"] == "expired" or data["revision"] != revision:
        raise ValueError("revision requires current non-expired strategy revision")
    now = _now()
    data.update(candidate=candidate, deliverable=_short(deliverable, "deliverable"), criterion=_short(criterion, "criterion"), status="proposed", revision=revision + 1, updated_at=now.isoformat(), review_due_at=(now + timedelta(days=TTL_DAYS)).isoformat())
    return _write(data)


def expire(revision: int) -> dict:
    data = _read()
    if not data or data["status"] == "expired" or data["revision"] != revision:
        raise ValueError("expiration requires current non-expired strategy revision")
    data.update(status="expired", revision=revision + 1, updated_at=_now().isoformat())
    return _write(data)
