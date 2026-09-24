"""Read-only, session-scoped chat evidence for tutoring; no transcript copies on disk.

The only durable link is the Hermes session ID plus message-ID bounds in the
active TutorSession. Never scan other sessions, tool messages or attachments.
"""
from __future__ import annotations

import os
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

MAX_LOG_BYTES = 1024 * 1024
MAX_BACKUPS = 2
KINDS = {"learning_entered", "learning_paused", "learning_resumed", "learning_exited",
         "question_asked", "answer_evaluated", "hint_given", "transfer_checked",
         "grade_submitted", "mentor_issue"}
ISSUES = {"revealed_answer_too_early", "skipped_transfer", "unnecessary_detour",
          "wrong_grading", "changed_topic_too_soon", "other_review_needed"}
REASONS = {"user_request", "topic_switch", "session_complete", "budget_exhausted", "interrupted", "unknown"}
FIELDS = {"session_id", "concept_id", "reason", "verdict", "hinted", "transfer", "objective", "ease", "issue", "mode"}

MAX_MESSAGES = 20
MAX_SCAN_ROWS = 100
MAX_EXCERPT = 300
_SENSITIVE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{20,}|(?:api[_-]?key|password|token|secret|验证码|密码)\s*[:=：]\s*\S+"
    r"|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d))"
)
_SKIP_MARKERS = ("<memory-context>", "[OUT-OF-BAND", "--- Attached Context ---",
                 "data:image/", "MEDIA:", "[CONTEXT COMPACTION")


def record(path: Path, kind: str, **fields) -> dict:
    """Keep only finite, typed learning metadata. Never serialize raw chat."""
    if kind not in KINDS:
        raise ValueError("unknown observation kind")
    item: dict = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind}
    for key, value in fields.items():
        if key not in FIELDS:
            continue
        if key in ("session_id", "concept_id"):
            if not isinstance(value, str) or len(value) > 120 or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
                raise ValueError("invalid identifier")
        elif key == "reason" and value not in REASONS:
            raise ValueError("invalid reason")
        elif key == "issue" and value not in ISSUES:
            raise ValueError("invalid issue")
        elif key in ("verdict", "transfer") and value not in ("correct", "partial", "wrong", "passed", "failed"):
            raise ValueError("invalid verdict")
        elif key == "objective" and value not in ("L0", "L1", "L2", "L3"):
            raise ValueError("invalid objective")
        elif key == "mode" and value not in ("active_learning", "passive_review", "quick_quiz"):
            raise ValueError("invalid mode")
        elif key == "ease" and (type(value) is not int or value not in (1, 2, 3, 4)):
            raise ValueError("invalid ease")
        elif key == "hinted" and type(value) is not bool:
            raise ValueError("invalid hinted")
        item[key] = value
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(item, ensure_ascii=False) + "\n"
    if path.exists() and path.stat().st_size + len(line.encode()) > MAX_LOG_BYTES:
        for index in range(MAX_BACKUPS, 1, -1):
            old = path.with_name(path.name + f".{index-1}")
            if old.exists():
                os.replace(old, path.with_name(path.name + f".{index}"))
        os.replace(path, path.with_name(path.name + ".1"))
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        os.fchmod(fh.fileno(), 0o600)
        fh.write(line)
    return item


def report(path: Path, session_id: str | None = None) -> dict:
    path = Path(path)
    rows = []
    for file in [path.with_name(path.name + f".{i}") for i in range(MAX_BACKUPS, 0, -1)] + [path]:
        if file.exists():
            with file.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict) and item.get("kind") in KINDS:
                        rows.append(item)
    if session_id:
        rows = [row for row in rows if row.get("session_id") == session_id]
    clocks = {}
    elapsed = 0.0
    for row in rows:
        sid = row.get("session_id")
        kind = row["kind"]
        if kind in ("learning_entered", "learning_resumed"):
            clocks[sid] = row["ts"]
        elif kind in ("learning_paused", "learning_exited") and sid in clocks:
            elapsed += max(0.0, (datetime.fromisoformat(row["ts"]) -
                                datetime.fromisoformat(clocks.pop(sid))).total_seconds())
    return {"events": len(rows), "transitions": dict(Counter(r["kind"] for r in rows if r["kind"].startswith("learning_"))),
            "answer_verdicts": dict(Counter(r["verdict"] for r in rows if r["kind"] == "answer_evaluated")),
            "mentor_issues": dict(Counter(r["issue"] for r in rows if r["kind"] == "mentor_issue")),
            "questions": sum(r["kind"] == "question_asked" for r in rows),
            "hints": sum(r["kind"] == "hint_given" for r in rows),
            "transfers": dict(Counter(r["transfer"] for r in rows if r["kind"] == "transfer_checked")),
            "grades_submitted": dict(Counter(str(r["ease"]) for r in rows if r["kind"] == "grade_submitted")),
            "completed_active_seconds": round(elapsed),
            "open_intervals_excluded": len(clocks),
            "recent": rows[-12:]}


def db_path() -> Path:
    profile = os.environ.get("HERMES_SESSION_PROFILE", "default")
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    if profile != "default":
        # The caller must supply its own profile home; never read the default
        # profile's database on behalf of another profile.
        if not os.environ.get("HERMES_HOME"):
            raise ValueError("non-default profile requires HERMES_HOME")
    return home / "state.db"


def _open(db: Path) -> sqlite3.Connection:
    if not Path(db).is_file():
        raise ValueError("Hermes session database unavailable")
    return sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)


def _identity(con: sqlite3.Connection, sid: str, profile: str, source: str) -> None:
    row = con.execute("SELECT profile_name, source FROM sessions WHERE id=?", (sid,)).fetchone()
    if not row or row[0] != profile or row[1] != source:
        raise ValueError("Hermes session scope/profile mismatch")


def bind(db: Path | None = None) -> dict:
    sid = os.environ.get("HERMES_SESSION_ID")
    profile = os.environ.get("HERMES_SESSION_PROFILE", "default")
    source = os.environ.get("HERMES_SESSION_SOURCE")
    if not sid or not source:
        raise ValueError("Hermes session identity unavailable; no chat observation bound")
    with _open(db or db_path()) as con:
        _identity(con, sid, profile, source)
        last = con.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE session_id=?", (sid,)).fetchone()[0]
    return {"session_id": sid, "profile": profile, "source": source, "after_id": last}


def watermark(db: Path, binding: dict) -> int:
    sid = binding["session_id"]
    _require_current(binding)
    with _open(db) as con:
        _identity(con, sid, binding["profile"], binding["source"])
        return int(con.execute("SELECT COALESCE(MAX(id),0) FROM messages WHERE session_id=?", (sid,)).fetchone()[0])


def _require_current(binding: dict) -> None:
    if (binding.get("session_id") != os.environ.get("HERMES_SESSION_ID") or
        binding.get("profile") != os.environ.get("HERMES_SESSION_PROFILE", "default") or
        binding.get("source") != os.environ.get("HERMES_SESSION_SOURCE")):
        raise ValueError("observation belongs to a different Hermes session")


def _excerpt(text: str) -> str:
    if any(marker in text for marker in _SKIP_MARKERS):
        return "[omitted: attachment/system context]"
    if _SENSITIVE.search(text):
        return "[omitted: possible private data]"
    # Avoid copying very long turns containing unrelated material. Excerpts
    # are generated only for display and are never stored in AnkiTutor state.
    if len(text) > 2000:
        return "[omitted: long or mixed-topic message]"
    return text[:MAX_EXCERPT] + ("…" if len(text) > MAX_EXCERPT else "")


def read_range(db: Path, binding: dict, until_id: int) -> list[dict]:
    _require_current(binding)
    after = binding.get("after_id")
    if type(after) is not int or after < 0 or type(until_id) is not int or until_id < after:
        raise ValueError("invalid observation boundary")
    with _open(db) as con:
        _identity(con, binding["session_id"], binding["profile"], binding["source"])
        rows = con.execute("""SELECT id, role, content FROM messages
            WHERE session_id=? AND id>? AND id<=? AND role IN ('user','assistant')
            AND active=1 AND (compacted=0 OR compacted IS NULL)
            ORDER BY id DESC LIMIT ?""",
            (binding["session_id"], after, until_id, MAX_SCAN_ROWS)).fetchall()
    return [{"id": mid, "role": role, "excerpt": _excerpt(content)}
            for mid, role, content in reversed(rows[:MAX_MESSAGES])
            if isinstance(content, str) and content.strip()]
