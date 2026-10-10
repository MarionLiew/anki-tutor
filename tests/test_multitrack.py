"""Multi-track safety regressions, entirely isolated from live Anki."""
import json
import pytest
import strategy
import cli
import passive_review
import observation
from concept_service import ConceptService
from mock_anki import MockAnkiClient
from session import new_session, load_session, SessionError


def test_tracks_focus_and_migration(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    old = strategy.propose('alpha', 'independent experiment', 'audited artifact')
    strategy.confirm(1)
    strategy.roadmap_add('audit')
    strategy.roadmap_evidence('audit', 'independent report checked')
    original = json.loads((tmp_path / 'strategy.json').read_text())
    strategy.migrate()
    assert (tmp_path / 'strategy.legacy.bak').exists()
    assert strategy.list_tracks()['tracks'][0]['outcome'] == original['outcome']
    assert strategy.list_tracks()['tracks'][0]['roadmap'] == original['roadmap']
    assert strategy.migrate()['migrated'] is False
    strategy.create_track('b', 'Forecast', 'independent forecast', 'resolved audit')
    strategy.set_focus('b')
    strategy.confirm(1)
    strategy.set_focus('legacy')
    assert strategy.show()['roadmap'] == original['roadmap']
    strategy.set_track_status('legacy', 'completed', confirmed=True)
    assert strategy.show()['track_status'] == 'completed'


def test_pending_cannot_pause_close_or_switch(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    strategy.create_track('a', 'A', 'outcome', 'criterion')
    strategy.create_track('b', 'B', 'other', 'criterion')
    strategy.set_focus('a')
    s = new_session('active_learning', concept={'concept_id':'test.one'})
    s.data.update(track_id='a', grade_state='pending')
    s.save(tmp_path / 'active_session.json')
    for call in [lambda: s.pause(tmp_path / 'active_session.json'), lambda: s.close(tmp_path / 'active_session.json'), lambda: strategy.set_focus('b')]:
        with pytest.raises((SessionError, ValueError), match='pending'):
            call()
    assert load_session(tmp_path / 'active_session.json').data['grade_state'] == 'pending'


def test_switch_restores_all_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    strategy.create_track('a', 'A', 'outcome', 'criterion')
    strategy.create_track('b', 'B', 'other', 'criterion')
    strategy.set_focus('a')
    s = new_session('active_learning', concept={'concept_id':'test.one'})
    s.data['track_id'] = 'a'
    s.set_current_question('test.one', 'original', objective='L2')
    s.record_answer('wrong')
    s.advance_attempt(1)
    s.data['hint_sent_at'] = '2026-10-01T00:00:00+00:00'
    s.save(tmp_path / 'active_session.json')
    saved = dict(s.data['evidence'])
    strategy.set_focus('b')
    assert load_session(tmp_path / 'active_session.json') is None
    strategy.set_focus('a')
    resumed = load_session(tmp_path / 'active_session.json')
    assert resumed.status == 'waiting_answer'
    assert resumed.data['current_question'] == 'original'
    assert resumed.data['evidence'] == saved
    assert resumed.data['hint_sent_at'] == s.data['hint_sent_at']


def test_changed_outcome_does_not_inherit_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    strategy.propose('same', 'old outcome', 'criterion')
    strategy.confirm(1)
    strategy.roadmap_add('audit')
    strategy.roadmap_evidence('audit', 'old report')
    result = strategy.revise('same', 1, 'new outcome', 'criterion')
    assert result['roadmap'] == []
    assert result['history'][0]['roadmap'][0]['evidence'] == 'old report'


def test_tags_and_lifecycle_do_not_duplicate_or_suspend(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    for tid in ('a', 'b'):
        strategy.create_track(tid, tid, 'outcome', 'criterion')
    client = MockAnkiClient()
    svc = ConceptService(client)
    c = svc.create({'concept_id':'test.one', 'title':'one', 'core_knowledge':'core', 'learning_objective':'judge', 'level':'L0'})
    client.add_tags([c['note_id']], ['user::keep'])
    svc.link_track('test.one', 'a')
    svc.link_track('test.one', 'b')
    svc.link_track('test.one', 'a')
    assert len(client._notes) == len(client._cards) == 1
    assert len(svc.search(track_id='a')) == 1
    before = json.dumps(client._cards, sort_keys=True)
    strategy.set_track_status('a', 'completed', confirmed=True)
    strategy.set_track_status('b', 'archived', confirmed=True)
    assert json.dumps(client._cards, sort_keys=True) == before
    assert 'track::a' in svc.get('test.one')['tags']
    svc.unlink_track('test.one', 'a')
    assert set(svc.get('test.one')['tags']) >= {'track::b', 'user::keep'}
    svc.update({'concept_id':'test.one','title':'changed'})
    assert 'track::b' in svc.get('test.one')['tags']


def test_cron_due_all_tracks_and_paused_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE', str(tmp_path))
    client = MockAnkiClient()
    svc = ConceptService(client)
    for tid in ('a','b'):
        strategy.create_track(tid, tid, 'outcome', 'criterion')
    strategy.set_focus('a')
    for cid in ('test.completed','test.archived','test.independent'):
        svc.create({'concept_id':cid,'title':cid,'core_knowledge':'core','learning_objective':'judge'})
    svc.link_track('test.completed', 'a')
    svc.link_track('test.archived', 'b')
    strategy.set_track_status('a','completed',True)
    strategy.set_track_status('b','archived',True)
    path = tmp_path / 'active_session.json'
    s = new_session('active_learning',concept={'concept_id':'test.old'})
    s.data['track_id']='a'
    s.set_current_question('test.old','old question')
    s.pause(path)
    monkeypatch.setattr(passive_review,'AnkiClient',lambda:client)
    monkeypatch.setattr(passive_review,'load_session',lambda:load_session(path))
    monkeypatch.setattr(passive_review,'session_path',lambda:path)
    original_save = type(s).save
    monkeypatch.setattr(type(s),'save',lambda self,path=path:original_save(self,path))
    result = passive_review.run()
    assert result['action'] == 'start'
    assert set(result['concept_queue']) == {'test.completed','test.archived','test.independent'}
    assert load_session(tmp_path / 'paused_sessions' / 'a.json').data['current_question'] == 'old question'
    assert passive_review.run()['action'] == 'skip'


def test_assisted_transfer_cli_and_observation(tmp_path):
    assert cli.main(['next','--first','wrong','--latest','correct','--transfer','assisted_correct','--objective','L2']) == 0
    assert observation.record(tmp_path/'obs.jsonl','transfer_checked',transfer='assisted_correct')['transfer'] == 'assisted_correct'


def test_cli_track_pause_and_resume(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE',str(tmp_path))
    assert cli.main(['strategy','create','a','A','--outcome','outcome','--criterion','criterion']) == 0
    assert cli.main(['strategy','focus','a']) == 0
    assert cli.main(['session','start','test.one']) == 0
    assert cli.main(['session','ask','test.one','question']) == 0
    assert cli.main(['session','pause']) == 0
    assert load_session(tmp_path/'active_session.json') is None
    assert cli.main(['session','resume','--snapshot','a']) == 0
    assert load_session(tmp_path/'active_session.json').status == 'waiting_answer'


def test_pending_snapshot_blocks_all_new_teaching(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE',str(tmp_path))
    path = tmp_path/'paused_sessions'/'a.json'
    s = new_session('active_learning',concept={'concept_id':'test.one'})
    s.data.update(track_id='a',grade_state='pending',status='paused')
    s.save(path)
    assert cli.main(['session','start','test.two','--temporary']) == 1
    monkeypatch.setattr(passive_review,'session_path',lambda:tmp_path/'active_session.json')
    assert passive_review.run()['reason'] == 'unsafe_session_state'


def test_corrupt_foreground_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE',str(tmp_path))
    path = tmp_path/'active_session.json'
    path.write_text('{broken')
    assert cli.main(['session','start','test.two']) == 1
    assert path.read_text() == '{broken'


def test_snapshot_resume_checks_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE',str(tmp_path))
    strategy.create_track('a','A','old','criterion')
    strategy.set_focus('a')
    strategy.confirm(1)
    assert cli.main(['session','start','test.one']) == 0
    assert cli.main(['session','pause']) == 0
    strategy.revise('A',1,'new','criterion')
    assert cli.main(['session','resume','--snapshot','a']) == 1
    assert (tmp_path/'paused_sessions'/'a.json').exists()


def test_import_exam_uses_targets_not_unverified_levels(tmp_path, monkeypatch):
    import runpy
    import anki_client, source_library, ingest
    client = MockAnkiClient()
    svc = ConceptService(client)
    svc.create({'concept_id':'quantos.research.mde_definition','title':'old','core_knowledge':'core','learning_objective':'objective','level':'L1'},verified_level=True)
    monkeypatch.setattr(anki_client,'AnkiClient',lambda:client)
    monkeypatch.setattr(source_library,'SourceLibrary',lambda path:object())
    class FakeIngest:
        def __init__(self,lib): pass
        def ingest(self,*args,**kwargs):
            return {'source_id':'source-test','hash':'123456789abcdef','candidate_count':7}
    monkeypatch.setattr(ingest,'IngestService',FakeIngest)
    from pathlib import Path
    runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts'/'import_exam_review.py'))
    assert svc.get('quantos.research.mde_definition')['level'] == 'L1'
    assert svc.get('quantos.contract.minimal_prediction_contract')['level'] == 'L0'
    assert svc.get('quantos.contract.minimal_prediction_contract')['target_level'] == 'L3'


def test_new_session_save_cannot_overwrite_foreground(tmp_path):
    path = tmp_path/'active_session.json'
    a = new_session('active_learning',concept={'concept_id':'test.one'})
    a.data['grade_state']='pending'
    a.save(path)
    b = new_session('active_learning',concept={'concept_id':'test.two'})
    with pytest.raises(SessionError,match='foreground|pending'):
        b.save(path)
    assert load_session(path).session_id == a.session_id


def test_replaced_roadmap_evidence_is_retained(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE',str(tmp_path))
    strategy.propose('a','outcome','criterion')
    strategy.confirm(1)
    strategy.roadmap_add('audit')
    strategy.roadmap_evidence('audit','first independent report')
    cleared = strategy.roadmap_evidence('audit','',status='no_evidence')
    assert cleared['roadmap'][0]['evidence_history'][0]['evidence'] == 'first independent report'


def test_expired_reproposal_keeps_previous_goal_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE',str(tmp_path))
    strategy.propose('a','old','criterion')
    strategy.confirm(1)
    strategy.roadmap_add('audit')
    strategy.roadmap_evidence('audit','independent report')
    strategy.expire(1)
    result = strategy.propose('b','new','new criterion')
    assert result['history'][0]['roadmap'][0]['evidence'] == 'independent report'


def test_closed_pending_corruption_is_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv('ANKITUTOR_STATE',str(tmp_path))
    (tmp_path/'active_session.json').write_text(json.dumps({'status':'closed','grade_state':'pending','session_id':'old'}))
    assert cli.main(['session','start','test.two']) == 1


def test_real_client_due_query_and_status_filter():
    from anki_client import AnkiClient
    from unittest.mock import Mock
    client = AnkiClient()
    client.find_cards = Mock(return_value=[1,2,3,4])
    client.cards_info = Mock(return_value=[{'cardId':i,'note':i,'queue':0} for i in range(1,5)])
    client.notes_info = Mock(return_value=[{'noteId':i,'fields':{'Status':{'value':status}},'tags':tags} for i,status,tags in [(1,'active',[]),(2,'active',['track::completed']),(3,'active',['track::archived']),(4,'retired',[])]])
    due = client.due_concepts(limit=3)
    assert [n['noteId'] for n in due] == [1,2,3]
    query = client.find_cards.call_args[0][0]
    assert '-is:suspended' in query and 'tag:' not in query and 'track' not in query
