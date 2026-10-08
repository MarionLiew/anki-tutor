import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from session import new_session

def test_waiting_wall_clock_is_not_learning_time():
    s = new_session('active_learning')
    s.data['started_at_epoch'] = 0
    s.data['active_since_epoch'] = 0
    assert s.active_elapsed_seconds() == 0
    assert s.can_continue()

def test_transfer_latest_correct_preserves_first_failure():
    s = new_session('active_learning')
    s.set_current_question('x', 'q', objective='L2')
    s.record_answer('correct')
    s.set_current_question('x', 't', objective='L2', is_transfer=True)
    s.record_answer('wrong')
    s.advance_attempt(1)
    s.record_answer('correct')
    # The learner produced the answer only after a hint: assisted, not verified.
    assert s.data['evidence']['transfer'] == 'assisted_correct'
    assert s.data['evidence']['transfer_first_failed'] is True
    # An assisted transfer therefore does not close the concept: one more
    # independent transfer is required before any grade is written.
    assert s.closure_decision().action == 'ask_transfer'
    s.set_current_question('x', 't2', objective='L2', is_transfer=True)
    s.record_answer('correct')
    assert s.data['evidence']['transfer'] == 'passed'
    assert s.closure_decision().grade == 1  # the first failure still forces Again


def test_cli_full_loop_isolated(tmp_path, monkeypatch):
    import cli
    from unittest.mock import Mock
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    client = Mock()
    client.review_history.side_effect = [[], [{"id": 1, "ease": 3}]]
    monkeypatch.setattr(cli, 'AnkiClient', lambda: client)
    monkeypatch.setattr(cli.ConceptService, 'get', lambda self, cid: {'card_ids': [42], 'note_id': 24})
    for args in [['session','start','test.concept'], ['session','ask','test.concept','Explain'],
                 ['session','answer','correct'], ['grade','test.concept','3'],
                 ['session','close']]:
        assert cli.main(args) == 0
    client.grade_card.assert_called_once_with(42, 3)
    assert not (tmp_path / 'active_session.json').exists()
    assert list((tmp_path / 'closed_sessions').glob('*.json'))


def test_missing_card_closes_ungraded(tmp_path, monkeypatch):
    import cli, json
    from unittest.mock import Mock
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    monkeypatch.setattr(cli, 'AnkiClient', Mock)
    monkeypatch.setattr(cli.ConceptService, 'get', lambda self, cid: None)
    assert cli.main(['session','start','missing']) == 0
    assert cli.main(['session','close','--reason','missing_concept']) == 0
    archived = json.loads(next((tmp_path/'closed_sessions').glob('*.json')).read_text())
    assert archived['closure_outcome'] == 'ungraded_no_mastery_claim'


def test_cron_skips_answered(monkeypatch):
    import passive_review
    s = new_session('active_learning')
    s.set_current_question('x','q')
    s.record_answer('correct')
    monkeypatch.setattr(passive_review, 'load_session', lambda: s)
    assert passive_review.run()['reason'] == 'question_already_answered'

