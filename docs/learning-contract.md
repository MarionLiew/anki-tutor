# Learning and memory contract / 学习与记忆约定

This is the authoritative learning contract. Engineering maintenance is governed
by the root `AGENTS.md`; operational details live in `SKILL.md`, the data contract
in `engineering-spec.md`, and mentor interventions in `mentor-view.md`.

## Goal-Directed Learning / 目的导向
Learning serves real capability, not card counts or course completion. Track
explains why to learn; Roadmap identifies capabilities and acceptance evidence;
Concept supplies durable knowledge. The user chooses Focus, confirms/revises
outcomes, and explicitly accepts completion. Several Tracks can coexist. Temporary
learning does not require a Track. Never infer or confirm a goal from chat silence.

## Mastery Requires Evidence / 掌握须有证据
Keep four distinct claims: memory retention, conceptual understanding and transfer,
independent real-task performance, and final Outcome attainment. Anki Good, L3,
card totals, repetitions, model self-assessment and subjective understanding do
not establish Roadmap capability or Track completion. Record independently
produced artifacts or verified real judgments against criteria, including source,
context and provenance. Assisted practice is not independent production.
Changing Outcome or Criterion invalidates automatic inheritance of its Roadmap;
old evidence stays in revision history, not as proof of the new outcome.

## Active Recall and Feedback / 主动检索与反馈
Ask one dynamic question at a time. Record it successfully before sending it.
Diagnose genuine first answers; give the smallest useful hint, then retry and
verify independently in a new context. A failed first retrieval remains failed
when the learner later answers after assistance. `assisted_correct` transfer is
not independent success. L0 recognition, L1 recall, L2 application and L3
construction describe verified ability; TargetLevel is a teaching plan. Never
backfill verified Level from an import or a plan.

Again(1): first wrong/unable or substantive hint needed. Hard(2): first independent
partial/hesitant answer. Good(3): first independently correct at the objective.
Easy(4): fast independent correctness plus higher-level evidence, used cautiously.
A required L2/L3 transfer cannot be waived with `not_needed`. Correcting a failed
transfer does not erase the original failure. Budget exhaustion closes a gap,
not a mastery claim. Measured study time excludes pauses and waiting.

## Durable Knowledge / 稳定知识
Create Concepts only for stable transferable knowledge worth retaining, with
sources, boundaries, objectives and judging criteria. Temporary cases and variants
are normally not cards. Search and reuse stable ConceptID across Tracks: linking
another `track::<id>` tag does not create another note or schedule. Tags express
association only; ordinary concept edits preserve Track and user tags.

## Spaced Repetition / 间隔复习
Anki/FSRS alone schedules long-term memory. Cron queries due, unsuspended cards
whose Concept Status is active, across all Tracks and without requiring tags.
Completed/archived Track Concepts and unassociated Concepts remain eligible.
Track completion/archive preserves goals, evidence, tags, Concepts and history.
Only a separate explicit user instruction may invoke suspend/retire/merge.

One foreground TutorSession and one displayed question are permitted. Track
switching parks an unfinished session as a dormant snapshot before releasing the
foreground; restoration retains original question, first answer, hint delivery,
transfer and grading evidence. Stored snapshots do not run and cannot block
normal due review unless their state is unsafe (e.g. pending grading). Cron does
not auto-resume dormant Tracks, advance questions or repeatedly deliver the
foreground question. A light reminder is optional only when no due review needs
the foreground; preparing a reminder is not proof of message delivery.

## Truthful Persistence / 真实持久化
CLI success is not WeChat delivery. Prepare hints without counting them; record
hint reliance only after actual delivery (`--sent-at`) or an explicit truthful
legacy hint declaration. Grading success requires exact-card revlog read-back.
Uncertain/pending grades block pause, Focus switch, closure and new teaching;
`session reconcile` reads only, never blindly resubmits. Unreadable state or an
unsafe snapshot blocks teaching until inspected. Preserve evidence and report
failures instead of guessing or teaching around the CLI.

## Effectiveness Over Complexity / 效果优先
Evaluate delayed recall, independent unfamiliar-context application and real-task
completion. Do not claim effectiveness from model confidence, counts or a feeling
of comprehension. Complex teaching mechanisms need a measurable benefit or a
specific research purpose. No second scheduler, mastery DB, recommendation system
or fabricated completion percentage.
