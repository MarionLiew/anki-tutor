"""AnkiTutor deterministic CLI — the shell through which Default Bot drives
CRUD + grading + ingest. It deliberately shuns AI decisions: pedagogy is the
Default Bot's job (via SKILL.md + prompts). Failures surface as non-zero exit
with a JSON error so callers never mistake a failed write for success (§16).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DECK, LIBRARY_DIR, MODEL, ensure_dirs  # noqa: E402
from anki_client import AnkiClient, AnkiConnectUnreachable  # noqa: E402
from concept_service import ConceptService, ConceptError  # noqa: E402
from events import log_event  # noqa: E402
from ingest import IngestError, IngestService  # noqa: E402
from source_library import SourceLibrary  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ensure_dirs()
    p = argparse.ArgumentParser(prog="ankitutor", description="AnkiTutor CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    sub.add_parser("ensure")
    pc = sub.add_parser("check"); pc.add_argument("concept_id")
    pg = sub.add_parser("get"); pg.add_argument("concept_id")
    pl = sub.add_parser("due"); pl.add_argument("--limit", type=int, default=3)
    pd = sub.add_parser("search"); pd.add_argument("--topic", default=None); pd.add_argument("--level", default=None)
    pgc = sub.add_parser("grade"); pgc.add_argument("concept_id"); pgc.add_argument("ease", type=int, choices=[1, 2, 3, 4])
    pr = sub.add_parser("retire"); pr.add_argument("concept_id"); pr.add_argument("--reason", default="")
    pm = sub.add_parser("merge"); pm.add_argument("source_id"); pm.add_argument("canonical_id")
    pi = sub.add_parser("ingest"); pi.add_argument("path"); pi.add_argument("--title", default=None); pi.add_argument("--list", action="store_true", default=False)

    args = p.parse_args(argv)
    try:
        return _dispatch(args)
    except AnkiConnectUnreachable as e:
        print(json.dumps({"ok": False, "unreachable": True, "error": str(e)}))
        return 2
    except (ConceptError, IngestError, ValueError) as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1


def _dispatch(args) -> int:
    client = AnkiClient()

    if args.cmd == "health":
        print(json.dumps(client.healthcheck()))
        return 0

    if args.cmd == "ensure":
        deck = client.ensure_deck(DECK)
        model = client.ensure_model()
        log_event("ensure", deck=deck, model=model)
        print(json.dumps({"ok": True, "deck": deck, "model": model}))
        return 0

    svc = ConceptService(client)
    if args.cmd == "check":
        c = svc.get(args.concept_id)
        print(json.dumps({"exists": c is not None}))
        return 0

    if args.cmd == "get":
        c = svc.get(args.concept_id)
        if not c:
            print(json.dumps({"ok": False, "error": f"not found: {args.concept_id}"}))
            return 1
        print(json.dumps(c, ensure_ascii=False))
        return 0

    if args.cmd == "due":
        print(json.dumps(client.due_concepts(deck=DECK, limit=args.limit), ensure_ascii=False))
        return 0

    if args.cmd == "search":
        print(json.dumps(svc.search(topic=args.topic, level=args.level), ensure_ascii=False))
        return 0

    if args.cmd == "grade":
        svc.grade(args.concept_id, args.ease)
        log_event("review_graded", concept_id=args.concept_id, ease=args.ease)
        print(json.dumps({"ok": True, "ease": args.ease}))
        return 0

    if args.cmd == "retire":
        c = svc.retire(args.concept_id, reason=args.reason)
        log_event("concept_retired", concept_id=args.concept_id)
        print(json.dumps({"ok": True, "concept": c}, ensure_ascii=False))
        return 0

    if args.cmd == "merge":
        print(json.dumps(svc.merge(args.source_id, args.canonical_id), ensure_ascii=False))
        return 0

    if args.cmd == "ingest":
        lib = SourceLibrary(LIBRARY_DIR)
        if args.list:
            print(json.dumps(lib.list_manifests(), ensure_ascii=False))
            return 0
        print(json.dumps(IngestService(lib).ingest(args.path, title=args.title), ensure_ascii=False))
        return 0

    print(json.dumps({"ok": False, "error": f"unknown cmd {args.cmd}"}))
    return 1


if __name__ == "__main__":
    sys.exit(main())