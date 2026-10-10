"""Paused sessions stay paused, but must not suppress reminders forever."""
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import passive_review
from session import new_session
import pytest
from mock_anki import MockAnkiClient


@pytest.fixture(autouse=True)
def isolated_cron(tmp_path, monkeypatch):
    monkeypatch.setattr(passive_review, "session_path", lambda: tmp_path / "active_session.json")
    monkeypatch.setattr(passive_review, "AnkiClient", lambda: MockAnkiClient())


def test_paused_session_is_silent_and_preserved(tmp_path, monkeypatch):
    import session
    path = tmp_path / "active_session.json"
    monkeypatch.setattr(passive_review, "load_session", lambda: session.load_session(path))
    s = new_session("passive_review", concept={"concept_id": "topic.mde"})
    s.set_current_question("topic.mde", "What does MDE mean?")
    s.save(path)
    s.pause(path, reason="topic_switch")
    before = path.read_bytes()
    result = passive_review.run()
    assert result["action"] == "skip"
    assert result["reason"] == "no_due_concepts"
    assert not path.exists()
    snapshot = path.parent / "paused_sessions" / (s.session_id + ".json")
    assert snapshot.read_bytes() == before
    s = session.load_session(snapshot)
    assert s is not None
    assert s.status == "paused" and s.data["current_question"] == "What does MDE mean?"


def test_paused_session_gets_light_reminder_after_one_day(tmp_path, monkeypatch):
    import session
    path = tmp_path / "active_session.json"
    monkeypatch.setattr(passive_review, "load_session", lambda: session.load_session(path))
    s = new_session("passive_review", concept={"concept_id": "topic.mde"})
    s.set_current_question("topic.mde", "What does MDE mean?")
    s.save(path)
    s.pause(path, reason="topic_switch")
    before = path.read_bytes()

    result = passive_review.run(now_epoch=s.data["paused_at_epoch"] + 24 * 60 * 60)

    assert result["action"] == "remind_paused"
    assert result["reason"] == "paused_session_due_for_reminder"
    assert result["current_question"] == "What does MDE mean?"
    assert not path.exists()
    snapshot = path.parent / "paused_sessions" / (s.session_id + ".json")
    preserved = session.load_session(snapshot)
    assert preserved.status == "paused" and preserved.data["current_question"] == "What does MDE mean?"
    assert preserved.data["paused_reminder_prepared"] is True
    assert passive_review.run(now_epoch=s.data["paused_at_epoch"] + 48 * 60 * 60)["action"] == "skip"


def test_legacy_paused_session_without_timestamp_is_reminded(tmp_path, monkeypatch):
    import session
    path = tmp_path / "active_session.json"
    monkeypatch.setattr(passive_review, "load_session", lambda: session.load_session(path))
    s = new_session("passive_review", concept={"concept_id": "topic.mde"})
    s.set_current_question("topic.mde", "What does MDE mean?")
    s.save(path)
    s.pause(path, reason="topic_switch")
    s.data.pop("paused_at_epoch", None)
    s.save(path)

    result = passive_review.run(now_epoch=time.time())

    assert result["action"] == "remind_paused"