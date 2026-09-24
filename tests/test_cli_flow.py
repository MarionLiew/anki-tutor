"""CLI contract for strategic choice and evidence-bound session flow."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cli import main


def call(capsys, argv):
    status = main(argv)
    out = capsys.readouterr()
    return status, json.loads(out.out if status == 0 else out.err)


def test_cli_session_evidence_pause_resume_and_gate(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    code, goal = call(capsys, ["strategy", "show"])
    assert code == 0 and goal["status"] == "unconfirmed"
    code, start = call(capsys, ["session", "start", "topic.alpha", "--task", "evaluate baseline"])
    assert code == 0 and start["strategy_revision"] is None
    sid = start["session_id"]
    assert call(capsys, ["session", "ask", "topic.alpha", "Explain", "--objective", "L2"])[0] == 0
    code, first = call(capsys, ["session", "answer", "wrong"])
    assert code == 0 and first["decision"]["action"] == "repair_current"
    assert call(capsys, ["session", "hint"])[0] == 0
    code, corrected = call(capsys, ["session", "answer", "correct"])
    assert code == 0 and corrected["decision"]["action"] == "ask_transfer"
    assert call(capsys, ["session", "pause"])[0] == 0
    code, resumed = call(capsys, ["session", "resume"])
    assert code == 0 and resumed["session_id"] == sid and resumed["current_question"] == "Explain"
    assert call(capsys, ["session", "ask", "topic.alpha", "Apply elsewhere", "--objective", "L2", "--transfer"])[0] == 0
    code, done = call(capsys, ["session", "answer", "correct"])
    assert code == 0 and done["decision"] == {"action": "close_concept", "grade": 1}


def test_cli_cannot_grade_without_evidence(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    code, error = call(capsys, ["grade", "topic.alpha", "3"])
    assert code == 1 and "no active session evidence" in error["error"]


def test_new_concept_requires_completed_grade(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    call(capsys, ["session", "start", "topic.alpha"])
    call(capsys, ["session", "ask", "topic.alpha", "Q"])
    call(capsys, ["session", "answer", "correct"])
    code, error = call(capsys, ["session", "ask", "topic.gold", "Next"])
    assert code == 1 and "grade or pause" in error["error"]


def test_cli_full_flow_with_mocked_anki(tmp_path, monkeypatch, capsys):
    from unittest.mock import Mock
    import cli
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    client = Mock()
    monkeypatch.setattr(cli, "AnkiClient", lambda: client)
    monkeypatch.setattr(cli.ConceptService, "get", lambda self, cid: {"card_ids": [42]})
    _, goal = call(capsys, ["strategy", "show"])
    assert goal["status"] == "unconfirmed"
    assert call(capsys, ["grade", "topic.mde", "3"])[0] == 1
    call(capsys, ["session", "start", "topic.mde"])
    call(capsys, ["session", "ask", "topic.mde", "What does MDE mean?", "--objective", "L2"])
    assert call(capsys, ["session", "answer", "wrong"])[1]["decision"]["action"] == "repair_current"
    call(capsys, ["session", "hint"])
    assert call(capsys, ["session", "answer", "correct"])[1]["decision"]["action"] == "ask_transfer"
    call(capsys, ["session", "pause"])
    assert call(capsys, ["session", "resume"])[1]["status"] == "answer_received"
    call(capsys, ["session", "ask", "topic.mde", "New case", "--objective", "L2", "--transfer"])
    assert call(capsys, ["session", "answer", "correct"])[1]["decision"] == {"action": "close_concept", "grade": 1}
    assert call(capsys, ["grade", "topic.mde", "3"])[0] == 1
    code, result = call(capsys, ["grade", "topic.mde", "1"])
    assert code == 0 and result["ok"]
    client.grade_card.assert_called_once_with(42, 1)
    assert call(capsys, ["grade", "topic.mde", "1"])[0] == 1
    assert call(capsys, ["session", "close"])[0] == 0
    assert not (tmp_path / "active_session.json").exists()
    assert call(capsys, ["strategy", "show"])[1]["status"] == "unconfirmed"


def test_learning_lifecycle_records_reasons(tmp_path, monkeypatch, capsys):
    import events
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    monkeypatch.setattr(events, "EVENTS_LOG_PATH", tmp_path / "events.jsonl")
    call(capsys, ["session", "start", "topic.mde"])
    _, paused = call(capsys, ["session", "pause", "--reason", "topic_switch"])
    assert paused["pause_reason"] == "topic_switch"
    call(capsys, ["session", "resume"])
    assert "pause_reason" not in call(capsys, ["session", "show"])[1]
    call(capsys, ["session", "pause", "--reason", "user_request"])
    call(capsys, ["session", "close", "--reason", "user_request"])
    records = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    transitions = [(r["event"], r.get("reason")) for r in records if r["event"].startswith("learning_")]
    assert transitions == [("learning_entered", "user_request"),
                           ("learning_paused", "topic_switch"),
                           ("learning_resumed", "user_request"),
                           ("learning_paused", "user_request"),
                           ("learning_exited", "user_request")]


def test_cli_observe_auto_bind_scoped_chat(tmp_path, monkeypatch, capsys):
    import observation
    import cli
    from test_observation import make_db
    db = tmp_path / "state.db"
    make_db(db)
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path / "learning"))
    monkeypatch.setenv("HERMES_SESSION_ID", "selected")
    monkeypatch.setenv("HERMES_SESSION_PROFILE", "default")
    monkeypatch.setenv("HERMES_SESSION_SOURCE", "desktop")
    monkeypatch.setattr(observation, "db_path", lambda: db)
    call(capsys, ["session", "start", "topic.mde"])
    # New user/assistant turns after the learning entry are read from Hermes
    # on demand. The raw text is not copied into AnkiTutor state/log files.
    import sqlite3
    con = sqlite3.connect(db)
    con.execute("INSERT INTO messages VALUES (8,'selected','user','What is MDE?',1,0)")
    con.execute("INSERT INTO messages VALUES (9,'other','user','PRIVATE OTHER CHAT',1,0)")
    con.commit(); con.close()
    code, result = call(capsys, ["observe", "show"])
    assert code == 0 and result["chat_scope"] == "active_learning_segment_only"
    assert result["chat_excerpts"] == [{"id": 8, "role": "user", "excerpt": "What is MDE?"}]
    call(capsys, ["session", "pause", "--reason", "topic_switch"])
    con = sqlite3.connect(db)
    con.execute("INSERT INTO messages VALUES (10,'selected','user','UNRELATED AFTER PAUSE',1,0)")
    con.commit(); con.close()
    assert "UNRELATED AFTER PAUSE" not in json.dumps(call(capsys, ["observe", "show"])[1])
    call(capsys, ["session", "resume"])
    con = sqlite3.connect(db)
    con.execute("INSERT INTO messages VALUES (11,'selected','user','Back to MDE',1,0)")
    con.commit(); con.close()
    assert call(capsys, ["observe", "show"])[1]["chat_excerpts"] == [
        {"id": 11, "role": "user", "excerpt": "Back to MDE"}]
    assert "What is MDE?" not in (tmp_path / "learning" / "active_session.json").read_text()
    call(capsys, ["observe", "issue", "revealed_answer_too_early"])
    assert call(capsys, ["observe", "show"])[1]["mentor_issues"]["revealed_answer_too_early"] == 1


def test_goal_revision_blocks_stale_resume(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    _, proposed = call(capsys, ["strategy", "propose", "alpha", "--outcome", "alpha hypothesis", "--criterion", "baseline checked"])
    _, confirmed = call(capsys, ["strategy", "confirm", "--revision", str(proposed["revision"])])
    _, started = call(capsys, ["session", "start", "topic.alpha"])
    assert started["strategy_revision"] == confirmed["revision"]
    call(capsys, ["session", "pause"])
    call(capsys, ["strategy", "revise", "gold", "--revision", str(confirmed["revision"]), "--outcome", "gold hypothesis", "--criterion", "baseline checked"])
    code, error = call(capsys, ["session", "resume"])
    assert code == 1 and "align session" in error["error"]
    _, shown = call(capsys, ["session", "show"])
    assert shown["goal_needs_review"] is True
