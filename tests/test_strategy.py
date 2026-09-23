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
    proposed = strategy.propose("alpha", "one alpha hypothesis", "baseline and costs specified")
    assert proposed["status"] == "proposed"
    assert proposed["revision"] == 1
    with pytest.raises(ValueError):
        strategy.propose("gold", "gold hypothesis", "pre-registered baseline")
    with pytest.raises(ValueError):
        strategy.confirm(0)
    confirmed = strategy.confirm(1)
    assert confirmed["status"] == "confirmed"
    assert confirmed["revision"] == 2
    assert confirmed["due_for_review"] is False
    assert set(json.loads(state.read_text())) == {"version", "revision", "status", "candidate", "deliverable", "criterion", "updated_at", "review_due_at"}
    assert state.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        strategy.revise("gold", 1, "gold hypothesis", "baseline checked")
    changed = strategy.revise("gold", 2, "gold hypothesis", "baseline checked")
    assert changed["status"] == "proposed"
    assert strategy.expire(3)["status"] == "expired"
    assert strategy.propose("Polymarket", "one forecast", "resolved and reviewed")["status"] == "proposed"


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


def test_cli_no_anki_dependency(state):
    env = dict(os.environ, ANKITUTOR_STATE=str(state.parent))
    def call(*args):
        return subprocess.run([sys.executable, str(ROOT / "src" / "cli.py"), "strategy", *args], env=env, text=True, capture_output=True)
    assert json.loads(call("show").stdout)["status"] == "unconfirmed"
    assert json.loads(call("propose", "gold", "--deliverable", "gold hypothesis", "--criterion", "baseline checked").stdout)["revision"] == 1
    assert call("confirm", "--revision", "9").returncode == 1
    assert json.loads(call("confirm", "--revision", "1").stdout)["status"] == "confirmed"
    assert json.loads(call("revise", "alpha", "--revision", "2", "--deliverable", "alpha hypothesis", "--criterion", "baseline checked").stdout)["status"] == "proposed"
    assert json.loads(call("expire", "--revision", "3").stdout)["status"] == "expired"
