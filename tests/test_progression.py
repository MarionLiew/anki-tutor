"""Decision gate: an extension cannot silently complete a concept."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from progression import decide_next  # noqa: E402


def test_first_independent_correct_can_close_current_objective():
    d = decide_next(first_attempt="correct", latest="correct", transfer="not_needed")
    assert d.action == "close_concept" and d.grade == 3


def test_hint_or_initial_miss_requires_fresh_transfer():
    d = decide_next(first_attempt="wrong", latest="correct", transfer="not_asked")
    assert d.action == "ask_transfer" and d.grade is None


def test_wrong_transfer_stays_on_same_concept():
    d = decide_next(first_attempt="wrong", latest="wrong", transfer="failed")
    assert d.action == "repair_current" and d.grade is None


def test_transfer_first_failed_never_becomes_good_after_self_correction():
    d = decide_next(first_attempt="correct", latest="correct", transfer="passed",
                    transfer_first_failed=True)
    assert d.action == "close_concept" and d.grade == 1


def test_corrected_transfer_keeps_first_miss_again():
    d = decide_next(first_attempt="wrong", latest="correct", transfer="passed")
    assert d.action == "close_concept" and d.grade == 1


def test_new_concept_extension_requires_explicit_boundary():
    d = decide_next(first_attempt="correct", latest="correct", transfer="not_needed", extension="new_concept")
    assert d.action == "close_then_introduce" and d.grade == 3


def test_partial_answer_needs_probe_not_automatic_good():
    d = decide_next(first_attempt="partial", latest="partial", transfer="not_asked")
    assert d.action == "probe_current" and d.grade is None


def test_budget_can_close_with_gap_but_never_good():
    d = decide_next(first_attempt="wrong", latest="wrong", transfer="failed", budget_exhausted=True)
    assert d.action == "close_with_gap" and d.grade == 1
    d = decide_next(first_attempt="correct", latest="correct", transfer="not_needed", budget_exhausted=True)
    assert d.action == "close_with_gap" and d.grade == 1


def test_unsupported_inputs_rejected():
    import pytest
    with pytest.raises(ValueError):
        decide_next(first_attempt="maybe", latest="correct", transfer="passed")


def test_cli_next_is_offline_and_reports_gate(capsys):
    from cli import main
    assert main(["next", "--first", "wrong", "--latest", "correct",
                 "--transfer", "not_asked", "--extension", "new_concept"]) == 0
    import json
    assert json.loads(capsys.readouterr().out) == {"action": "ask_transfer", "grade": None}
