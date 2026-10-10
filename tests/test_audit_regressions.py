"""Regressions for the issues raised in the 2026-10 project audit.

Each test pins one audited defect so it cannot silently return:
  * ConceptID lookup must never resolve to a different note
  * duplicate ConceptID must stop the caller, not pick one arbitrarily
  * multi-page sources keep the real page of every candidate
  * a backend that dies mid-parse must not leave duplicated pages
  * an exhausted question budget must not falsify a passed objective
  * a hinted transfer is recorded as assisted, never as verified
  * the standard CLI can create/update concepts (the closed loop)
  * Level stays the verified level; TargetLevel holds the aim
  * managed tags are replaced, not only accumulated
  * evidence does not migrate between two different goals
  * the direction-ask cooldown survives with no strategy record yet
  * an uncertain grade blocks closing the session
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import ingest  # noqa: E402
import strategy  # noqa: E402
from anki_client import AnkiClient, ConceptIDConflict  # noqa: E402
from concept_service import ConceptService, make_concept_id, validate_concept  # noqa: E402
from ingest import chunk_candidates  # noqa: E402
from mock_anki import MockAnkiClient  # noqa: E402
from session import new_session  # noqa: E402


def call(capsys, argv):
    """Run the CLI and decode whichever stream it used."""
    from cli import main
    status = main(argv)
    out = capsys.readouterr()
    return status, json.loads(out.out if status == 0 else out.err)


def cli_with_mock(tmp_path, monkeypatch):
    import cli
    client = MockAnkiClient()
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    monkeypatch.setattr(cli, "AnkiClient", lambda: client)
    return cli, client


def concept(**overrides):
    base = {
        "concept_id": "topic.concept",
        "title": "Concept",
        "core_knowledge": "core principle and its boundary",
        "learning_objective": "apply it to a new case",
        "level": "L0",
        "status": "active",
    }
    base.update(overrides)
    return base


# -- ConceptID identity ----------------------------------------------------
class _SearchAnki(AnkiClient):
    """AnkiClient whose Anki search returns notes for any query."""

    def __init__(self, notes):
        super().__init__()
        self._notes = notes

    def find_notes(self, query):
        return [int(n["noteId"]) for n in self._notes]

    def notes_info(self, note_ids):
        return [n for n in self._notes if int(n["noteId"]) in note_ids]


def _note(note_id, concept_id):
    return {"noteId": str(note_id), "fields": {"ConceptID": {"value": concept_id}}}


def test_unknown_concept_id_never_resolves_to_another_note():
    client = _SearchAnki([_note(1, "topic.concept_v2")])
    assert client.find_concept("topic.concept") is None


def test_differently_cased_concept_id_is_reported_not_silently_matched():
    # Anki's field search is case-insensitive; the id is not.
    client = _SearchAnki([_note(1, "topic.concept")])
    with pytest.raises(ConceptIDConflict):
        client.find_concept("Topic.Concept")


def test_duplicate_concept_id_stops_instead_of_picking_one():
    client = _SearchAnki([_note(1, "topic.concept"), _note(2, "topic.concept")])
    with pytest.raises(ConceptIDConflict):
        client.find_concept("topic.concept")


# -- ingest page attribution ----------------------------------------------
def test_multipage_candidates_keep_their_real_page():
    text = "## Bayes\nbase rate first page\n\f\n## Risk\nsecond page idea\n\f\n## Third\nthird page idea\n"
    cands = chunk_candidates(text, [])
    assert [c["page"] for c in cands] == [1, 2, 3]
    assert [c["ref"] for c in cands] == ["p1:bayes", "p2:risk", "p3:third"]


def test_headingless_multipage_source_does_not_claim_page_one():
    text = "first page body text\n\f\nsecond page body text\n"
    assert [c["page"] for c in chunk_candidates(text, [])] == [1, 2]


def test_pdf_backend_fallback_does_not_duplicate_pages(monkeypatch):
    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

        def get_text(self):
            return self._text

    class _BrokenPages:
        def __init__(self):
            self._first = True

        def __iter__(self):
            return self

        def __next__(self):
            if self._first:
                self._first = False
                return _Page("pypdf first page body")
            raise RuntimeError("pypdf died mid-document")

    class _Reader:
        def __init__(self, path):
            self.pages = _BrokenPages()

    class _Doc:
        def __init__(self, path):
            self._pages = ["fitz one", "fitz two"]

        def __len__(self):
            return len(self._pages)

        def __getitem__(self, i):
            return _Page(self._pages[i])

        def close(self):
            pass

    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = _Reader
    fake_fitz = types.ModuleType("fitz")
    fake_fitz.open = lambda path: _Doc(path)
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    text, pages = ingest._parse_pdf(Path("broken.pdf"))
    assert [p["page"] for p in pages] == [1, 2]
    assert text.count("fitz one") == 1 and text.count("fitz two") == 1
    assert "pypdf first page body" not in text


# -- budget vs evidence ----------------------------------------------------
def test_budget_exhaustion_does_not_force_again_on_a_passed_objective():
    s = new_session("active_learning")
    s.set_current_question("topic.mde", "Q", objective="L2")
    s.record_answer("correct")
    s.set_current_question("topic.mde", "New case", objective="L2", is_transfer=True)
    s.record_answer("correct")
    s.data["questions_used"] = 8
    assert s.can_continue() is False
    decision = s.closure_decision(budget_exhausted=True)
    assert (decision.action, decision.grade) == ("close_concept", 3)


def test_budget_exhaustion_still_declares_a_gap_when_unverified():
    s = new_session("active_learning")
    s.set_current_question("topic.mde", "Q", objective="L2")
    s.record_answer("wrong")
    s.data["questions_used"] = 8
    decision = s.closure_decision(budget_exhausted=True)
    assert (decision.action, decision.grade) == ("close_with_gap", 1)


def test_hinted_transfer_is_assisted_not_verified():
    s = new_session("active_learning")
    s.set_current_question("topic.mde", "Q", objective="L2")
    s.record_answer("wrong")
    s.advance_attempt(1)
    s.record_answer("correct")
    s.set_current_question("topic.mde", "New case", objective="L2", is_transfer=True)
    s.record_answer("correct", hinted=True)
    assert s.data["evidence"]["transfer"] == "assisted_correct"
    assert s.closure_decision().action == "ask_transfer"


def test_cli_next_reports_the_hint_rule(capsys):
    # A hint anywhere in the concept keeps the grade at Again, never Good.
    code, decision = call(capsys, ["next", "--first", "correct", "--latest", "correct",
                                   "--transfer", "passed", "--hints-used", "--objective", "L2"])
    assert code == 0 and decision == {"action": "close_concept", "grade": 1}


# -- CLI concept CRUD: the closed loop ------------------------------------
def test_cli_concept_create_completes_the_standard_loop(tmp_path, monkeypatch, capsys):
    cli_with_mock(tmp_path, monkeypatch)
    code, created = call(capsys, [
        "concept", "create", "--id", "probability.bayes", "--title", "Bayes",
        "--core", "posterior combines base rate and likelihood",
        "--objective", "update a probability in an unfamiliar case",
        "--target-level", "L2", "--source-ref", "p5:bayes", "--error", "inverse_probability",
    ])
    assert code == 0 and created["created"] is True
    # the aim is stored, the verified level is NOT claimed
    assert created["concept"]["target_level"] == "L2"
    assert created["concept"]["level"] == "L0"

    code, got = call(capsys, ["get", "probability.bayes"])
    assert code == 0 and got["core_knowledge"] and got["target_level"] == "L2"

    call(capsys, ["session", "start", "probability.bayes"])
    call(capsys, ["session", "ask", "probability.bayes", "New case?", "--objective", "L1"])
    call(capsys, ["session", "answer", "correct"])
    code, graded = call(capsys, ["grade", "probability.bayes", "3"])
    assert code == 0 and graded["ok"]

    code, target = call(capsys, ["concept", "level", "--id", "probability.bayes", "--target", "L3"])
    assert code == 0 and target["concept"]["target_level"] == "L3"
    assert target["concept"]["level"] == "L0"
    code, verified = call(capsys, ["concept", "level", "--id", "probability.bayes", "--verified", "L1"])
    assert code == 0 and verified["concept"]["level"] == "L1"

    code, errored = call(capsys, ["concept", "error", "--id", "probability.bayes",
                                  "--type", "base_rate_neglect"])
    assert code == 0 and "base_rate_neglect" in errored["concept"]["common_errors"]


def test_cli_concept_update_and_upsert_are_available(tmp_path, monkeypatch, capsys):
    cli_with_mock(tmp_path, monkeypatch)
    call(capsys, ["concept", "upsert", "--id", "topic.c", "--title", "T",
                  "--core", "k", "--objective", "o"])
    code, again = call(capsys, ["concept", "upsert", "--id", "topic.c", "--title", "T2",
                                "--core", "k2", "--objective", "o"])
    assert code == 0 and again["created"] is False and again["concept"]["title"] == "T2"
    code, updated = call(capsys, ["concept", "update", "--id", "topic.c", "--topic", "statistics"])
    assert code == 0 and "topic::statistics" in updated["concept"]["tags"]


def test_cli_concept_json_payload_and_level_validation(tmp_path, monkeypatch, capsys):
    cli_with_mock(tmp_path, monkeypatch)
    payload = tmp_path / "concept.json"
    payload.write_text(json.dumps({"concept_id": "topic.j", "title": "J", "core_knowledge": "k",
                                   "learning_objective": "o", "source_refs": ["p1:x"]}), encoding="utf-8")
    code, created = call(capsys, ["concept", "create", "--id", "topic.j", "--json", str(payload)])
    assert code == 0 and created["concept"]["source_refs"] == ["p1:x"]
    code, err = call(capsys, ["concept", "level", "--id", "topic.j"])
    assert code == 1 and "exactly one" in err["error"]


def test_create_refuses_a_verified_level_without_evidence():
    svc = ConceptService(MockAnkiClient())
    with pytest.raises(Exception) as exc:
        svc.create(concept(level="L2"))
    assert "VERIFIED" in str(exc.value)
    made = svc.create(concept(level="L0", target_level="L2"))
    assert made["level"] == "L0" and made["target_level"] == "L2"
    asserted = svc.create(concept(concept_id="topic.other", level="L2"), verified_level=True)
    assert asserted["level"] == "L2"


def test_update_refuses_to_smuggle_a_higher_level():
    svc = ConceptService(MockAnkiClient())
    svc.create(concept())
    with pytest.raises(Exception) as exc:
        svc.update(concept(level="L2"))
    assert "Level" in str(exc.value)
    raised = svc.update(concept(level="L2"), verified_level=True)
    assert raised["level"] == "L2"


def test_generated_concept_ids_always_validate():
    cid = make_concept_id("概率", "贝叶斯定理")
    assert validate_concept(concept(concept_id=cid)) == []


def test_update_replaces_stale_managed_tags_not_only_adds():
    client = MockAnkiClient()
    svc = ConceptService(client)
    made = svc.create(concept(topic="probability", level="L0"))
    note_id = made["note_id"]
    svc.update(concept(topic="statistics"))
    svc.set_level("topic.concept", "L2")
    tags = client.notes_info([note_id])[0]["tags"]
    assert "topic::statistics" in tags and "topic::probability" not in tags
    assert "level::l2" in tags and "level::l0" not in tags


# -- strategy --------------------------------------------------------------
def test_direction_ask_cooldown_holds_without_any_strategy_record(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    assert strategy.show()["should_ask_direction"] is True
    after = strategy.mark_asked("session_opening")
    assert after["should_ask_direction"] is False
    assert after["asked_at"]
    assert (tmp_path / "direction_asks.json").exists()


def test_a_custom_goal_line_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    proposed = strategy.propose("学习经济学", "能独立解读一份央行报告", "写完一份复盘")
    assert proposed["candidate"] == "学习经济学"


def test_revise_to_a_different_goal_does_not_inherit_roadmap(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path))
    proposed = strategy.propose("alpha", "own alpha", "baseline checked")
    confirmed = strategy.confirm(proposed["revision"])
    strategy.roadmap_add("design a powered test")
    strategy.roadmap_evidence("design a powered test", "MDE audit passed")
    revised = strategy.revise("polymarket", confirmed["revision"], "predict better", "pre-registered")
    assert revised["roadmap"] == []
    # An unchanged outcome/criterion keeps evidence; changed text cannot prove equivalence.
    strategy.confirm(revised["revision"])
    strategy.roadmap_add("pre-register a question")
    strategy.roadmap_evidence("pre-register a question", "registered on 2026-10-08")
    same = strategy.revise("polymarket", revised["revision"], "predict better", "pre-registered")
    assert [e["id"] for e in same["roadmap"]] == ["pre-register a question"]


# -- reporting / recovery --------------------------------------------------
def test_observe_report_reads_the_current_goal_field(tmp_path, monkeypatch, capsys):
    cli_with_mock(tmp_path, monkeypatch)
    call(capsys, ["strategy", "propose", "alpha", "--outcome", "own alpha",
                  "--criterion", "baseline checked"])
    code, summary = call(capsys, ["observe", "show"])
    assert code == 0
    assert summary["goal"]["outcome"] == "own alpha"
    assert "deliverable" not in summary["goal"]


def test_close_refused_while_a_grade_outcome_is_uncertain(tmp_path, monkeypatch, capsys):
    cli, _client = cli_with_mock(tmp_path, monkeypatch)
    call(capsys, ["session", "start", "topic.c"])
    call(capsys, ["session", "ask", "topic.c", "Q"])
    call(capsys, ["session", "answer", "correct"])
    from session import load_session
    path = cli._session_path()
    session = load_session(path)
    session.data["grade_state"] = "pending"
    session.save(path)
    code, err = call(capsys, ["session", "close", "--reason", "user_request"])
    assert code == 1 and "pending" in err["error"]
    assert path.exists()
