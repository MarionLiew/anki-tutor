"""Offline audit export tests: never touch Anki or real learning data."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from audit_export import export_audit
from anki_client import AnkiConnectError


class FakeAnki:
    def __init__(self, fail=False):
        self.fail = fail

    def find_notes(self, query):
        assert "managed::anki_tutor" in query
        if self.fail:
            raise AnkiConnectError("offline")
        return [1, 2]

    def notes_info(self, ids):
        return [
            {"noteId": 1, "modelName": "AdaptiveConcept", "tags": ["managed::anki_tutor"],
             "cards": [10], "fields": {"Level": {"value": "L2"}}},
            {"noteId": 2, "modelName": "Other", "tags": ["managed::anki_tutor"],
             "cards": [20], "fields": {}},
        ]

    def cards_info(self, ids):
        assert ids == [10]
        return [{"cardId": 10, "note": 1}]

    def invoke(self, name, **params):
        assert name == "getReviewsOfCards"
        assert params["cards"] == [10]
        return {"10": [{"ease": 1, "id": 123456}]}


@pytest.fixture
def private(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "library" / "sources").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "state" / "strategy.json").write_text(json.dumps({
        "focus": "quant", "tracks": {"quant": {"name": "Quant", "roadmap": [
            {"kind": "required", "status": "no_evidence"}]}}
    }), encoding="utf-8")
    (tmp_path / "state" / ".env").write_text("TOP_SECRET")
    (tmp_path / "src" / "keep.py").write_text("# safe sample")
    (tmp_path / "src" / ".env").write_text("API_KEY=secret")
    return tmp_path


def export(private, name="audit.zip", **kwargs):
    return export_audit(private / name,
                        client=kwargs.pop("client", FakeAnki()),
                        state_dir=private / "state",
                        library_dir=private / "library",
                        skill_root=private, **kwargs)


def test_summary_manifest_scope_and_no_secrets(private):
    output = export(private)
    with zipfile.ZipFile(output) as archive:
        files = archive.namelist()
        assert "summary.json" in files and "审计入口.md" in files
        assert all(".env" not in item and not item.startswith("local/src/") for item in files)
        summary = json.loads(archive.read("summary.json"))
        assert summary["anki"]["managed_notes"] == 1
        assert summary["anki"]["total_reviews"] == 1
        assert summary["focus"] == "quant"
        assert summary["tracks"][0]["no_evidence"] == 1
        manifest = json.loads(archive.read("manifest.json"))
        for name, info in manifest["files"].items():
            assert info["bytes"] == len(archive.read(name))
            assert info["sha256"] == hashlib.sha256(archive.read(name)).hexdigest()


def test_fail_closed_if_anki_unavailable(private):
    with pytest.raises(AnkiConnectError):
        export(private, client=FakeAnki(fail=True))
    assert not (private / "audit.zip").exists()


def test_code_snapshot_is_opt_in_and_allowlisted(private):
    with zipfile.ZipFile(export(private, include_code=True)) as archive:
        assert "local/src/keep.py" in archive.namelist()
        assert "local/src/.env" not in archive.namelist()


def test_symlink_to_secret_refused(private):
    (private / "library" / "sources" / "leak").symlink_to(private / "state" / ".env")
    with pytest.raises(ValueError):
        export(private)
    assert not (private / "audit.zip").exists()


def test_does_not_overwrite_a_previous_audit(private):
    (private / "audit.zip").write_text("original")
    with pytest.raises(FileExistsError):
        export(private)
    assert (private / "audit.zip").read_text() == "original"
