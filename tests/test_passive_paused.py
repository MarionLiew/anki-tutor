"""A cron tick must not re-ask a question explicitly paused by the learner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import passive_review
from session import new_session


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
    assert result["reason"] == "session_paused"
    assert result["pause_reason"] == "topic_switch"
    assert path.read_bytes() == before
    s = session.load_session(path)
    assert s is not None
    assert s.status == "paused" and s.data["current_question"] == "What does MDE mean?"