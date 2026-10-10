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

# Suggestions only: the user's own goal line is free-form (a candidate that
# isn't listed here is accepted and drives teaching just the same).
CANDIDATES = ("alpha", "Polymarket", "gold")
TTL_DAYS = 30
ASK_COOLDOWN_DAYS = 7
ROADMAP_LIMIT = 12
VERSION = 2


def _path() -> Path:
    return Path(os.environ.get("ANKITUTOR_STATE", str(Path(__file__).resolve().parent.parent / "state"))) / "strategy.json"


def _asks_path() -> Path:
    """Where a proactive direction ask is recorded when no goal exists yet.

    The ask predates any strategy record, so it cannot live inside
    strategy.json: without this sidecar the 7-day cooldown silently never
    applied and the tutor re-asked on every session.
    """
    return _path().with_name("direction_asks.json")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_asks() -> dict:
    path = _asks_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_asks(record: dict) -> None:
    path = _asks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=str(path.parent),
                                         prefix=".asks-", delete=False) as fh:
            name = fh.name
            os.fchmod(fh.fileno(), 0o600)
            json.dump(record, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _valid_candidate(value) -> str:
    if not isinstance(value, str):
        raise ValueError("strategy candidate must be a string")
    value = value.strip()
    if not value or len(value) > 200 or "\n" in value or "\r" in value:
        raise ValueError("strategy candidate must be a nonempty single line of at most 200 characters")
    return value


def _read_store() -> Optional[dict]:
    path = _path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("strategy state is unreadable; refusing to overwrite") from exc
    if isinstance(data, dict) and data.get("version") == 3:
        if not isinstance(data.get("tracks"), dict) or data.get("focus") not in (None, *data["tracks"]):
            raise ValueError("invalid track store; refusing to overwrite")
        for tid, track in data["tracks"].items():
            validate_track_id(tid)
            if not isinstance(track, dict) or track.get("id") != tid or track.get("track_status") not in ("active", "completed", "archived"):
                raise ValueError("invalid track record; refusing to overwrite")
        return data
    if not isinstance(data, dict) or data.get("version") not in (1, 2) or data.get("status") not in ("proposed", "confirmed", "expired") or not isinstance(data.get("revision"), int) or isinstance(data.get("revision"), bool) or data["revision"] < 1:
        raise ValueError("strategy state is invalid; refusing to overwrite")
    _valid_candidate(data.get("candidate"))
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


def _read() -> Optional[dict]:
    data = _read_store()
    if data and data.get("version") == 3:
        return data["tracks"].get(data["focus"])
    return data


def validate_track_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise ValueError("track ID must match [a-z0-9][a-z0-9_-]{0,63}; no normalization")
    return value


def migrate() -> dict:
    """Back up before atomic migration; reads never infer historical progress."""
    store = _read_store()
    if store and store.get("version") == 3:
        return {"migrated": False, "focus": store["focus"]}
    path = _path()
    if store:
        backup = path.with_name("strategy.legacy.bak")
        original = path.read_bytes()
        if backup.exists() and backup.read_bytes() != original:
            raise ValueError("legacy backup differs; manual recovery required")
        if not backup.exists():
            with backup.open("xb") as fh:
                os.fchmod(fh.fileno(), 0o600)
                fh.write(original)
                fh.flush()
                os.fsync(fh.fileno())
        if backup.read_bytes() != original:
            raise ValueError("backup verification failed")
        store.update(id="legacy", name=store["candidate"], track_status="active")
    wrapper = {"version": 3, "focus": "legacy" if store else None,
               "tracks": {"legacy": store} if store else {}}
    _atomic_write(wrapper)
    if _read_store() != wrapper:
        raise ValueError("migration verification failed; restore strategy.legacy.bak")
    return {"migrated": bool(store), "focus": wrapper["focus"]}


def list_tracks() -> dict:
    store = _read_store()
    if not store:
        return {"focus": None, "tracks": []}
    if store.get("version") != 3:
        return {"focus": "legacy", "tracks": [dict(store, id="legacy", name=store["candidate"], track_status="active")]}
    return {"focus": store["focus"], "tracks": list(store["tracks"].values())}


def create_track(track_id: str, name: str, outcome: str, criterion: str) -> dict:
    validate_track_id(track_id)
    record = _outcome(_valid_candidate(name), outcome, criterion, None)
    migrate()
    store = _read_store()
    if track_id in store["tracks"]:
        raise ValueError("track ID already exists")
    record.update(id=track_id, name=_short(name, "name"), track_status="active")
    store["tracks"][track_id] = record
    _atomic_write(store)
    return record


def get_track(track_id: str) -> dict:
    validate_track_id(track_id)
    for track in list_tracks()["tracks"]:
        if track["id"] == track_id:
            return track
    raise ValueError("unknown track")


def set_focus(track_id: str | None) -> dict:
    from session import load_session, park_session, restore_snapshot, assert_safe_snapshots, SessionError
    if track_id is not None:
        get_track(track_id)
    path = _path().with_name("active_session.json")
    assert_safe_snapshots(path)
    current = load_session(path)
    if current and current.data.get("grade_state") == "pending":
        raise SessionError("pending grade: reconcile before switching focus")
    migrate()
    store = _read_store()
    if store["focus"] == track_id:
        if not current and track_id:
            restore_snapshot(track_id, path)
        return show()
    if current:
        park_session(current, path)
    store["focus"] = track_id
    _atomic_write(store)
    if track_id:
        restore_snapshot(track_id, path)
    return show()


def set_track_status(track_id: str, status: str, confirmed: bool = False) -> dict:
    if status not in ("active", "completed", "archived") or not confirmed:
        raise ValueError("explicit user confirmation required for track status")
    get_track(track_id)
    migrate()
    store = _read_store()
    store["tracks"][track_id]["track_status"] = status
    store["tracks"][track_id]["updated_at"] = _now().isoformat()
    _atomic_write(store)
    return store["tracks"][track_id]


def show() -> dict:
    data = _read()
    if data is None:
        asks = _read_asks()
        asked = _latest_asked(asks)
        return {"status": "unconfirmed", "candidate": None, "candidates": list(CANDIDATES),
                "asked_at": asked, "roadmap": [], "should_ask_direction": _should_ask({"asked_at": asked})}
    result = _v2(dict(data))
    result["asked_at"] = _latest_asked(data)
    result["due_for_review"] = data["status"] == "confirmed" and _now() >= datetime.fromisoformat(data["review_due_at"])
    result["should_ask_direction"] = (data["status"] != "confirmed" and _should_ask(result))
    if result["due_for_review"]:
        # Monthly full review: outcome/goal still right? Mention once, do not nag.
        result["review_note"] = ("monthly goal review is due: confirm the outcome still fits "
                                 "or run strategy revise --revision N")
    return result


def _latest_asked(data: dict) -> str | None:
    """The most recent proactive ask, from the strategy record or the sidecar."""
    stamps = []
    for value in (data.get("asked_at"), _read_asks().get("asked_at")):
        try:
            stamps.append(datetime.fromisoformat(value))
        except (TypeError, ValueError):
            continue
    return max(stamps).isoformat() if stamps else None


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


def mark_asked(because: str | None = None) -> dict:
    """Record that the tutor proactively asked the user for direction.

    because: what prompted the ask — 'cron_delivery', 'session_opening' or
    'review_due'. Recorded in asked_reason for the monthly review, so the
    ask isn't a silently writable side effect.

    With no strategy record yet (the usual case — that is exactly when the
    tutor asks) the timestamp goes to the sidecar so the cooldown still holds.
    """
    prompts = {"cron_delivery", "session_opening", "review_due"}
    if because not in prompts:
        raise ValueError("ask reason must be one of " + ", ".join(sorted(prompts)))
    asked_at = _now().isoformat()
    data = _read()
    if data is None:
        _write_asks({"asked_at": asked_at, "asked_reason": because})
        return show()
    data["asked_at"] = asked_at
    data["asked_reason"] = because
    _write(data)
    return show()


def _write(data: dict) -> dict:
    store = _read_store()
    if store and store.get("version") == 3:
        focus = store["focus"]
        if focus is None:
            raise ValueError("select a focus or create a named track first")
        previous = store["tracks"][focus]
        data.update(id=focus, name=data.get("candidate", previous["name"]), track_status=previous["track_status"])
        store["tracks"][focus] = data
        _atomic_write(store)
    else:
        _atomic_write(data)
    return show()


def _atomic_write(data: dict) -> None:
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
    candidate = _valid_candidate(candidate)
    previous = _read()
    if previous and previous["status"] != "expired":
        raise ValueError("existing strategy: use revise or expire first")
    update = _outcome(candidate, outcome, criterion, previous)
    if previous:
        update["history"] = previous.get("history", []) + [{k: v for k, v in previous.items() if k != "history"}]
    return _write(update)


def confirm(revision: int) -> dict:
    data = _read()
    if not data or data["status"] not in ("proposed", "confirmed") or data["revision"] != revision:
        raise ValueError("confirmation requires the current proposed revision")
    now = _now()
    # Confirming ratifies the current version: the revision number does NOT
    # advance here (it counts roadmap versions, not write operations).
    if data["status"] == "confirmed":
        data.setdefault("confirmation_history", []).append({"revision": data["revision"], "updated_at": data["updated_at"], "review_due_at": data["review_due_at"]})
    data.update(status="confirmed", updated_at=now.isoformat(), review_due_at=(now + timedelta(days=TTL_DAYS)).isoformat())
    return _write(data)


def revise(candidate: str, revision: int, outcome: str = "", criterion: str = "") -> dict:
    candidate = _valid_candidate(candidate)
    data = _read()
    if not data or data["status"] == "expired" or data["revision"] != revision:
        raise ValueError("revision requires current non-expired strategy revision")
    previous = data
    update = _outcome(candidate, outcome, criterion, previous, status="proposed")
    update["asked_at"] = data.get("asked_at")
    # Roadmap content survives a terminology-only revision of the SAME goal so
    # evidence is not lost — but evidence for one goal is never inherited by a
    # different one (capability proof does not transfer between outcomes).
    update["history"] = previous.get("history", []) + [{k: v for k, v in previous.items() if k != "history"}]
    if previous.get("roadmap") and previous.get("outcome") == update["outcome"] and previous.get("criterion") == update["criterion"]:
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
    if entry.get("evidence"):
        entry.setdefault("evidence_history", []).append({k: v for k, v in entry.items() if k != "evidence_history"})
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
