"""Offline, evidence-bound session and grading tests."""
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import session as session_module
from concept_service import ConceptService
from session import SessionError, load_session, new_session


def setup_session(tmp_path, objective="L1", verdict="correct"):
    path = tmp_path / "active.json"
    s = new_session("active_learning")
    s.set_current_question("topic.concept", "Explain", objective=objective)
    s.save(path)
    s.record_answer(verdict)
    s.save(path)
    return s, path


def test_l1_closes_without_transfer_but_l2_requires_it(tmp_path):
    l1, _ = setup_session(tmp_path)
    assert l1.closure_decision().grade == 3
    l2, path = setup_session(tmp_path / "second", objective="L2")
    assert l2.closure_decision().action == "ask_transfer"
    l2.set_current_question("topic.concept", "New situation", objective="L2", is_transfer=True)
    l2.record_answer("correct")
    l2.save(path)
    assert l2.closure_decision().grade == 3


def test_hint_and_first_failure_stay_again_after_transfer(tmp_path):
    s, path = setup_session(tmp_path, verdict="wrong")
    s.advance_attempt(1)
    s.record_answer("correct")
    assert s.closure_decision().action == "ask_transfer"
    s.set_current_question("topic.concept", "Transfer", is_transfer=True)
    s.record_answer("correct")
    assert s.closure_decision().grade == 1
    s.save(path)
    assert load_session(path).data["evidence"]["first_attempt"] == "wrong"


def test_pause_resume_excludes_wall_time_and_preserves_question(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(session_module, "_now_epoch", lambda: clock[0])
    s = new_session("quick_quiz")
    path = tmp_path / "active.json"
    s.set_current_question("topic.concept", "Q")
    clock[0] += 60
    s.pause(path)
    clock[0] += 3600
    s = load_session(path)
    assert s.active_elapsed_seconds() == pytest.approx(60)
    s.resume(path)
    assert s.status == "waiting_answer" and s.data["current_question"] == "Q"
    clock[0] += 60
    assert s.active_elapsed_seconds() == pytest.approx(120)


def test_legacy_paused_question_resumes_without_fabricated_verdict(tmp_path):
    path = tmp_path / "active.json"
    s = new_session("active_learning", concept={"concept_id": "topic.concept"})
    s.data.update(status="paused", current_question="Old question",
                  questions_used=1)
    s.data.pop("evidence", None)
    s.save(path)
    recovered = load_session(path)
    assert recovered is not None
    recovered.resume(path)
    assert recovered.data["evidence"]["first_attempt"] is None
    assert recovered.data["current_question"] == "Old question"
    recovered.record_answer("wrong")
    assert recovered.closure_decision().action == "repair_current"


def test_budget_blocks_registration_before_increment(tmp_path):
    s = new_session("quick_quiz")
    s.data["questions_used"] = 8
    with pytest.raises(SessionError):
        s.set_current_question("topic.concept", "Q")
    assert s.questions_used == 8 and s.current_concept is None


def test_grade_requires_persisted_evidence_and_is_once_only(tmp_path):
    s, path = setup_session(tmp_path)
    client = Mock()
    svc = ConceptService(client)
    svc.get = Mock(return_value={"card_ids": [42]})
    with pytest.raises(SessionError):
        svc.grade("topic.concept", 3, path=path)
    with pytest.raises(SessionError):
        svc.grade("topic.concept", 4, session=s, path=path)
    svc.grade("topic.concept", 3, session=s, path=path)
    client.grade_card.assert_called_once_with(42, 3)
    assert load_session(path).data["grade_state"] == "completed"
    with pytest.raises(SessionError):
        svc.grade("topic.concept", 3, session=s, path=path)
    client.grade_card.assert_called_once()


def test_uncertain_remote_result_is_not_retried(tmp_path):
    s, path = setup_session(tmp_path)
    client = Mock()
    client.grade_card.side_effect = TimeoutError("unknown remote outcome")
    svc = ConceptService(client)
    svc.get = Mock(return_value={"card_ids": [42]})
    with pytest.raises(TimeoutError):
        svc.grade("topic.concept", 3, session=s, path=path)
    assert load_session(path).data["grade_state"] == "pending"
    with pytest.raises(SessionError):
        svc.grade("topic.concept", 3, session=load_session(path), path=path)
    client.grade_card.assert_called_once()
