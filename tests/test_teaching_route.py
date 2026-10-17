"""Teaching advice derives from session evidence, never upgrades capability."""
import json
from session import new_session
from progression import decide_next


def test_failed_transfer_requires_repair_even_when_base_answer_correct():
    assert decide_next('partial', 'correct', 'failed', objective='L2').action == 'repair_current'


def test_entry_is_integrated_diagnostic_not_definition():
    s = new_session('active_learning')
    s.data['task'] = 'audit a research hypothesis'
    advice = s.teaching_guidance()
    assert advice['action'] == 'integrated_diagnostic'
    assert advice['task'] == s.data['task']
    assert advice['active_seconds'] is None
    assert advice['capability_claim'] == 'insufficient_evidence'


def test_failed_transfer_preserves_failure_and_repairs():
    s = new_session('active_learning')
    s.set_current_question('x', 'base', 'L2')
    s.record_answer('correct')
    s.set_current_question('x', 'new', 'L2', True)
    s.record_answer('wrong')
    assert s.teaching_guidance()['action'] == 'minimal_prerequisite_repair'
    assert s.data['evidence']['transfer_first_failed'] is True
    s.advance_attempt(0)
    s.record_answer('correct')
    assert s.closure_decision().grade == 1


def test_transfer_success_returns_to_task_not_level_upgrade():
    s = new_session('active_learning')
    s.data['task'] = 'original research'
    s.set_current_question('x', 'base', 'L2')
    s.record_answer('partial')
    s.advance_attempt(1)
    s.record_answer('correct')
    for q in ['new context one', 'new context two']:
        s.set_current_question('x', q, 'L2', True)
        s.record_answer('correct')
    advice = s.teaching_guidance()
    assert advice['action'] == 'return_to_original_task'
    assert advice['independent_transfers'] == 2
    assert advice['marginal_value'] == 'diminishing'
    assert advice['task'] == 'original research'
    assert advice['capability_claim'] == 'session_evidence_only'
    assert s.closure_decision().grade == 1


def test_guidance_pending_budget_and_legacy_are_conservative():
    s = new_session('active_learning')
    s.data['grade_state'] = 'pending'
    assert s.teaching_guidance()['action'] == 'blocked_pending_grade'
    s.data.pop('grade_state')
    s.set_current_question('x', 'base', 'L2')
    s.record_answer('wrong')
    s.data['questions_used'] = 8
    assert s.teaching_guidance()['action'] == 'close_with_gap'
    s.data['time_accounting'] = 'explicit'
    s.data['active_seconds'] = 45
    assert s.teaching_guidance()['active_seconds'] == 45
    s.data['answer_records'].append({'concept_id': 'x', 'verdict': 'correct', 'question': 'legacy'})
    assert s.teaching_guidance()['independent_transfers'] == 0


def test_corrected_transfer_requires_fresh_evidence_in_guidance():
    s = new_session('active_learning')
    s.set_current_question('x', 'base', 'L2')
    s.record_answer('correct')
    s.set_current_question('x', 'transfer', 'L2', True)
    s.record_answer('wrong')
    s.advance_attempt(0)
    s.record_answer('correct')
    assert s.teaching_guidance()['action'] == 'fresh_independent_transfer'
    assert s.teaching_guidance()['independent_transfers'] == 0
    assert s.closure_decision().grade == 1


def test_cli_guidance_is_read_only(tmp_path, monkeypatch, capsys):
    from cli import main
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    assert main(['session', 'start', 'x', '--task', 'research']) == 0
    capsys.readouterr()
    p = tmp_path / 'active_session.json'
    before = p.read_bytes()
    assert main(['session', 'guidance']) == 0
    assert json.loads(capsys.readouterr().out)['action'] == 'integrated_diagnostic'
    assert p.read_bytes() == before
