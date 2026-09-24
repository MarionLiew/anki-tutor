"""Scoped, bounded and read-only Hermes conversation observation."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def make_db(path):
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE sessions(id TEXT PRIMARY KEY, profile_name TEXT, source TEXT);
        CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
        content TEXT, active INTEGER, compacted INTEGER);""")
    con.execute("INSERT INTO sessions VALUES ('selected','default','desktop')")
    con.execute("INSERT INTO sessions VALUES ('other','default','desktop')")
    con.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?)", [
        (1, 'selected', 'user', 'start learning', 1, 0),
        (2, 'selected', 'user', 'MDE is a drawdown', 1, 0),
        (3, 'other', 'user', 'PRIVATE OTHER CHAT', 1, 0),
        (4, 'selected', 'tool', 'SECRET TOOL RESULT', 1, 0),
        (5, 'selected', 'assistant', 'Try contrasting effect and drawdown', 1, 0),
        (6, 'selected', 'user', 'sk-TESTPRIVATE12345678901234567890', 1, 0),
        (7, 'selected', 'user', 'ignored removed answer', 0, 0),
    ])
    con.commit()
    con.close()


def test_scoped_chat_and_no_raw_persistence(tmp_path, monkeypatch):
    import observation
    db = tmp_path / 'state.db'
    make_db(db)
    monkeypatch.setenv('HERMES_SESSION_ID', 'selected')
    monkeypatch.setenv('HERMES_SESSION_PROFILE', 'default')
    monkeypatch.setenv('HERMES_SESSION_SOURCE', 'desktop')
    marker = observation.bind(db)
    assert marker['after_id'] == 7
    entries = observation.read_range(db, {'session_id': 'selected', 'profile': 'default',
                                           'source': 'desktop', 'after_id': 1}, 7)
    text = json.dumps(entries)
    assert 'MDE is a drawdown' in text
    assert 'PRIVATE OTHER CHAT' not in text and 'SECRET TOOL RESULT' not in text
    assert 'sk-TESTPRIVATE' not in text
    assert len(entries) <= 20
    with pytest.raises(ValueError):
        observation.read_range(db, {'session_id': 'other', 'profile': 'default',
                                    'source': 'desktop', 'after_id': 0}, 7)


def test_excerpt_limits_and_profile_guard(tmp_path, monkeypatch):
    import observation
    db = tmp_path / 'state.db'
    make_db(db)
    monkeypatch.setenv('HERMES_SESSION_ID', 'selected')
    monkeypatch.setenv('HERMES_SESSION_PROFILE', 'other-profile')
    monkeypatch.setenv('HERMES_SESSION_SOURCE', 'desktop')
    with pytest.raises(ValueError):
        observation.bind(db)
    monkeypatch.setenv('HERMES_SESSION_PROFILE', 'default')
    con = sqlite3.connect(db)
    con.execute("INSERT INTO messages VALUES (8,'selected','user',?,1,0)", ('x' * 1000,))
    con.commit(); con.close()
    entries = observation.read_range(db, {'session_id': 'selected', 'profile': 'default',
                                          'source': 'desktop', 'after_id': 7}, 8)
    assert len(entries[0]['excerpt']) <= 301


def test_bounded_observation_metadata_and_issue(tmp_path):
    import observation
    path = tmp_path / 'observations.jsonl'
    observation.record(path, 'learning_entered', session_id='s1', concept_id='topic.mde',
                       reason='user_request', raw_answer='PRIVATE')
    observation.record(path, 'answer_evaluated', session_id='s1', verdict='wrong',
                       hinted=False, raw_answer='PRIVATE')
    observation.record(path, 'mentor_issue', session_id='s1', issue='revealed_answer_too_early')
    report = observation.report(path, session_id='s1')
    assert report['events'] == 3
    assert report['answer_verdicts']['wrong'] == 1
    assert report['mentor_issues']['revealed_answer_too_early'] == 1
    assert 'PRIVATE' not in path.read_text()
    with pytest.raises(ValueError):
        observation.record(path, 'mentor_issue', session_id='s1', issue='arbitrary personal text')


def test_observation_requires_explicit_session_binding(tmp_path, monkeypatch):
    import observation
    db = tmp_path / 'state.db'
    make_db(db)
    monkeypatch.delenv('HERMES_SESSION_ID', raising=False)
    with pytest.raises(ValueError):
        observation.bind(db)
