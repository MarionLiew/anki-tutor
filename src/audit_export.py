"""Read-only AnkiTutor learning audit ZIP export.

Contains sensitive learning records. Never commit or publicly share a real ZIP.
Reads only managed AdaptiveConcept notes and their cards/reviews.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import zipfile

from anki_client import AnkiClient, AnkiConnectError
from config import LIBRARY_DIR, MANAGED_TAG, MODEL, SKILL_ROOT, STATE_DIR

FORMAT_VERSION = 2
STATE_FILES = ("strategy.json", "strategy.legacy.bak", "active_session.json",
               "events.jsonl", "learning_observations.jsonl")
STATE_FOLDERS = ("closed_sessions", "paused_sessions")
LIBRARY_FOLDERS = ("sources", "parsed", "manifests", "index")
DOC_FILES = ("AGENTS.md", "README.md", "README.zh-CN.md", "SKILL.md",
             "docs/learning-contract.md", "docs/engineering-spec.md",
             "docs/mentor-view.md", "docs/audit-recovery.md")


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _safe_files(root: Path, names: tuple[str, ...], folders: tuple[str, ...] = ()):
    """Use explicit allowlists and reject links into other users' files."""
    if root.is_symlink():
        raise ValueError(f"symlink export root refused: {root}")
    candidates = [root / name for name in names]
    for folder in folders:
        directory = root / folder
        if directory.is_symlink():
            raise ValueError(f"symlink export folder refused: {directory}")
        if directory.is_dir():
            candidates.extend(sorted(directory.rglob("*")))
    for path in candidates:
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
            raise ValueError(f"symlink export item refused: {path}")
        if path.is_file():
            yield path, path.relative_to(root).as_posix()


def _managed_anki(client):
    ids = client.find_notes(f'tag:"{MANAGED_TAG}"')
    notes = client.notes_info(sorted(set(ids))) if ids else []
    if len(notes) != len(set(ids)):
        raise AnkiConnectError("notesInfo returned an incomplete snapshot")
    notes = [n for n in notes if n.get("modelName") == MODEL and MANAGED_TAG in n.get("tags", [])]
    notes.sort(key=lambda n: int(n["noteId"]))
    card_ids = sorted({int(cid) for n in notes for cid in n.get("cards", [])})
    cards = client.cards_info(card_ids) if card_ids else []
    if len(cards) != len(card_ids):
        raise AnkiConnectError("cardsInfo returned an incomplete snapshot")
    cards.sort(key=lambda c: int(c["cardId"]))
    reviews = client.invoke("getReviewsOfCards", cards=card_ids) if card_ids else {}
    if not isinstance(reviews, dict) or any(str(cid) not in reviews for cid in card_ids):
        raise AnkiConnectError("review history incomplete; export aborted")
    return notes, cards, {str(cid): reviews[str(cid)] for cid in card_ids}


def _summary(strategy, session, notes, cards, reviews, created):
    tracks = strategy.get("tracks", {}) if isinstance(strategy, dict) else {}
    rows = []
    for tid, track in sorted(tracks.items()):
        statuses = Counter(x.get("status", "unknown") for x in track.get("roadmap", []))
        rows.append({"id": tid, "name": track.get("name", tid),
                     "status": track.get("status"), "track_status": track.get("track_status"),
                     "required": sum(x.get("kind", "required") == "required" for x in track.get("roadmap", [])),
                     "evidenced": sum(x.get("status") == "evidenced" and x.get("kind", "required") == "required" for x in track.get("roadmap", [])),
                     "no_evidence": statuses.get("no_evidence", 0)})
    levels = Counter(n.get("fields", {}).get("Level", {}).get("value", "unknown") for n in notes)
    ease = Counter(str(r.get("ease", "unknown")) for history in reviews.values() for r in history)
    unreviewed_high_level = sum(
        n.get("fields", {}).get("Level", {}).get("value") in ("L1", "L2", "L3")
        and not any(reviews.get(str(cid)) for cid in n.get("cards", []))
        for n in notes
    )
    return {
        "format_version": FORMAT_VERSION, "exported_at": created,
        "focus": strategy.get("focus") if isinstance(strategy, dict) else None,
        "tracks": rows,
        "active_session": {k: session.get(k) for k in
            ("session_id", "concept_id", "status", "mode", "track_id") if k in session}
            if isinstance(session, dict) else None,
        "anki": {"managed_notes": len(notes), "managed_cards": len(cards),
                 "cards_with_reviews": sum(bool(reviews.get(str(c["cardId"]))) for c in cards),
                 "total_reviews": sum(map(len, reviews.values())),
                 "note_levels": dict(sorted(levels.items())),
                 "review_ease": dict(sorted(ease.items())),
                 "high_level_notes_without_reviews": unreviewed_high_level},
        "limitations": [
            "Roadmap no_evidence means no accepted proof, not inability.",
            "Note Level and FSRS ratings alone do not prove independent capability.",
            "Historical events.jsonl may contain test activity; do not count it as verified study.",
            "Anki revlog may include non-Tutor/manual reviews; grade origin is not inferred.",
            "This is a read-only snapshot, not a restored backup or proof of trading performance.",
        ],
    }


def _readme(summary, include_code):
    a = summary["anki"]
    tracks = "\n".join(
        f"- {t['name']} ({t['id']}): {t['evidenced']}/{t['required']} roadmap entries evidenced (not a mastery score)"
        for t in summary["tracks"]
    ) or "- None"
    return (
        f"# AnkiTutor 学习审计包 v{FORMAT_VERSION}\n\n"
        f"导出时间：{summary['exported_at']}\n\n"
        "**敏感学习资料，请勿公开或提交 GitHub。** 本包是只读快照，未修改卡片或 FSRS。\n\n"
        "## 快速概览\n\n"
        f"- 当前 Focus：{summary['focus']}\n"
        f"- AnkiTutor 概念：{a['managed_notes']}；卡片：{a['managed_cards']}；有复习记录的卡片：{a['cards_with_reviews']}\n"
        f"- 复习日志条目：{a['total_reviews']}；高 Level 但无复习日志的概念：{a['high_level_notes_without_reviews']}\n"
        f"- 代码与规程快照：{'包含' if include_code else '不包含（可使用 --include-code）'}\n\n"
        "## 学习路线\n\n" + tracks + "\n\n"
        "## 阅读顺序\n\n"
        "1. summary.json：可机器读取的整体状态、数量、限制。\n"
        "2. local/state/：Track、会话、答题与事件原始证据。\n"
        "3. anki/：受管理概念卡和原始复习记录，不包括其他 Anki 卡。\n"
        "4. local/library/：原始来源与索引；注意可能包含私人内容。\n"
        "5. manifest.json：各文件字节长度和 SHA-256，用于完整性检查。\n\n"
        "## 解释边界\n\n" + "\n".join(f"- {s}" for s in summary["limitations"]) + "\n"
        "\n未读取 Hermes 完整聊天历史；本机其他 Anki profile 不在导出范围内。\n"
    ).encode("utf-8")


def export_audit(output: Path, *, client=None, state_dir=STATE_DIR,
                 library_dir=LIBRARY_DIR, skill_root=SKILL_ROOT,
                 include_code=False, now=None):
    """Return ZIP path; never create a partial archive after Anki read failures."""
    now = now or datetime.now().astimezone()
    created = now.isoformat()
    client = client if client is not None else AnkiClient()
    notes, cards, reviews = _managed_anki(client)
    data = {}

    def add(name, raw):
        if name in data:
            raise ValueError(f"duplicate archive entry: {name}")
        data[name] = raw

    state_dir, library_dir, skill_root = map(Path, (state_dir, library_dir, skill_root))
    for path, rel in _safe_files(state_dir, STATE_FILES, STATE_FOLDERS):
        add("local/state/" + rel, path.read_bytes())
    for path, rel in _safe_files(library_dir, (), LIBRARY_FOLDERS):
        add("local/library/" + rel, path.read_bytes())
    if include_code:
        for path, rel in _safe_files(skill_root, DOC_FILES, ("prompts",)):
            add(rel, path.read_bytes())
        for sub in ("src", "tests"):
            for path in sorted((skill_root / sub).glob("*.py")):
                if path.is_symlink():
                    raise ValueError(f"symlink export item refused: {path}")
                add("local/" + sub + "/" + path.name, path.read_bytes())

    add("anki/notes.json", _json(notes))
    add("anki/cards.json", _json(cards))
    add("anki/reviews.json", _json(reviews))
    strategy = json.loads(data["local/state/strategy.json"]) if "local/state/strategy.json" in data else {}
    session = json.loads(data["local/state/active_session.json"]) if "local/state/active_session.json" in data else None
    summary = _summary(strategy, session, notes, cards, reviews, created)
    add("summary.json", _json(summary))
    add("审计入口.md", _readme(summary, include_code))
    manifest = {
        "format_version": FORMAT_VERSION, "exported_at": created,
        "include_code": include_code,
        "files": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                  for name, raw in sorted(data.items())},
    }
    add("manifest.json", _json(manifest))
    output = Path(output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as target:
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, raw in sorted(data.items()):
                    archive.writestr(name, raw)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output
