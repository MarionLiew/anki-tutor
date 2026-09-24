"""Keep pytest session and event writes out of the installed AnkiTutor state."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# This runs before test modules import config/events/session. Their path constants
# (including function default arguments) are captured at import time.
_ISOLATED_ROOT = tempfile.TemporaryDirectory(prefix="ankitutor-pytest-")
_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))
os.environ["ANKITUTOR_STATE"] = _ISOLATED_ROOT.name
os.environ["ANKITUTOR_EVENTS_LOG"] = str(Path(_ISOLATED_ROOT.name) / "events.jsonl")


def pytest_unconfigure(config):
    _ISOLATED_ROOT.cleanup()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Redirect both copied module constants and bound session defaults per test."""
    import config
    import events
    import session

    state = tmp_path / "state"
    event_log = state / "events.jsonl"
    active = state / "active_session.json"
    monkeypatch.setenv("ANKITUTOR_STATE", str(state))
    monkeypatch.setenv("ANKITUTOR_EVENTS_LOG", str(event_log))
    monkeypatch.setattr(config, "STATE_DIR", state)
    monkeypatch.setattr(config, "ACTIVE_SESSION_PATH", active)
    monkeypatch.setattr(config, "EVENTS_LOG_PATH", event_log)
    monkeypatch.setattr(events, "EVENTS_LOG_PATH", event_log)
    monkeypatch.setattr(session, "ACTIVE_SESSION_PATH", active)
    for method in (session.TutorSession.save, session.TutorSession.close,
                   session.TutorSession.pause, session.TutorSession.resume,
                   session.load_session, session.active_session_exists,
                   session.clear_session):
        monkeypatch.setattr(method, "__defaults__", (active,))
