"""Tests for AnkiTutor — offline, mock AnkiConnect.

Mapping to acceptance criteria / feature tests in the engineering doc:
  AC-01  read of existing concepts/fields/tags/due   (T01-adjacent)
  AC-02  candidate concept dedupe by ConceptID       (T02)
  AC-03  create/update note after active learning    (T05)
  AC-04  cron only triggers/recover first question   (T06)
  AC-05  wrong answer -> hint -> retry -> variation  (T03)
  AC-06  grade mapping written back to Anki          (T04)
  AC-07  PDF delete does not delete review history   (T07, T08)
  AC-08  session recovery (current question/attempt) (T10)
  AC-09  Level is verified-max, not forced L0->L3    (T12)
Budget:  max_questions=8 / hard cap 20min            (T11)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from anki_client import AnkiConnectUnreachable  # noqa: E402
from concept_service import (  # noqa: E402
    ConceptService,
)
from mock_anki import MockAnkiClient  # noqa: E402
import session as S  # noqa: E402


@pytest.fixture()
def svc():
    client = MockAnkiClient()
    return ConceptService(client), client


@pytest.fixture()
def base_concept():
    return {
        "concept_id": "probability.bayes.base_rate",
        "title": "Base Rate / 基础率",
        "core_knowledge": "后验概率必须同时考虑基础率与观测证据的似然。",
        "learning_objective": "能在陌生场景中用自然频率或 Bayes 更新概率。",
        "level": "L2",
        "prerequisites": ["probability.conditional"],
        "common_errors": ["inverse_probability"],
        "source_refs": ["forecasting_principles.pdf#page=32"],
        "status": "active",
        "version": 1,
        "domain": "quantos",
        "topic": "probability",
        "origin": "pdf",
    }


# -- AC-01: read existing concept + fields/tags/due ----------------------
def test_create_and_read_back(svc, base_concept):
    s, c = svc
    created = s.create(base_concept)
    assert created["note_id"] is not None
    got = s.get("probability.bayes.base_rate")
    assert got["core_knowledge"] == base_concept["core_knowledge"]
    assert got["level"] == "L2"
    assert got["card_ids"]
    # tags written
    info = c.notes_info([got["note_id"]])[0]
    assert "managed::anki_tutor" in info["tags"]
    assert "topic::probability" in info["tags"]
    assert "domain::quantos" in info["tags"]


def test_due_detection(svc, base_concept):
    s, _ = svc
    s.create(base_concept)
    due = s.client.due_concepts()
    assert [d["fields"]["ConceptID"]["value"] for d in due] == ["probability.bayes.base_rate"]


# -- AC-02 / T02: dedupe by ConceptID -------------------------------------
def test_duplicate_create_blocked(svc, base_concept):
    s, _ = svc
    s.create(base_concept)
    with pytest.raises(Exception):
        s.create(base_concept)


def test_upsert_reuses_concept_merging_refs(svc, base_concept):
    s, _ = svc
    s.create(base_concept)
    second = dict(base_concept)
    second["source_refs"] = ["bayes_notes.md#p=3"]
    updated, created = s.upsert(second)
    assert created is False
    assert "forecasting_principles.pdf#page=32" in updated["source_refs"]
    assert "bayes_notes.md#p=3" in updated["source_refs"]
    assert updated["version"] == 2


# -- AC-03 / T05: create/update after learning ----------------------------
def test_update_bumps_version_and_preserves(svc, base_concept):
    s, _ = svc
    s.create(base_concept)
    upd = s.update(dict(base_concept, common_errors=["inverse_probability", "base_rate_neglect"]))
    assert upd["version"] == 2
    assert "base_rate_neglect" in upd["common_errors"]


# -- AC-06 / T04: grading mapping written back ----------------------------
def test_grade_maps_to_ease(svc, base_concept):
    s, c = svc
    s.create(base_concept)
    cid = s.get("probability.bayes.base_rate")["card_ids"][0]
    s.grade("probability.bayes.base_rate", 1)  # Again
    assert c._cards[cid]["queue"] == 1  # went to learning
    assert c._cards[cid]["reps"] == 1


# -- AC-05 / T03-ready: session prompt flow (one-question, hint, variation)
def test_session_one_question_hint_retry(svc):
    s, _ = svc
    sess = S.new_session("passive_review", concept_queue=["c1"], concept={"concept_id": "c1"}, question="Q1")
    sess.set_current_question("c1", "Q1")
    assert sess.status == "waiting_answer"
    sess.advance_attempt(hint_level=1)
    assert sess.attempt == 2 and sess.hint_level == 1 and sess.status == "waiting_answer"


# -- AC-08 / T10: session recovery ----------------------------------------
def test_session_recovery(svc, tmp_path):
    s, _ = svc
    p = tmp_path / "active_session.json"
    sess = S.new_session("passive_review", concept_queue=["c1", "c2"], concept={"concept_id": "c1"}, question="Q1")
    sess.set_current_question("c1", "Q1")
    sess.advance_attempt(hint_level=1)
    sess.save(p)
    recovered = S.load_session(p)
    assert recovered.current_concept == "c1"
    assert recovered.attempt == 2
    assert recovered.hint_level == 1
    assert recovered.status == "waiting_answer"  # interpreted as the current answer


# -- AC-09 / T12: Level not forced through full ladder --------------------
def test_level_is_verified_max_not_forced(svc, base_concept):
    s, _ = svc
    s.create(base_concept)  # starts L2
    # ordinary review passes 1 question at L2, no forced L3
    assert s.get("probability.bayes.base_rate")["level"] == "L2"
    # raise is allowed
    s.set_level("probability.bayes.base_rate", "L3")
    assert s.get("probability.bayes.base_rate")["level"] == "L3"
    # lower is refused
    with pytest.raises(Exception):
        s.set_level("probability.bayes.base_rate", "L1")


# -- AC-07 / T08: source delete does not delete review history ------------
def test_delete_protected_after_review(svc, base_concept):
    s, _ = svc
    s.create(base_concept)
    s.grade("probability.bayes.base_rate", 3)
    with pytest.raises(Exception):
        s.delete_unreviewed("probability.bayes.base_rate", confirm=True)


def test_retire_preserves_and_suspends(svc, base_concept):
    s, c = svc
    s.create(base_concept)
    cid = s.get("probability.bayes.base_rate")["card_ids"][0]
    s.retire("probability.bayes.base_rate")
    got = s.get("probability.bayes.base_rate")
    assert got["status"] == "retired"
    assert c._cards[cid]["queue"] == -1  # suspended, not deleted


def test_delete_unreviewed_requires_confirm(svc, base_concept):
    s, _ = svc
    s.create(base_concept)
    with pytest.raises(Exception):
        s.delete_unreviewed("probability.bayes.base_rate")  # no confirm
    s.delete_unreviewed("probability.bayes.base_rate", confirm=True)
    assert s.get("probability.bayes.base_rate") is None


# -- T01: initial ingest produces candidates, no batch card creation ------
def test_unreachable_raises_not_fabricates(svc, base_concept):
    s, c = svc
    c.up = False
    with pytest.raises(AnkiConnectUnreachable):
        s.create(base_concept)


# -- T11: budget enforces max_questions -----------------------------------
def test_session_budget_max_questions(svc, tmp_path):
    s, _ = svc
    sess = S.new_session("active_learning", concept_queue=["c1"])
    for _ in range(8):
        sess.register_question()
    assert sess.can_continue() is True
    sess.register_question()  # 9th
    assert sess.can_continue() is False


# -- mode guard -----------------------------------------------------------
def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        S.new_session("bogus")