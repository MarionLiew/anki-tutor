# AnkiTutor

<p align="center">
  <b>English</b> · <a href="README.zh-CN.md">简体中文</a>
</p>

Fixed concepts. Fresh questions every review.

**AnkiTutor** turns your AI assistant into an adaptive tutor on top of Anki. Store one Concept per note — the thing you want to remember — and every time it's due the agent writes a **new** question. Same card, never the same review, so you practice transfer instead of the answer key.

```
Concept: base_rate_neglect
─────────────────────────────────────────────
Review 1:  "某病患病率1%，灵敏度90%，假阳10%，
           检测阳性后实际患病概率？"
Review 2:  "如果患病率是30%呢？"
─────────────────────────────────────────────
答错？ agent 给最小提示 → 你重答 →
        再出一道全新变式确认你学会了。
```

## What it does

- Fixed Concept, live questions. Tracks one knowledge point forever, serves a new scenario each review.
- A wrong answer gets a minimal hint and a retry, then a new scenario to check transfer. If you ask for an explanation, the tutor explains; that first miss still counts.
- Strict grading: forget or miss it and it's `Again`, even if you recall it right after a hint.
- The same assistant notices when a detail is consuming the session without advancing the goal, and suggests a change of course. No separate mentor persona or routine progress report.
- Anki stays the source of truth for scheduling (FSRS). AnkiTutor handles the teaching.

## Install

Paste this into any AI assistant (Hermes, Claude, GPT, …):

```text
Install AnkiTutor into ~/.anki-tutor from
https://github.com/MarionLiew/anki-tutor . Clone it, create the state/ and
library/ subdirs, pip install -r requirements.txt, then verify with:
    cd ~/.anki-tutor && python3 src/cli.py health
A successful health check returns JSON with `"version": 6`. If Anki isn't running,
report that the connection failed; don't touch existing files, keys or data.
```

Or the plain commands:

```bash
git clone https://github.com/MarionLiew/anki-tutor.git ~/.anki-tutor
cd ~/.anki-tutor
pip install -r requirements.txt
python3 src/cli.py ensure
```

Beyond Python 3.10 you need the **Anki desktop app** and the **AnkiConnect plugin** (code `2055492159`, listens on `localhost:8765`). Without Anki, local strategy/session commands still work, but Anki reads and grading cannot be verified or persisted; do not report a successful Anki write.

## Quick start

```bash
python3 src/cli.py health
python3 src/cli.py ensure
python3 src/cli.py strategy show   # unconfirmed until you choose a main line
# Example only: do not confirm a goal on behalf of a user.
python3 src/cli.py strategy propose alpha --deliverable "one falsifiable hypothesis" --criterion "baseline and costs documented"
python3 src/cli.py strategy confirm --revision 1  # only after the user confirms this exact proposal
python3 src/cli.py session start quantos.research.mde_definition --task "audit a baseline" --bottleneck "interpret MDE"
python3 src/cli.py session ask quantos.research.mde_definition "What does an MDE of 2 percentage points mean?" --objective L1
python3 src/cli.py session answer wrong  # record an evaluated answer, not a guessed verdict
python3 src/cli.py session hint
python3 src/cli.py session answer correct
python3 src/cli.py session ask quantos.research.mde_definition "New scenario: MDE 3pp, observed 1pp; what follows?" --objective L1 --transfer
python3 src/cli.py session answer correct
python3 src/cli.py grade quantos.research.mde_definition 1  # only after evidence authorizes it
```

`session show`, `session pause --reason topic_switch` and `session resume` preserve the current question across turns. Enter/pause/resume/exit transitions are recorded with reasons in a bounded local event log (1 MiB + three backups), not a full chat transcript. The CLI records the tutor's evaluated verdict; it cannot independently judge a free-text answer. An uncertain Anki write is marked pending rather than retried blindly. `next` is a read-only advisory route; `grade` checks persisted session evidence before writing.

Daily passive review (pick ≤3 due concepts, send only the first question):

```bash
python3 src/passive_review.py
```

Cron on Hermes: `hermes cron create "0 20 * * *" --name anki-tutor-review --skill anki-tutor`

## How it works

AnkiTutor keeps the teaching route tied to a goal you explicitly confirm. Mentioning alpha, Polymarket or gold makes them candidates, not an automatic priority. A goal records a concrete deliverable and what would count as finished; it is due for review after 30 days, never silently switched. One session then keeps its current task and bottleneck, while Anki alone schedules concept reviews. The local goal file lives under `state/strategy.json` (or `ANKITUTOR_STATE`) and is not a second mastery database.

| Component | Owns |
|-----------|------|
| Anki + FSRS | concept state, review history, scheduling — the source of truth |
| Source Library | original material, page anchors, SHA-256, provenance |
| TutorSession | short-lived state so the next message continues the current question |
| AnkiTutor skill | question generation, diagnosis, transfer checks, and in-conversation pacing |

The mentor view is a decision within the same conversation: it reads the current attempt and Anki history, then speaks up only when a change of course might help. One correct answer is not a learning-speed trend. The evidence and intervention rules are in [docs/mentor-view.md](docs/mentor-view.md).

```
src/
  anki_client.py      AnkiConnect HTTP wrapper (CRUD / grade / suspend)
  session.py          one-question state machine + budget (8 questions / 20 min cap)
  concept_service.py  ConceptID dedupe, merge, retire, field validation
  source_library.py   material store + hash + page index
  ingest.py           PDF/DOCX/MD parse + candidate-concept chunking
  passive_review.py   cron entry: first question only, resume before duplicate
prompts/              question generation, diagnosis, concept extraction
tests/                mock AnkiConnect — no live Anki needed
```

## What it is not

AnkiTutor isn't a new Anki, a standalone tutor bot, or an LMS. It's a skill the agent calls on demand. No web UI, no own scheduler, no generating fixed decks wholesale. Boundaries are the point — Anki stays the single scheduler, Source Library the single knowledge store.

## Requirements & tests

- Python 3.10+, `pypdf` / `python-docx` for ingest, `pytest` for tests.
- Tests run fully offline, no Anki: `python3 -m pytest tests/ -q` (mock AnkiConnect).

## License

MIT © 2026 Marion Liew. See [LICENSE](LICENSE).