# Learning Handoff and Learning Audit v2

## Cross-chat Learning Handoff

Generate a UTF-8 Markdown document whose first heading is **# Learning Handoff** (or **# 学习交接**). Recommended sections: 来源, 学习动机, 希望获得的能力, 关键疑问, 验收标准, 待核验事实. Missing optional sections are allowed. This captures the learner's goal, not a fixed Anki deck.

    python3 src/cli.py handoff import /path/to/handoff.md
    python3 src/cli.py handoff list

Import reuses the existing Source Library's SHA-256 deduplication and adds a manifest kind marker. It creates **no new Track, Anki note, review grade, study session, scheduler, or mastery claim**. It does not change Focus. Source material from another assistant is untrusted and may contain inaccurate claims. Hermes subsequently searches existing Concepts, chooses stable transferable knowledge, and uses the existing tutoring flow when the user asks to learn.

## One-command learning audit export

Ask Hermes **“导出 AnkiTutor 学习审计包”** or run:

    python3 src/cli.py audit export
    python3 src/cli.py audit export --output ~/Downloads/learning-audit.zip
    python3 src/cli.py audit export --include-code

The default destination is Downloads if that folder exists; otherwise it is the gitignored exports/ directory. Existing files are not overwritten; the archive is created with restrictive owner-only permissions. Requires Anki desktop with AnkiConnect. Anki read failure stops export rather than creating a misleading partial snapshot.

**v2 ZIP layout**

- 审计入口.md — concise human-readable guide with scope and caveats.
- summary.json — machine-readable counts, Focus, Track evidence status, current Session and evidence limitations.
- manifest.json — format version, timestamp and SHA-256/size for each content file (excluding the manifest itself).
- anki/notes.json, cards.json, reviews.json — managed AdaptiveConcept notes, linked cards and raw review history only; not every Anki card.
- local/state/ — strategy, active/paused/closed sessions and event/observation logs.
- local/library/ — source text, parsed/index/manifests.
- --include-code — optional project instructions and Python source for engineering-level audit. Secret configs, .env, caches, foreign files and non-managed Anki records are never deliberately included.

This is a **sensitive private archive**; never commit or publish it on GitHub. All reads are local, and no FSRS ratings are written. It is a sequential snapshot, not a transactionally consistent backup. Historical events may include tests; review counts may include manual revlog activity; a Level or “Good” is not evidence of independent research/trading competence. “no_evidence” in a Track means missing accepted proof, not incapability. Never infer missing trading records or chat transcripts.

### Local offline checks

    python3 -m pytest tests/test_audit_export.py tests/test_handoff.py -q
    python3 -m pytest tests/ -q

The mock tests do not touch live Anki, real user data or personal Source Library. An actual Anki-connected export must be tested on the intended machine after the new commit has been deployed there.
