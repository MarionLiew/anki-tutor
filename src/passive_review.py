"""passive_review.py — deterministic Phase-3 entry point for Cron.

Does everything that must NOT be left to improvisation (doc §8):
  1. Existing foreground -> skip without resending; paused -> dormant snapshot.
  2. Else query due + active Concepts (max 3).
  3. Else if none due -> report "nothing to teach" and stop.
  4. Else create a Review Session, persist it, and emit the FIRST concept's
     payload for Default Bot to turn into ONE question.

It does NOT generate the question, decide mastery, change Level, or push
more than the first item — those are the LLM's + the user's job (§8.1).
When AnkiConnect is unreachable it says so plainly; it never fabricates state.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anki_client import AnkiClient, AnkiConnectUnreachable  # noqa: E402
from concept_service import note_to_concept  # noqa: E402
from config import DECK, SESSION_POLICY, ensure_dirs  # noqa: E402
from events import log_event
from session import load_session, new_session, park_session, assert_safe_snapshots, state_lock, SessionError
import observation  # noqa: E402
import strategy  # noqa: E402


PAUSED_REMINDER_AFTER_SECONDS = 24 * 60 * 60


def session_path() -> Path:
    from config import ACTIVE_SESSION_PATH
    return Path(os.environ.get("ANKITUTOR_STATE", str(ACTIVE_SESSION_PATH.parent))) / "active_session.json"


def run(limit: int = SESSION_POLICY["target_concepts"], now_epoch: float | None = None) -> dict:
    with state_lock(session_path()):
        try:
            assert_safe_snapshots(session_path())
            return _run(limit, now_epoch)
        except SessionError as exc:
            return {"action": "skip", "reason": "unsafe_session_state", "error": str(exc)}


def _run(limit: int, now_epoch: float | None) -> dict:
    if type(limit) is not int or limit < 1:
        raise SessionError("review limit must be a positive integer")
    limit = min(limit, SESSION_POLICY["target_concepts"])
    ensure_dirs()

    # 1. Preserve one foreground, never double-create or infer delivery.
    active = load_session()
    if active and active.data.get("grade_state") == "pending":
        return {"action": "skip", "reason": "pending_grade", "session_id": active.session_id}
    if active and active.status == "paused":
        park_session(active, session_path())
        active = None
    if active and active.status in ("answer_received", "diagnosing", "graded"):
        return {"action": "skip", "reason": "question_already_answered",
                "session_id": active.session_id}
    if active and active.status in ("asking", "waiting_answer", "verifying_transfer"):
        return {
            "action": "skip",
            "reason": "foreground_session_exists",
            "session_id": active.session_id,
            "current_concept": active.current_concept,
            "current_question": active.data.get("current_question"),
            "attempt": active.attempt,
            "hint_level": active.hint_level,
            "questions_used": active.questions_used,
            "note": "existing foreground — do not resend its question or create a new session",
        }

    # 2. query due
    client = AnkiClient()
    try:
        due_notes = client.due_concepts(deck=DECK, limit=limit)
    except AnkiConnectUnreachable as e:
        log_event("passive_review_unreachable", error=str(e))
        return {"action": "skip", "reason": "anki_unreachable", "error": str(e)}

    if not due_notes:
        for file in sorted((session_path().parent / "paused_sessions").glob("*.json")):
            from session import load_session as load_snapshot
            paused = load_snapshot(file)
            now = time.time() if now_epoch is None else now_epoch
            stamp = paused.data.get("paused_at_epoch")
            if stamp is not None and now - float(stamp) < PAUSED_REMINDER_AFTER_SECONDS:
                continue
            if paused.data.get("paused_reminder_prepared") or paused.data.get("paused_reminder_sent"):
                continue
            paused.data["paused_reminder_prepared"] = True
            paused.save(file)
            return {"action": "remind_paused", "reason": "paused_session_due_for_reminder",
                    "session_id": paused.session_id, "snapshot": file.stem,
                    "current_concept": paused.current_concept,
                    "current_question": paused.data.get("current_question"),
                    "note": "One optional light reminder prepared, NOT delivery evidence; keep snapshot dormant."}
        log_event("passive_review_no_due")
        return {"action": "skip", "reason": "no_due_concepts",
                "note": "no due Concepts — do not force teaching (§8.1)"}

    # 3. build queue + first concept payload
    concepts = []
    for n in due_notes:
        c = note_to_concept(n)
        if any(existing["concept_id"] == c["concept_id"] for existing in concepts):
            raise SessionError("duplicate ConceptID in due notes; reconcile identity before teaching")
        c["card_ids"] = n.get("_card_ids") or []
        concepts.append(c)
    queue = [c["concept_id"] for c in concepts]
    first = concepts[0]

    sess = new_session("passive_review", concept_queue=queue, concept=first)
    sess.data["track_id"] = None
    try:
        sess.data["observation_binding"] = observation.bind()
    except (ValueError, OSError):
        pass
    # The tutor has not generated/sent a question yet. Let `session ask` register it.
    sess.save()
    try:
        from config import STATE_DIR
        observation.record(STATE_DIR / "learning_observations.jsonl", "learning_entered",
                           session_id=sess.session_id, concept_id=first["concept_id"],
                           mode=sess.mode, reason="unknown")
    except OSError:
        pass
    log_event("learning_entered", session_id=sess.session_id, mode=sess.mode,
              concept_id=first["concept_id"], reason="unknown")
    log_event("passive_review_started", session_id=sess.session_id, concepts=queue)

    return {
        "action": "start",
        "session_id": sess.session_id,
        "concept_queue": queue,
        "current_concept": first["concept_id"],
        "concept": {
            "concept_id": first["concept_id"],
            "title": first["title"],
            "core_knowledge": first["core_knowledge"],
            "learning_objective": first["learning_objective"],
            "level": first["level"],
            "common_errors": first["common_errors"],
            "tutor_instruction": first["tutor_instruction"],
            "source_refs": first["source_refs"],
        },
        "policy": {
            "ask_only_first_question": True,
            "max_questions": SESSION_POLICY["max_questions"],
            "target_concepts": SESSION_POLICY["target_concepts"],
        },
        "strategy": strategy.show(),
        "next": "if strategy.should_ask_direction, first ask the user which line (alpha/Polymarket/gold) to prioritise; else generate ONE question for current_concept via prompts/question_generation.md and send it",
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))