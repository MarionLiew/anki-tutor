"""Offline strategic profile tests; isolated state and subprocess CLI."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import strategy


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKITUTOR_STATE", str(tmp_path / "private"))
    return tmp_path / "private" / "strategy.json"


def test_explicit_lifecycle_and_privacy(state):
    assert strategy.show()["status"] == "unconfirmed"
    assert not state.exists()
    proposed = strategy.propose("alpha", "independently validate one alpha hypothesis",
                                "baseline and costs documented")
    assert proposed["status"] == "proposed"
    assert proposed["revision"] == 1
    assert proposed["outcome"].startswith("independently validate")
    assert proposed["roadmap"] == []
    with pytest.raises(ValueError):
        strategy.propose("gold", "gold hypothesis", "pre-registered baseline")
    with pytest.raises(ValueError):
        strategy.confirm(0)
    confirmed = strategy.confirm(1)
    assert confirmed["status"] == "confirmed"
    assert confirmed["revision"] == 2
    assert confirmed["due_for_review"] is False
    assert set(json.loads(state.read_text())) == {"version", "revision", "status", "candidate", "outcome",
                                                 "criterion", "roadmap", "updated_at", "review_due_at"}
    assert state.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        strategy.revise("gold", 1, "gold hypothesis", "baseline checked")
    changed = strategy.revise("gold", 2, "gold hypothesis", "baseline checked")
    assert changed["status"] == "proposed"
    assert strategy.expire(3)["status"] == "expired"
    assert strategy.propose("Polymarket", "one forecast reviewed", "resolved and reviewed")["status"] == "proposed"


def test_roadmap_chain_and_gap(state):
    strategy.propose("alpha", "independently validate a strategy hypothesis",
                     "film-style audit passes on own rerun")
    strategy.confirm(1)
    assert strategy.next_gap() is None
    strategy.roadmap_add("Design a testable experiment")
    strategy.roadmap_add("Judge the strength of baseline")
    assert strategy.next_gap() == {"id": "design a testable experiment",
                                   "capability": "Design a testable experiment", "status": "no_evidence"}
    strategy.roadmap_evidence("design a testable experiment",
                              "2026-09-24 experiment audit plus reproduction chain passed")
    assert strategy.next_gap()["id"] == "judge the strength of baseline"
    with pytest.raises(ValueError):
        strategy.roadmap_evidence("nonexistent", "text")
    with pytest.raises(ValueError):
        strategy.roadmap_add("Design a testable experiment")  # duplicate id
    strategy.roadmap_evidence("judge the strength of baseline", "", status="no_evidence")
    assert strategy.roadmap_evidence("judge the strength of baseline",
                                     "2026-09-24 strong-baseline explanation accepted")["roadmap"][1]["status"] == "evidenced"
    assert strategy.next_gap() is None


def test_roadmap_requires_confirmed_strategy(state):
    strategy.propose("alpha", "independent validation", "baseline checked")
    with pytest.raises(ValueError):
        strategy.roadmap_add("arbitrary capability")


def test_ask_direction_flag_and_cooldown(state, monkeypatch):
    assert strategy.show()["should_ask_direction"] is True
    strategy.propose("alpha", "independent validation", "baseline checked")
    assert strategy.show()["should_ask_direction"] is True
    # Simulate having asked recently: no nudge.
    strategy.mark_asked()
    assert strategy.show()["should_ask_direction"] is False
    import datetime
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=8)
    monkeypatch.setattr(strategy, "_now", lambda: future)
    assert strategy.show()["should_ask_direction"] is True
    strategy.confirm(1)
    assert strategy.show()["should_ask_direction"] is False  # confirmed: never nudge


def test_due_is_notice_not_automatic_selection(state, monkeypatch):
    strategy.propose("alpha", "one alpha hypothesis", "baseline and costs specified")
    strategy.confirm(1)
    from datetime import timedelta
    import datetime
    future = datetime.datetime.now(datetime.timezone.utc) + timedelta(days=31)
    monkeypatch.setattr(strategy, "_now", lambda: future)
    assert strategy.show()["due_for_review"] is True
    assert strategy.show()["status"] == "confirmed"
    assert json.loads(state.read_text())["status"] == "confirmed"


def test_invalid_state_and_candidate_refuse_overwrite(state):
    state.parent.mkdir(parents=True)
    state.write_text("not json")
    with pytest.raises(ValueError):
        strategy.propose("alpha", "one alpha hypothesis", "baseline and costs specified")
    assert state.read_text() == "not json"
    with pytest.raises(ValueError):
        strategy.propose("secret raw text")


def test_v1_record_is_read_with_v2_fields(state, tmp_path, monkeypatch):
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"version": 1, "revision": 2, "status": "confirmed", "candidate": "alpha",
                                 "deliverable": "one falsifiable hypothesis", "criterion": "baseline documented",
                                 "updated_at": "2026-09-01T00:00:00+00:00",
                                 "review_due_at": "2026-10-01T00:00:00+00:00"}))
    shown = strategy.show()
    assert shown["outcome"] == "one falsifiable hypothesis"
    assert shown["roadmap"] == [] and shown["version"] == 2
    strategy.roadmap_add("audit a backtest")
    assert strategy.next_gap()["id"] == "audit a backtest"


def test_cli_no_anki_dependency(state):
    env = dict(os.environ, ANKITUTOR_STATE=str(state.parent))
    def call(*args):
        return subprocess.run([sys.executable, str(ROOT / "src" / "cli.py"), "strategy", *args], env=env, text=True, capture_output=True)
    assert json.loads(call("show").stdout)["status"] == "unconfirmed"
    assert json.loads(call("propose", "gold", "--outcome", "reproduce a gold report from raw data",
                           "--criterion", "own rerun matches the headline").stdout)["revision"] == 1
    assert call("confirm", "--revision", "9").returncode == 1
    assert json.loads(call("confirm", "--revision", "1").stdout)["status"] == "confirmed"
    assert json.loads(call("roadmap", "add", "audit the data lineage").stdout)["roadmap"][0]["status"] == "no_evidence"
    assert json.loads(call("roadmap", "evidence", "audit the data lineage", "2026-09-24 PIT chain audit passed").stdout)["roadmap"][0]["status"] == "evidenced"
    assert json.loads(call("roadmap", "gap").stdout)["gap"] is None
    assert json.loads(call("revise", "alpha", "--revision", "2", "--outcome", "alpha hypothesis",
                           "--criterion", "baseline checked").stdout)["status"] == "proposed"
    assert json.loads(call("expire", "--revision", "3").stdout)["status"] == "expired"
    assert json.loads(call("asked").stdout)["asked_at"] is not None or call("asked").returncode == 0
