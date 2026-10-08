import copy
from unittest.mock import Mock
import pytest
from session import new_session, SessionError, load_session
from concept_service import ConceptService
from mock_anki import MockAnkiClient


def ready(tmp_path):
    c=MockAnkiClient(); svc=ConceptService(c)
    svc.create({'concept_id':'audit.receipt','title':'Receipt','core_knowledge':'K','learning_objective':'O'})
    s=new_session('quick_quiz'); s.set_current_question('audit.receipt','Question'); s.record_answer('correct')
    p=tmp_path/'session.json'; s.save(p)
    return c,svc,s,p


def test_grade_reads_exact_revlog(tmp_path):
    c,svc,s,p=ready(tmp_path); svc.grade('audit.receipt',3,session=s,path=p)
    assert s.data['grade_receipt']['review']['ease']==3
    assert load_session(p).status=='graded'


def test_timeout_after_acceptance_reconciles_without_retry(tmp_path):
    c,svc,s,p=ready(tmp_path); original=c.grade_card
    def accepted(cid,ease):
        original(cid,ease); raise TimeoutError('lost reply')
    c.grade_card=Mock(side_effect=accepted)
    with pytest.raises(TimeoutError): svc.grade('audit.receipt',3,session=s,path=p)
    s=load_session(p); svc.reconcile_grade(s,p)
    assert c.grade_card.call_count==1 and s.status=='graded'


@pytest.mark.parametrize('rows',[[],[{'id':1,'ease':1}],[{'id':1,'ease':3},{'id':2,'ease':3}]])
def test_pending_absent_mismatch_ambiguous_stays_pending(tmp_path,rows):
    c,svc,s,p=ready(tmp_path); c.grade_card=Mock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError): svc.grade('audit.receipt',3,session=s,path=p)
    c.review_history=lambda cid: rows
    with pytest.raises(SessionError): svc.reconcile_grade(s,p)
    assert load_session(p).data['grade_state']=='pending'
    with pytest.raises(SessionError): s.set_current_question('audit.receipt','Overwrite?')
    with pytest.raises(SessionError): s.advance_attempt(1)
    assert c.grade_card.call_count==1


def test_legacy_pending_refuses_recovery(tmp_path):
    _,svc,s,p=ready(tmp_path); s.data['grade_state']='pending'; s.save(p)
    with pytest.raises(SessionError,match='legacy'): svc.reconcile_grade(s,p)


def test_rubric_requires_core_points_and_preserves_evidence():
    s=new_session('quick_quiz'); s.set_current_question('audit.mde','Compare CI to economic hurdle')
    rubric=[{'criterion':'economic threshold','met':False,'evidence':'learner omitted threshold comparison'}]
    before=copy.deepcopy(s.data)
    with pytest.raises(SessionError): s.record_answer('correct',rubric=rubric)
    assert s.data==before
    s.record_answer('partial',rubric=rubric,answer_text='not significant')
    assert s.data['answer_records'][0]['rubric']==rubric


def test_spontaneous_retry_not_hint_dependency():
    s=new_session('quick_quiz'); s.set_current_question('audit.mde','Q'); s.record_answer('partial')
    s.advance_attempt(0); s.record_answer('correct',spontaneous=True)
    assert not s.data['evidence']['hints_used']
    assert s.data['evidence']['first_attempt']=='partial'


def test_delivered_hint_cannot_be_spontaneous():
    s=new_session('quick_quiz'); s.set_current_question('audit.mde','Q'); s.record_answer('wrong')
    s.advance_attempt(1)
    with pytest.raises(SessionError): s.record_answer('correct',spontaneous=True)


def test_cli_hint_delivery_and_spontaneous_retry(tmp_path, monkeypatch):
    import cli
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    for args in [['session','start','audit.hint'], ['session','ask','audit.hint','Q'],
                 ['session','answer','partial'], ['session','hint']]:
        assert cli.main(args) == 0
    s=load_session(tmp_path/'active_session.json')
    assert not s.data['evidence']['hints_used'] and 'hint_sent_at' not in s.data
    assert cli.main(['session','hint','--sent-at','2026-01-01T00:00:00+00:00']) == 0
    s=load_session(tmp_path/'active_session.json')
    assert s.data['hint_sent_at']=='2026-01-01T00:00:00+00:00'
    assert cli.main(['session','answer','correct','--spontaneous']) == 1
    assert cli.main(['session','answer','correct']) == 0


def test_free_search_keeps_filters():
    c=MockAnkiClient(); svc=ConceptService(c)
    svc.create({'concept_id':'audit.mde','title':'MDE 裁决','core_knowledge':'K','learning_objective':'O','topic':'research'})
    assert len(svc.search(topic='research',level='L0',query='裁决'))==1
    assert svc.search(topic='other',query='MDE')==[]
