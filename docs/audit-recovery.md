# Review receipts and audit recovery

## Deterministic boundary

The tutor supplies verdicts and complete core rubrics; Python only validates their structure and prevents a supplied unmet rubric point from being labelled correct. It cannot discover omitted rubric points, authenticate tutor assertions, grade free text or prove learning. Legacy verdict-only calls remain supported. Hint delivery timestamps are caller assertions, not messaging-service receipts; `--hinted` remains a conservative legacy assertion. Self-reported understanding is not an answer.

## Submission protocol

1. Validate persisted session identity, authorized closure decision and exactly one card.
2. Read `getReviewsOfCards` for that exact card; save the entire baseline, note/card/concept identity, ease and submission timestamp in `grade_submission` before writing.
3. Persist `grade_state=pending`, then call `answerCards` once.
4. Read the exact card's revlog again. Require preserved baseline plus exactly one new row with matching ease. Save that actual row as `grade_receipt`, then mark completed.
5. A failed/uncertain write or readback stays pending. `session reconcile` reads only: it never submits a review. Missing/mismatched/multiple rows or missing legacy baseline remain blocked for manual audit. New questions, retry hints and ordinary closure cannot erase pending evidence.

This is conservative at-most-once submission, not distributed exactly-once delivery. Anki has no tutor transaction identifier: a concurrent external review with identical ease cannot be distinguished solely by revlog. Avoid simultaneous desktop reviews during chat grading. No-review pending is not automatically reset or retried. Legacy pending must be manually investigated without inventing historical evidence.

## Compatibility and classification

`search [literal-text] --topic ... --level ...` intersects literal case-insensitive text in ID/title/core/objective with existing topic/level filters. Literal text is not executable Anki search syntax. Level changes require explicit independently verified evidence; TargetLevel is freely adjustable teaching intent. Existing Level data is not bulk reclassified. Managed tag replacement preserves unrelated user tags and unspecified classification namespaces. Strategy candidates accept user-defined names; cross-candidate changes do not inherit roadmap evidence.

## Isolated live verification

Live tests must allocate a unique deck, model, state and library, use synthetic answers clearly labelled test fixtures, read exact note/card/revlog targets back and retain reviewed cards suspended. Never grade real learning cards, delete reviewed cards or feed test observations into mastery claims. Integration evidence is archived outside git along with live state/library backups. Offline tests use the in-memory backend and are not historical learning evidence.
