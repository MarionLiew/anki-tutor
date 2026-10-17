# Incremental efficiency audit

## Scope and cause

Audited main at `f1fdf88`, with a clean worktree and fetched origin/main. Existing
session guidance already preserves the waiting question, distinguishes first
answers/hints/transfer, reports diminishing value after two distinct independent
transfer records, repairs failed transfer and returns to the task. Existing
Roadmap, Concept fields, Source Library, Anki review history, handoff and audit
export are sufficient; no new planner, graph, database or scheduling code is needed.

The remaining gap is orchestration: the topic-priority instructions did not
explicitly require comparing existing Concept coverage and prerequisites before
choosing the next topic. The question prompt also lacked the natural external-view
scenario clarification already present in main's SKILL. Session guidance is local
advice, not a global concept selector. Fix only the teaching contract and prompt.

Read-only live inspection confirmed an unfinished waiting-answer session with
legacy answer records lacking transfer/attempt metadata. Those records cannot be
reclassified as independent transfers. Missing Roadmap acceptance evidence is not
proof of inability or mastery. A chat-only withdrawal is not a persisted question
withdrawal; this audit does not change it. Existing review rows support memory
history, not independent project capability. No raw learning transcript or source
content is included here; mixed historical events are not learner evidence.

## Minimal change

SKILL now requires a read-only comparison using existing Roadmap evidence,
LearningObjective, Level/TargetLevel, Prerequisites, SourceRefs/Source Library and
Anki evidence; select one valuable coverage gap or minimal prerequisite instead
of following the most recent tangent. Search across Tracks before creating any
missing Concept. Do not expand Roadmap or batch-create Concepts. Repeated genuine
independent transfers default to closure/return, not another numeric variant;
two is not a practice quota. A new boundary can justify another question.

The question prompt references this rule and permits natural evaluation of an
external idea (e.g. encountering a blogger's post) while requiring real provenance
or explicit fictional labeling. No score, FSRS, pending or persisted schema changes.

## Executed acceptance checks and limits

`tests/test_incremental_efficiency.py` uses isolated synthetic sessions, never live
learning data:

- **A:** a first independent correct answer plus two distinct unhinted transfer
  records yields `return_to_original_task`, `independent_transfers=2` and
  `marginal_value=diminishing`; guidance leaves session data unchanged, existing
  closure proposes Good. This routing already worked before this patch; the new
  prompt makes stopping repetition an explicit teaching default. Distinct strings
  alone cannot establish semantic novelty.
- **B:** static contract checks confirm the prompt uses coverage, dependencies,
  sources and review evidence instead of chat recency, and never equates
  `no_evidence` with inability. In a quant-learning case with only a few Concepts,
  compare the existing required capabilities and their supporting Concepts, then
  diagnose one unverified useful capability or its minimal prerequisite. Do not
  invent mastery, percentages, or fill the Roadmap. This is a tested instruction
  contract plus a reviewed scenario, **not execution of an automatic selector or
  proof that an LLM reliably selects the best Concept**.
- **C:** a synthetic cross-venue task with a funding-cashflow gap routes wrong
  answer -> minimal prerequisite repair -> fresh independent transfer -> return
  to the original task. Again remains Again after repair. For math, funding and
  microstructure gaps, select one observed blocker using existing prerequisites,
  not three complete courses. Actual exchange rules/data must be sourced before
  claiming a real anomaly; this test supplies no market evidence. The routing
  already existed; the patch clarifies which prerequisite to choose.

External-view source/fiction instructions have static regression checks. These
checks do not grade open answers, generate or validate real questions, demonstrate
message delivery, establish delayed recall or show improved real-task results.
Efficiency is still a hypothesis: evaluate subsequent real independent unfamiliar
applications, delayed retention and research deliverables before claiming benefit.
No learner experiment or fabricated history was created for this audit.

## Verification and deployment contract

Run the full offline suite and `git diff --check`. Synchronize only tracked source,
prompts, documentation and tests from the repository into the installed Skill,
never state/library or repository fixtures. Preserve newer main handoff/audit code;
verify synchronized file SHA-256 parity, installed offline tests and protected
live state/library hashes. Verify the exact remote main SHA after authorized push.
The execution receipt (test totals, commit and deployment checks) is reported with
the delivery rather than represented as evidence of educational effectiveness.
