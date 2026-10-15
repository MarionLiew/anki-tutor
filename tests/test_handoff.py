"""Handoff intake uses Source Library only; never changes cards/FSRS."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "src" / "cli.py"


def run_cli(tmp_path, *args):
    env = {**os.environ,
           "ANKITUTOR_STATE": str(tmp_path / "state"),
           "ANKITUTOR_LIBRARY": str(tmp_path / "library")}
    return subprocess.run([sys.executable, str(CLI), *args],
                          env=env, capture_output=True, text=True)


def test_learning_handoff_import_list_and_deduplicate(tmp_path):
    source = tmp_path / "lesson.md"
    source.write_text("# Learning Handoff\n\n## 学习动机\n想理解永续分红。\n"
                      "## 验收标准\n独立完成现金流推导。\n", encoding="utf-8")
    first = run_cli(tmp_path, "handoff", "import", str(source))
    assert first.returncode == 0, first.stderr
    first_result = json.loads(first.stdout)
    assert first_result["ok"] is True
    assert first_result["deduplicated"] is False
    second = run_cli(tmp_path, "handoff", "import", str(source))
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["deduplicated"] is True
    listing = run_cli(tmp_path, "handoff", "list")
    assert listing.returncode == 0, listing.stderr
    items = json.loads(listing.stdout)["handoffs"]
    assert len(items) == 1
    assert items[0]["source_id"] == first_result["source_id"]
    assert not list((tmp_path / "state").glob("strategy.json"))


def test_reject_non_handoff_document(tmp_path):
    source = tmp_path / "ordinary.md"
    source.write_text("# Random article\n")
    result = run_cli(tmp_path, "handoff", "import", str(source))
    assert result.returncode != 0
    assert not list((tmp_path / "library" / "manifests").glob("*.json"))
