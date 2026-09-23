"""TutorSession — short-lived per-session state, NOT a second mastery DB.

Responsibilities (doc §9): tell the next user message whether it is answering
the current question or starting a new task; enforce the one-question-at-a-time
rule and the question/duration budget; handle create/recover/pause/close.

Explicitly does NOT maintain next_review, FSRS values or any long-term mastery
(doc §9). Those belong to Anki only.
"""

from __future__ import annotations

import json
import os
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
        if self.questions_used >= SESSION_POLICY["max_questions"]:
            return False
        if self.active_elapsed_seconds() >= SESSION_POLICY["hard_cap_duration_min"] * 60:
            return False
        return True

    def active_elapsed_seconds(self) -> float:
        accumulated = float(self.data.get("active_seconds", 0))
        anchor = self.data.get("active_since_epoch", self.data.get("started_at_epoch"))
        if self.status == "paused" or anchor is None:
            return accumulated
        return accumulated + max(0, _now_epoch() - float(anchor))

    def budget_remaining(self) -> dict:
        return {
            "questions_used": self.questions_used,
            "max_questions": SESSION_POLICY["max_questions"],
            "deep_misconceptions_tracked": self.data.get("deep_misconceptions_tracked", 0),
        }

    # -- one-question rule -------------------------------------------------
    def register_question(self) -> None:
        if self.status == "paused" or not self.can_continue():
            raise SessionError("session paused or question/time budget exhausted")
        if self.status == "waiting_answer":
            raise SessionError("answer the current question before registering another")
        self.data["questions_used"] = int(self.data.get("questions_used", 0)) + 1

    def set_current_question(self, concept_id: str, question: str, objective: str = "L1",
                             is_transfer: bool = False) -> None:
        if objective not in ("L0", "L1", "L2", "L3") or not concept_id or not question:
            raise SessionError("valid objective, concept and question required")
        evidence = self.data.get("evidence")
        if is_transfer and (not evidence or evidence["concept_id"] != concept_id or
                            evidence["first_attempt"] is None or evidence["latest"] != "correct"):
            raise SessionError("transfer requires a corrected first question")
        if not is_transfer and evidence and evidence["concept_id"] != concept_id:
            if self.data.get("grade_state") != "completed":
                raise SessionError("grade or pause the current concept before changing concepts")
            self.data.pop("grade_state", None)
        if not is_transfer and (not evidence or evidence["concept_id"] != concept_id):
            evidence = {"concept_id": concept_id, "objective": objective,
                        "first_attempt": None, "latest": None, "hints_used": False,
                        "transfer": "not_asked", "transfer_first_failed": False}
        elif evidence["objective"] != objective:
            raise SessionError("objective cannot change mid-concept")
        self.register_question()
        self.data["evidence"] = evidence
        self.data["current_concept"] = concept_id
        self.data["current_question"] = question
        self.data["is_transfer_question"] = is_transfer
        self.data["attempt"] = 1
        self.data["hint_level"] = 0
        self.data["status"] = "waiting_answer"

    def advance_attempt(self, hint_level: int) -> None:
        if hint_level < 0:
            raise SessionError("invalid hint level")
        if hint_level:
            self.data["evidence"]["hints_used"] = True
        self.data["attempt"] = int(self.data.get("attempt", 1)) + 1
        self.data["hint_level"] = hint_level
        self.data["status"] = "waiting_answer"

    def record_answer(self, verdict: str, *, hinted: bool = False) -> None:
        """Record an externally evaluated answer, without inventing an evaluation."""
        if verdict not in ("correct", "partial", "wrong"):
            raise SessionError("invalid verdict")
        if self.status != "waiting_answer" or not self.data.get("current_question"):
            raise SessionError("no unanswered question")
        evidence = self.data.get("evidence")
        if not evidence or evidence["concept_id"] != self.current_concept:
            raise SessionError("missing concept evidence")
        hinted = hinted or self.hint_level > 0
        evidence["hints_used"] = evidence["hints_used"] or hinted
        if self.data.get("is_transfer_question"):
            if verdict != "correct" or hinted:
                evidence["transfer_first_failed"] = True
            evidence["transfer"] = "passed" if verdict == "correct" and not hinted else "failed"
        else:
            if evidence["first_attempt"] is None:
                evidence["first_attempt"] = "wrong" if hinted else verdict
            evidence["latest"] = verdict
        self.data["status"] = "answer_received"

    def closure_decision(self, extension: str = "same_concept", budget_exhausted: bool = False):
        from progression import decide_next
        e = self.data.get("evidence")
        if not e or e.get("first_attempt") is None or self.status not in ("answer_received", "diagnosing"):
            raise SessionError("evaluated first attempt required")
        return decide_next(e["first_attempt"], e["latest"], e["transfer"],
                           extension=extension, budget_exhausted=budget_exhausted,
                           transfer_first_failed=e["transfer_first_failed"],
                           hints_used=e["hints_used"], objective=e["objective"])

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
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(self.to_json())
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))
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
        if self.status == "paused":
            return
        self.data["resume_status"] = self.status
        self.data["active_seconds"] = self.active_elapsed_seconds()
        self.data["active_since_epoch"] = None
        self.data["status"] = "paused"
        self.save(path)

    def resume(self, path: Path = ACTIVE_SESSION_PATH) -> None:
        if self.status != "paused":
            raise SessionError("session is not paused")
        self.data["status"] = self.data.pop("resume_status", "waiting_answer" if self.data.get("current_question") else "asking")
        if self.data["status"] == "waiting_answer" and not self.data.get("evidence"):
            # Legacy sessions stored a question but no verdict; keep the question,
            # never invent an answer or a higher objective during migration.
            self.data["evidence"] = {"concept_id": self.current_concept, "objective": "L1",
                "first_attempt": None, "latest": None, "hints_used": False,
                "transfer": "not_asked", "transfer_first_failed": False}
            self.data["is_transfer_question"] = False
        self.data["active_since_epoch"] = _now_epoch()
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
        "active_seconds": 0,
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