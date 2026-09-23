"""Privacy and passive-review entry regressions."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import events
import passive_review
import session


def test_events_drop_arbitrary_payload_and_private_mode(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    monkeypatch.setattr(events, "EVENTS_LOG_PATH", path)
    rec = events.log_event("session_started", session_id="s1", mode="active_learning",
                           error="SECRET", source_text="SECRET")
    assert rec["mode"] == "active_learning"
    assert "SECRET" not in path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o777 == 0o600
    events.log_event("SECRET", token="SECRET")
    assert "SECRET" not in path.read_text(encoding="utf-8")


def test_event_log_rotates_at_fixed_budget(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    monkeypatch.setattr(events, "EVENTS_LOG_PATH", path)
    monkeypatch.setattr(events, "MAX_LOG_BYTES", 180)
    for index in range(30):
        events.log_event("session_saved", session_id=str(index), status="paused")
    assert path.stat().st_size <= 180
    assert (tmp_path / "events.jsonl.1").exists()
    assert not (tmp_path / "events.jsonl.4").exists()


def test_session_private_mode(tmp_path):
    s = session.new_session("quick_quiz")
    path = tmp_path / "active.json"
    s.save(path)
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] == s.session_id
    assert path.stat().st_mode & 0o777 == 0o600


def test_passive_review_starts_without_fabricated_question(tmp_path, monkeypatch):
    path = tmp_path / "active.json"
    monkeypatch.setattr(passive_review, "load_session", lambda: session.load_session(path))
    monkeypatch.setattr(session, "ACTIVE_SESSION_PATH", path)
    # save() default bound path is defined at import time; bind it here for this test.
    original_save = session.TutorSession.save
    monkeypatch.setattr(session.TutorSession, "save", lambda self, path=path: original_save(self, path))
    note = {"fields": {k: {"value": v} for k, v in {
        "ConceptID": "topic.mde", "Title": "MDE", "CoreKnowledge": "effect",
        "LearningObjective": "distinguish", "Level": "L1", "Status": "active"}.items()},
        "noteId": 1, "_card_ids": [42]}
    client = Mock()
    client.due_concepts.return_value = [note]
    monkeypatch.setattr(passive_review, "AnkiClient", lambda: client)
    started = passive_review.run()
    saved = session.load_session(path)
    assert saved is not None
    assert started["action"] == "start"
    assert saved.status == "asking" and saved.questions_used == 0
    assert saved.data["current_question"] == ""
    saved.set_current_question("topic.mde", "What is MDE?")
    saved.save(path)
    assert passive_review.run()["action"] == "resume"
    saved.pause(path)
    assert passive_review.run()["action"] == "resume"
