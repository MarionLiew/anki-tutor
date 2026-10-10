# Engineering and project maintenance contract

This file governs coding and maintenance by Hermes, Codex and other coding agents. It is not a teaching prompt. Learning and memory principles are authoritative in [docs/learning-contract.md](docs/learning-contract.md); operational teaching and CLI instructions are in [SKILL.md](SKILL.md). Data contracts live in [docs/engineering-spec.md](docs/engineering-spec.md), and mentor interventions in [docs/mentor-view.md](docs/mentor-view.md).

## Purpose First

Before adding a feature, identify the concrete problem, why existing functionality is insufficient, and observable acceptance criteria. Deliver working, verified behavior rather than a design alone. Do not expand the scope to hypothetical future needs.

## Reuse Before Build

Inspect existing project implementations before writing replacements. Check the standard library and installed dependencies, then mature, maintained, license-compatible open-source solutions. Prefer direct use or a thin adaptation. Evaluate upstream maintenance costs before forking. Build custom infrastructure only for core differentiation, an unmet critical constraint, or an explicit verifiable benefit; learning a technology is not a production architecture justification.

## Minimal Complexity

Use the simplest implementation satisfying the acceptance criteria. Avoid meaningless abstraction layers, premature generalization, duplicate databases or state machines, complex new dependencies, and unrelated refactoring. Reuse TutorSession, AnkiClient and ConceptService. Do not create another FSRS scheduler, knowledge graph, concurrent teaching scheduler, or automatic multi-Track recommendation system.

## Single Source of Truth

- **Anki:** Concepts, review history and FSRS scheduling.
- **Source Library:** original knowledge materials and provenance.
- **Track:** long-term Outcome, Criterion, Roadmap and real capability acceptance evidence.
- **Session:** the current teaching process and short-term evidence; dormant snapshots preserve unfinished work.
- **Hermes:** user interaction, teaching orchestration and tool calls.

Never maintain duplicate authoritative state. Track association uses Anki `track::<id>` tags, not another mapping database. A Concept's lifecycle and due-review eligibility remain independent of Track Focus, completion or archive. Concept scores do not establish Track completion.

## Compatibility and Reliability

Changes to persisted data, CLI commands and state transitions must account for legacy migration, idempotency, atomic writes, interruption recovery and preservation of historical evidence. Back up and verify before migrating; repeated migration must not duplicate records. Never infer historical progress from test logs or chat summaries.

Keep at most one foreground teaching Session and one displayed question. Preserve the original question, first answer, hint and transfer evidence when parking or restoring a Session. Pending or uncertain grading must block unsafe switching, pausing, closing and new teaching. Never blindly resubmit a grade or clear evidence to escape a blocker. Preserve damaged or interrupted state for inspection rather than guessing recovery.

CLI success does not prove WeChat delivery. Grading success requires verified Anki receipts; preparing a hint is not proof it was delivered. Completing or archiving a Track must not delete Concepts, remove historical association tags, suspend cards or reset review history.

Protect real Anki data. Offline tests must isolate runtime state and Source Library before importing application modules. Any real integration test must use an isolated test deck and explicit test identifiers; never write, grade or delete real learning cards. Never overwrite installed live state or Source Library with repository fixtures during skill synchronization.

## Testing and Maintenance

Add regression tests for defects and critical transitions, including Focus switching, snapshot restoration, pending-grade protection, migration and Track-independent due reviews. Run the full offline suite with `python3 -m pytest tests/ -q` and check `git diff --check`. Report mock/offline results separately from real integration acceptance; never fabricate successful tests or delivery.

New dependencies need a concrete maintenance justification. Keep documentation consistent with actual CLI and code, referencing authoritative contracts rather than duplicating them. When updating an installed Hermes Skill, verify installed source parity and tests, preserve live learning data, and report the actual deployment scope. Commit and push only when authorized, and verify the remote target after pushing.
