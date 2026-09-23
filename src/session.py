"""TutorSession — short-lived per-session state, NOT a second mastery DB.

Responsibilities (doc §9): tell the next user message whether it is answering
the current question or starting a new task; enforce the one-question-at-a-time
rule and the question/duration budget; handle create/recover/pause/close.

Explicitly does NOT maintain next_review, FSRS values or any long-term mastery
(doc §9). Those belong to Anki only.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config import ACTIVE_SESSION_PATH, MODES, SESSION_POLICY, SESSION_STATUSES
from events import log_event


class SessionError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


class TutorSession:
    def __init__(self, data: dict):
        self.data = data

    @property
    def session_id(self) -> str:
        return self.data.get("session_id", "")

    @property
    def mode(self) -> str:
        return self.data.get("mode", "active_learning")

    @property
    def status(self) -> str:
        return self.data.get("status", "asking")

    @status.setter
    def status(self, value: str):
        if value not in SESSION_STATUSES:
            raise SessionError(f"invalid status '{value}'")
        self.data["status"] = value

    @property
    def current_concept(self) -> str | None:
        return self.data.get("current_concept")

    @property
    def attempt(self) -> int:
        return self.data.get("attempt", 1)

    @property
    def hint_level(self) -> int:
        return self.data.get("hint_level", 0)

    @property
    def questions_used(self) -> int:
        return self.data.get("questions_used", 0)

    # -- budget ------------------------------------------------------------
    def can_continue(self) -> bool:
        """False when question or duration budget is exhausted (§9.1)."""
        if self.questions_used > SESSION_POLICY["max_questions"]:
            return False
        started = self.data.get("started_at_epoch")
        if started is not None:
            elapsed = _now_epoch() - started
            if elapsed > SESSION_POLICY["hard_cap_duration_min"] * 60:
                return False
        return True

    def budget_remaining(self) -> dict:
        return {
            "questions_used": self.questions_used,
            "max_questions": SESSION_POLICY["max_questions"],
            "deep_misconceptions_tracked": self.data.get("deep_misconceptions_tracked", 0),
        }

    # -- one-question rule -------------------------------------------------
    def register_question(self) -> None:
        self.data["questions_used"] = int(self.data.get("questions_used", 0)) + 1

    def set_current_question(self, concept_id: str, question: str) -> None:
        self.data["current_concept"] = concept_id
        self.data["current_question"] = question
        self.data["attempt"] = 1
        self.data["hint_level"] = 0
        self.data["status"] = "waiting_answer"

    def advance_attempt(self, hint_level: int) -> None:
        self.data["attempt"] = int(self.data.get("attempt", 1)) + 1
        self.data["hint_level"] = hint_level
        self.data["status"] = "waiting_answer"

    def allows_another_prompt(self) -> bool:
        """One question can retry up to a fixed cap before forcing a verdict."""
        return self.attempt < 3

    def track_deep_misconception(self, concept_id: str) -> None:
        self.data.setdefault("deep_misconceptions_tracked", 0)
        self.data["deep_misconceptions_tracked"] = int(self.data["deep_misconceptions_tracked"]) + 1

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict:
        return self.data

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, indent=2)

    def save(self, path: Path = ACTIVE_SESSION_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(self.to_json())
        shutil.move(str(tmp), str(path))
        log_event("session_saved", session_id=self.session_id, status=self.status)

    def close(self, path: Path = ACTIVE_SESSION_PATH) -> None:
        path = Path(path)
        # Persist only the long-term-relevant outcome, then drop short-term state.
        log_event(
            "session_closed", session_id=self.session_id, questions_used=self.questions_used
        )
        self.data["status"] = "closed"
        self.data["ended_at"] = _now_iso()
        if path.exists():
            path.unlink()

    def pause(self, path: Path = ACTIVE_SESSION_PATH) -> None:
        path = Path(path)
        self.data["status"] = "paused"
        self.save(path)


# -- module-level helpers --------------------------------------------------

def new_session(
    mode: str,
    concept_queue: list[str] | None = None,
    concept: dict | None = None,
    question: str = "",
) -> TutorSession:
    if mode not in MODES:
        raise SessionError(f"invalid mode '{mode}', expected one of {MODES}")
    started = _now_iso()
    sid = concept["concept_id"] if concept else (concept_queue[0] if concept_queue else "seed")
    data = {
        "session_id": f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{str(uuid4())[:8]}",
        "mode": mode,
        "status": "asking",
        "concept_queue": concept_queue or [],
        "current_concept": concept.get("concept_id") if concept else None,
        "current_question": question,
        "attempt": 1,
        "hint_level": 0,
        "questions_used": 0,
        "deep_misconceptions_tracked": 0,
        "started_at": started,
        "started_at_epoch": _now_epoch(),
    }
    s = TutorSession(data)
    log_event(
        "session_started", session_id=s.session_id, mode=mode, concept=sid,
    )
    return s


def load_session(path: Path = ACTIVE_SESSION_PATH) -> TutorSession | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    s = TutorSession(data)
    return s if s.status in ("asking", "waiting_answer", "answer_received",
                             "diagnosing", "verifying_transfer", "graded", "paused") else None


def active_session_exists(path: Path = ACTIVE_SESSION_PATH) -> bool:
    s = load_session(path)
    return s is not None and s.status != "closed"


def clear_session(path: Path = ACTIVE_SESSION_PATH) -> None:
    if path.exists():
        path.unlink()