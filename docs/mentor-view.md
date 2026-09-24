# Mentor view: a decision rule inside the conversation

AnkiTutor does not introduce a second persona. The same assistant teaches, notices how the session is going, and occasionally changes course. The user can ask for a review of their learning at any time; otherwise this view stays quiet unless a useful intervention is warranted.

## Evidence and boundaries

| Evidence | Source | What it can support |
|---|---|---|
| Current question, attempts, hints, transfer check, elapsed active time | TutorSession | A decision about the current turn |
| Concept level and review history | Anki | A cautious statement about repeated recall and application |
| Source and learning objective | Source Library / Concept | Whether a detour serves the learning goal |
| User's stated goal, confusion or request to stop | Conversation | Override the default route |

Elapsed wall-clock time is not study time when the conversation has been paused or diverted. A single correct answer, a level label or a short response time does not establish mastery or learning speed. If a signal is missing, say so instead of filling it in. No separate mastery score, learner profile database, scheduler or persistent psychological label is created.

## Decision at each answer

1. Diagnose the answer against the current objective. Record first-attempt success separately from success after a hint; preserve the original grading rule.
2. Ask whether another question would provide new evidence. If a learner needed a hint, test in a fresh context before treating the concept as understood. Run `python3 src/cli.py next --first wrong --latest correct --transfer not_asked` to check the gate: it returns `ask_transfer`, not a grade. The CLI reports a route and a proposed grade; it does not write to Anki.
3. Treat a changed-context question about the same learning objective as `same_concept`. If it is really a new concept, close and grade the old one first (`--extension new_concept`); do not count a correct answer to the new concept as proof of the old one. A failed transfer stays on the current concept; after self-correction, use `--transfer-first-failed` so a later correct answer cannot turn the initial miss into Good. When question budget is exhausted, close with a stated gap and Again rather than continuing indefinitely.
4. Check for a useful course correction: repeated attempts without new understanding, an increasingly narrow detail that no longer changes the answer to the learning objective, exhausted question budget, or an explicit request to pause/change topic. A thoughtful follow-up is not by itself "overthinking."
5. Choose one action: continue, give a minimal hint, change the example, revisit a prerequisite, park a detail, or pause. Explain the reason in a sentence only when changing course. The learner may choose to continue a detour.
6. Persist the question before sending it; after diagnosis and any required transfer check, write the grade through the existing CLI. If persistence fails, say so. Do not mark a chat explanation as an Anki review.

Example: "We've spent two turns on whether the difference is written 2% or two percentage points. That distinction matters, but let's check whether you can use MDE to interpret a non-significant result before going deeper."

## Strategic steering: protect time for the chosen problem

Before selecting the next card, name the user's current outcome: e.g. a falsifiable alpha hypothesis, a dated probability forecast with a resolution criterion, or a gold strategy comparison against a viable baseline. The user chooses the main line; the assistant can propose, not silently choose for them. The next lesson is the smallest blocker to producing that outcome. A mistake's frequency in Anki does not by itself make it strategically important.

Use a provisional allocation of roughly 70% on a live case and its review, 20% on the knowledge blocking that case, 10% on spaced review. These are attention budgets, not measured claims about optimal learning; change them when the user's goal or bottleneck changes. Within a session, ask whether the tangent would change a decision, evidence quality, or next action. If not, answer briefly and park it. If it would, teach only as deep as needed to resume the live case. For example, MDE interpretation may be essential to deciding whether a backtest can resolve a claim; deriving a HAC estimator is optional until the research task actually requires one.

Assess controllable work: hypotheses defined before looking, baseline and costs specified, probabilities recorded before resolution, calibration checked across forecasts, leakage/selection risk challenged, and out-of-sample observations logged. Do not promise a profitable alpha or judge learning from a single forecast's outcome. Anki schedules facts; it does not decide how to allocate the user's research time.

## When the user asks for the big picture

Summarize observed strengths, recurring failure modes and a proposed next step with the underlying evidence. Separate *this session* from *across reviews*. Do not infer a trend from one session. If review history is unavailable, give a current-session observation and identify what remains unknown. Do not output routine progress reports during ordinary teaching.

## Learning-state transitions (for the future observation log)

Record explicit `learning_entered`, `learning_paused`, `learning_resumed`, and `learning_exited` events with session ID, mode, concept ID, timestamp and a controlled reason. `session pause --reason topic_switch` distinguishes a detour from a completed session; `session close` means exit, not a grade. Do not infer an exit from a quiet conversation or a crashed process: mark it unknown until the next explicit action. If a user asks to stop without grading, pause first and preserve the current question; closing a paused session is an explicit abandonment, not mastery. Passive review also records entry only after the session has been saved.

The separate `state/learning_observations.jsonl` stores only typed learning transitions, answer verdicts, hint/transfer/grade events and explicitly flagged mentor mistakes; it rotates at 1 MiB plus two backups. Test runs are redirected to temporary state, so they no longer write into the installed learning log. The pre-existing `events.jsonl` contains historical test pollution and must not be treated as a clean learning history. Observation reports summarize only the new log and the active session, never infer mastery or a learning-speed trend from sparse evidence.

At `session start`, the CLI can bind the **current** Hermes session ID, profile, source and starting message ID (when Hermes exposes them). `observe show` then reads at most 20 recent user/assistant turns from that exact session and active learning segment via a short-lived, read-only SQLite connection. It never scans for other chats, reads tool messages, copies a transcript to AnkiTutor state, or stores raw chat text. Obvious credentials, attachments, large/mixed turns and system-memory context are omitted; this filter is a guard, not a guarantee that all private information is detected. On topic-switch pause, the segment closes at its message watermark; resuming binds a fresh current segment so off-topic messages are excluded. If there is no Hermes identity, the report says `unbound` and still shows structured events. For an old session, `observe bind` explicitly starts observing from **now**, without claiming to recover its past chat. `observe issue <type>` flags a tutor mistake from a fixed taxonomy, not an automated judgment.

This is a bounded evidence feed for improving teaching, not a complete or infallible transcript. A tutor should read `observe show` when asked to review the system or after a learning session, and state which observations are verified versus inferred. Anki still owns scheduling and review history.

## Verification scenarios

- First answer "I don't know": give a minimal cue, ask for a response, and retain Again even if later corrected.
- Correct after hint: ask one changed-context question; never relabel the first attempt Good.
- Two turns on an irrelevant detail: propose parking it, without overriding an explicit request to explore it.
- User changes topic: pause the current question; resuming presents the same question, not a new session.
- User asks "How fast am I learning?" with one recorded answer: state that speed cannot be estimated yet.
- Anki unavailable: teach if useful, but report that progress and grade were not persisted.
