"""Regression checks for pytest's state-write boundary."""

from pathlib import Path

import config
import events
import session


def test_direct_new_session_uses_test_event_log(tmp_path):
    expected = tmp_path / "state" / "events.jsonl"
    assert config.EVENTS_LOG_PATH == events.EVENTS_LOG_PATH == expected
    assert not expected.exists()

    created = session.new_session("quick_quiz")

    assert expected.exists()
    assert events.read_events()[-1]["session_id"] == created.session_id
    assert config.ACTIVE_SESSION_PATH == tmp_path / "state" / "active_session.json"
    assert Path(session.TutorSession.save.__defaults__[0]) == config.ACTIVE_SESSION_PATH
    assert Path(session.load_session.__defaults__[0]) == config.ACTIVE_SESSION_PATH
