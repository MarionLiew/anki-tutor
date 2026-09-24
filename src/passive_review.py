"""passive_review.py — deterministic Phase-3 entry point for Cron.

Does everything that must NOT be left to improvisation (doc §8):
  1. If an active Review Session exists -> resume it (never create a second).
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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anki_client import AnkiClient, AnkiConnectUnreachable  # noqa: E402
from concept_service import note_to_concept  # noqa: E402
from config import DECK, SESSION_POLICY, ensure_dirs  # noqa: E402
from events import log_event  # noqa: E402
from session import load_session, new_session  # noqa: E402
import observation  # noqa: E402


def run(limit: int = SESSION_POLICY["target_concepts"]) -> dict:
    ensure_dirs()

    # 1. resume, never double-create
    active = load_session()
    if active and active.status in ("asking", "waiting_answer", "answer_received",
                                    "diagnosing", "verifying_transfer", "graded", "paused"):
        return {
            "action": "resume",
            "session_id": active.session_id,
            "current_concept": active.current_concept,
            "current_question": active.data.get("current_question"),
            "attempt": active.attempt,
            "hint_level": active.hint_level,
            "questions_used": active.questions_used,
            "note": "existing session — resume, do not create a new one",
        }

    # 2. query due
    client = AnkiClient()
    try:
        due_notes = client.due_concepts(deck=DECK, limit=limit)
    except AnkiConnectUnreachable as e:
        log_event("passive_review_unreachable", error=str(e))
        return {"action": "skip", "reason": "anki_unreachable", "error": str(e)}

    if not due_notes:
        log_event("passive_review_no_due")
        return {"action": "skip", "reason": "no_due_concepts",
                "note": "no due Concepts — do not force teaching (§8.1)"}

    # 3. build queue + first concept payload
    concepts = []
    for n in due_notes:
        c = note_to_concept(n)
        c["card_ids"] = n.get("_card_ids") or []
        concepts.append(c)
    queue = [c["concept_id"] for c in concepts]
    first = concepts[0]

    sess = new_session("passive_review", concept_queue=queue, concept=first)
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
        "next": "generate ONE question for current_concept via prompts/question_generation.md and send it",
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))