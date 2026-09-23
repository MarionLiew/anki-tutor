# AnkiTutor

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
- Wrong answers get a diagnosis (`error_type`), a minimal hint, a retry, then a transfer check. The agent never just reveals the answer.
- Strict grading: forget or miss it and it's `Again`, even if you recall it right after a hint (doc rule: a hinted recall is not a first-try success).
- Anki stays the source of truth for scheduling (FSRS). AnkiTutor only handles the teaching.

## Install

Paste this into any AI assistant (Hermes, Claude, GPT, …):

```text
Install AnkiTutor into ~/.anki-tutor from
https://github.com/MarionLiew/anki-tutor . Clone it, create the state/ and
library/ subdirs, pip install -r requirements.txt, then verify with:
    cd ~/.anki-tutor && python3 src/cli.py health
"OK" means AnkiConnect on localhost:8765 answers 6. If Anki isn't running,
just say so — do not touch any of my existing files, keys, or data.
```

Or the plain commands:

```bash
git clone https://github.com/MarionLiew/anki-tutor.git ~/.anki-tutor
cd ~/.anki-tutor
pip install -r requirements.txt
python3 src/cli.py ensure
```

Beyond Python 3.10 you need the **Anki desktop app** and the **AnkiConnect plugin** (code `2055492159`, listens on `localhost:8765`). Without Anki the CLI still works but flags every write as "not persisted" — it never fakes a success.

## Quick start

```bash
python3 src/cli.py health          # is AnkiConnect reachable?
python3 src/cli.py ensure          # create deck + note type (idempotent)
python3 src/cli.py ingest notes.pdf --title "Bayes 入门"   # extract candidate concepts
python3 src/cli.py due              # what's up for review
python3 src/cli.py grade <concept> 3   # grade a review: 1=Again 2=Hard 3=Good 4=Easy
```

Daily passive review (pick ≤3 due concepts, send only the first question):

```bash
python3 src/passive_review.py
```

Cron on Hermes: `hermes cron create "0 20 * * *" --name anki-tutor-review --skill anki-tutor`

## How it works

| Component | Owns |
|-----------|------|
| Anki + FSRS | concept state, review history, scheduling — the source of truth |
| Source Library | original material, page anchors, SHA-256, provenance |
| TutorSession | short-lived state so the next message continues the current question |
| AnkiTutor skill | question generation, diagnosis, minimal hints, transfer checks |

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
- Tests run fully offline, no Anki: `python3 -m pytest tests/ -q` (15 cases, mock AnkiConnect).

## License

MIT © 2026 Marion Liew. See [LICENSE](LICENSE).