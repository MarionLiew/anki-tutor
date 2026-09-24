"""Explicit, local strategic goal choice; never inferred from study activity.

Level design (user-defined):
  outcome   — the end result the user wants ("I can find alpha"), as a
              concrete deliverable statement, not a topic name.
  criterion — how the user will judge it done.
  roadmap   — ordered capability chain on the way to the outcome; one entry
              may hold evidence (a produced artifact or verified judgement).
  asked_at  — when the tutor last proactively asked the user for direction,
              so it asks once and not again for ASK_COOLDOWN_DAYS.
Anki scores concepts; only roadmap evidence advances the outcome.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

CANDIDATES = ("alpha", "Polymarket", "gold")
TTL_DAYS = 30
ASK_COOLDOWN_DAYS = 7
ROADMAP_LIMIT = 12
VERSION = 2


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
    if not isinstance(data, dict) or data.get("version") not in (1, 2) or data.get("status") not in ("proposed", "confirmed", "expired") or data.get("candidate") not in CANDIDATES or not isinstance(data.get("revision"), int) or isinstance(data.get("revision"), bool) or data["revision"] < 1:
        raise ValueError("strategy state is invalid; refusing to overwrite")
    if not isinstance(data.get("deliverable") if data.get("version") == 1 else data.get("outcome"), str) or not isinstance(data.get("criterion"), str):
        raise ValueError("strategy outcome is missing; refusing to infer it")
    try:
        due = datetime.fromisoformat(data["review_due_at"])
        if due.tzinfo is None:
            raise ValueError("timezone required")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("strategy review date is invalid") from exc
    if data["version"] == 1:
        data["outcome"] = data.pop("deliverable")
        data["roadmap"] = []
        data["version"] = 2
    return data


def show() -> dict:
    data = _read()
    if data is None:
        return {"status": "unconfirmed", "candidate": None, "candidates": list(CANDIDATES),
                "roadmap": [], "should_ask_direction": True}
    result = _v2(dict(data))
    result["due_for_review"] = data["status"] == "confirmed" and _now() >= datetime.fromisoformat(data["review_due_at"])
    result["should_ask_direction"] = (data["status"] != "confirmed" and _should_ask(data))
    if result["due_for_review"]:
        # Monthly full review: outcome/goal still right? Mention once, do not nag.
        result["review_note"] = ("monthly goal review is due: confirm the outcome still fits "
                                 "or run strategy revise --revision N")
    return result


def _v2(result: dict) -> dict:
    """Present v1 records with the v2 field names."""
    if result.get("version") == 1:
        result["outcome"] = result.get("deliverable", "")
        result["roadmap"] = []
        result.pop("deliverable", None)
    result.setdefault("roadmap", [])
    result["version"] = 2
    return result


def _should_ask(data: dict) -> bool:
    asked = data.get("asked_at")
    if not asked:
        return True
    try:
        return _now() - datetime.fromisoformat(asked) >= timedelta(days=ASK_COOLDOWN_DAYS)
    except ValueError:
        return True


def mark_asked(because: str | None = None) -> dict | None:
    """Record that the tutor proactively asked the user for direction.

    because: what prompted the ask — 'cron_delivery', 'session_opening' or
    'review_due'. Recorded in asked_reason for the monthly review, so the
    ask isn't a silently writable side effect.
    """
    prompts = {"cron_delivery", "session_opening", "review_due"}
    if because not in prompts:
        raise ValueError("ask reason must be one of " + ", ".join(sorted(prompts)))
    data = _read()
    if data is None:
        return None
    data["asked_at"] = _now().isoformat()
    data["asked_reason"] = because
    _write(data)
    return show()


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


def _evidence(value: str, name: str) -> str:
    value = value.strip()
    if len(value) > 200 or "\n" in value or "\r" in value:
        raise ValueError(f"{name} must be a single line of at most 200 characters")
    return value


def _outcome(candidate: str, outcome: str, criterion: str, previous: dict | None, status: str = "proposed") -> dict:
    """Shared write for propose/revise: version 2 schema with outcome + empty roadmap."""
    now = _now()
    base_revision = previous["revision"] if previous else 0
    return {"version": 2, "revision": base_revision + 1, "status": status, "candidate": candidate,
            "outcome": _short(outcome, "outcome"), "criterion": _short(criterion, "criterion"),
            "roadmap": [], "updated_at": now.isoformat(),
            "review_due_at": (now + timedelta(days=TTL_DAYS)).isoformat()}


def propose(candidate: str, outcome: str = "", criterion: str = "") -> dict:
    if candidate not in CANDIDATES:
        raise ValueError("candidate must be alpha, Polymarket, or gold")
    previous = _read()
    if previous and previous["status"] != "expired":
        raise ValueError("existing strategy: use revise or expire first")
    return _write(_outcome(candidate, outcome, criterion, previous))


def confirm(revision: int) -> dict:
    data = _read()
    if not data or data["status"] != "proposed" or data["revision"] != revision:
        raise ValueError("confirmation requires the current proposed revision")
    now = _now()
    # Confirming ratifies the current version: the revision number does NOT
    # advance here (it counts roadmap versions, not write operations).
    data.update(status="confirmed", updated_at=now.isoformat(), review_due_at=(now + timedelta(days=TTL_DAYS)).isoformat())
    return _write(data)


def revise(candidate: str, revision: int, outcome: str = "", criterion: str = "") -> dict:
    if candidate not in CANDIDATES:
        raise ValueError("candidate must be alpha, Polymarket, or gold")
    data = _read()
    if not data or data["status"] == "expired" or data["revision"] != revision:
        raise ValueError("revision requires current non-expired strategy revision")
    previous = data
    update = _outcome(candidate, outcome, criterion, previous, status="proposed")
    update["asked_at"] = data.get("asked_at")
    # Roadmap content survives a terminology-only revision so evidence is not lost.
    if previous.get("roadmap"):
        update["roadmap"] = previous["roadmap"]
    return _write(update)


# -- roadmap (capability chain evidence) ------------------------------------

def _roadmap_entry(data: dict, entry_id: str) -> dict:
    for e in data["roadmap"]:
        if e["id"] == entry_id:
            return e
    raise ValueError(f"no roadmap entry {entry_id}")


def roadmap_add(capability: str, kind: str = "required") -> dict:
    """kind: required (directly on the path to the criterion) or
    optional (supporting skill; never blocks the next-gap choice)."""
    if kind not in ("required", "optional"):
        raise ValueError("kind must be required or optional")
    data = _read()
    if not data or data["status"] != "confirmed":
        raise ValueError("roadmap requires a confirmed strategy")
    cap = _short(capability, "capability").lower()
    if len(data["roadmap"]) >= ROADMAP_LIMIT:
        raise ValueError("roadmap is full; revise or expire the strategy first")
    if any(e["id"] == cap for e in data["roadmap"]):
        raise ValueError(f"roadmap already has {cap}")
    data["roadmap"].append({"id": cap, "capability": _short(capability, "capability"),
                            "kind": kind, "status": "no_evidence", "evidence": None})
    data["updated_at"] = _now().isoformat()
    return _write(data)


def roadmap_evidence(entry_id: str, evidence: str, status: str = "evidenced") -> dict:
    if status not in ("evidenced", "no_evidence"):
        raise ValueError("status must be evidenced or no_evidence")
    data = _read()
    if not data or data["status"] != "confirmed":
        raise ValueError("roadmap requires a confirmed strategy")
    entry = _roadmap_entry(data, entry_id)
    entry["evidence"] = _evidence(evidence, "evidence") or None
    entry["status"] = status if (entry["evidence"] and status == "evidenced") else "no_evidence"
    if entry["evidence"]:
        entry["evidenced_at"] = _now().isoformat()
    data["updated_at"] = _now().isoformat()
    return _write(data)


def _serves(entry_cap: str, serving: str) -> bool:
    """Either direction contains the other, or they share a meaningful word."""
    a, b = entry_cap.lower(), serving.strip().lower()
    if a in b or b in a:
        return True
    stop = {"a", "the", "and", "of", "for", "to", "in", "on", "with", "的", "与", "和"}
    words_a = {w for w in re.split(r"[\s_-]+", a) if len(w) > 2 and w not in stop}
    words_b = {w for w in re.split(r"[\s_-]+", b) if len(w) > 2 and w not in stop}
    return bool(words_a & words_b)


def next_gap(serving: str | None = None) -> dict | None:
    """First required roadmap entry without evidence.

    serving: the current task/bottleneck, if any. When given, an entry that
    directly serves it is returned first (the roadmap order is a suggested
    path, not a straitjacket — the user's live task wins).
    """
    data = _read()
    if not data or data["status"] != "confirmed":
        return None
    if serving:
        for e in data["roadmap"]:
            if e["status"] != "evidenced" and _serves(e["capability"], serving):
                return {"id": e["id"], "capability": e["capability"],
                        "kind": e.get("kind", "required"), "status": e["status"],
                        "reason": "serves_current_task"}
    for e in data["roadmap"]:
        if e["status"] != "evidenced" and e.get("kind", "required") == "required":
            return {"id": e["id"], "capability": e["capability"], "kind": e["kind"],
                    "status": e["status"], "reason": "next_required_gap"}
    return None


def expire(revision: int) -> dict:
    data = _read()
    if not data or data["status"] == "expired" or data["revision"] != revision:
        raise ValueError("expiration requires current non-expired strategy revision")
    data.update(status="expired", revision=revision + 1, updated_at=_now().isoformat())
    return _write(data)
