"""AnkiTutor deterministic CLI — the shell through which Default Bot drives
CRUD + grading + ingest. It deliberately shuns AI decisions: pedagogy is the
Default Bot's job (via SKILL.md + prompts). Failures surface as non-zero exit
with a JSON error so callers never mistake a failed write for success (§16).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DECK, LIBRARY_DIR, MODEL, ensure_dirs  # noqa: E402
from anki_client import AnkiClient, AnkiConnectUnreachable  # noqa: E402
from concept_service import ConceptService, ConceptError  # noqa: E402
from events import log_event  # noqa: E402
from ingest import IngestError, IngestService  # noqa: E402
from source_library import SourceLibrary  # noqa: E402
from progression import decide_next  # noqa: E402
from session import SessionError, load_session, new_session  # noqa: E402
import observation  # noqa: E402
import strategy  # noqa: E402


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
    pn = sub.add_parser("next", help="check whether the current concept can be closed")
    pn.add_argument("--first", required=True, choices=["correct", "partial", "wrong"])
    pn.add_argument("--latest", required=True, choices=["correct", "partial", "wrong"])
    pn.add_argument("--transfer", required=True, choices=["not_needed", "not_asked", "failed", "passed"])
    pn.add_argument("--extension", default="same_concept", choices=["same_concept", "new_concept"])
    pn.add_argument("--budget-exhausted", action="store_true")
    pn.add_argument("--transfer-first-failed", action="store_true")

    ps = sub.add_parser("strategy", help="explicit strategic goal profile (no inference)")
    actions = ps.add_subparsers(dest="strategy_action", required=True)
    for action in ("propose", "revise"):
        sp = actions.add_parser(action)
        sp.add_argument("candidate", choices=strategy.CANDIDATES)
        sp.add_argument("--deliverable", required=True, help="one concrete user-chosen output")
        sp.add_argument("--criterion", required=True, help="how the user will know it is done")
        if action == "revise":
            sp.add_argument("--revision", type=int, required=True)
    for action in ("confirm", "expire"):
        actions.add_parser(action).add_argument("--revision", type=int, required=True)
    actions.add_parser("show")

    psess = sub.add_parser("session", help="persist teaching evidence and resume it")
    steps = psess.add_subparsers(dest="session_action", required=True)
    start = steps.add_parser("start")
    start.add_argument("concept_id")
    start.add_argument("--mode", choices=["active_learning", "passive_review", "quick_quiz"], default="active_learning")
    start.add_argument("--task", default="", help="current user-chosen deliverable, not inferred")
    start.add_argument("--bottleneck", default="")
    ask = steps.add_parser("ask")
    ask.add_argument("concept_id"); ask.add_argument("question")
    ask.add_argument("--objective", choices=["L0", "L1", "L2", "L3"], default="L1")
    ask.add_argument("--transfer", action="store_true")
    answer = steps.add_parser("answer")
    answer.add_argument("verdict", choices=["correct", "partial", "wrong"])
    answer.add_argument("--hinted", action="store_true")
    hint = steps.add_parser("hint"); hint.add_argument("--level", type=int, default=1)
    pause = steps.add_parser("pause")
    pause.add_argument("--reason", choices=["user_request", "topic_switch", "interrupted"], default="user_request")
    close = steps.add_parser("close")
    close.add_argument("--reason", choices=["session_complete", "budget_exhausted", "user_request"], default="session_complete")
    for step in ("show", "resume"):
        steps.add_parser(step)

    po = sub.add_parser("observe", help="bounded learning metadata + current scoped chat")
    obs = po.add_subparsers(dest="observe_action", required=True)
    for action in ("show", "bind"):
        obs.add_parser(action)
    obs.add_parser("issue").add_argument("type", choices=sorted(observation.ISSUES))

    args = p.parse_args(argv)
    try:
        return _dispatch(args)
    except AnkiConnectUnreachable as e:
        print(json.dumps({"ok": False, "unreachable": True, "error": str(e)}))
        return 2
    except (ConceptError, IngestError, SessionError, ValueError) as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1


def _session_path() -> Path:
    return Path(os.environ.get("ANKITUTOR_STATE", str(Path(__file__).resolve().parent.parent / "state"))) / "active_session.json"


def _observation_path() -> Path:
    return _session_path().with_name("learning_observations.jsonl")


def _note(kind: str, **fields) -> None:
    try:
        observation.record(_observation_path(), kind, **fields)
    except OSError:
        # The teaching state is authoritative; observation failures are visible
        # as absent evidence, not a reason to repeat a potentially remote write.
        pass


def _observe_dispatch(args) -> int:
    s = load_session(_session_path())
    action = args.observe_action
    if action == "bind":
        if not s:
            raise SessionError("no active learning session to bind")
        if s.data.get("observation_binding"):
            raise SessionError("observation already bound; refusing to change scope")
        s.data["observation_binding"] = observation.bind()
        s.save(_session_path())
        print(json.dumps({"ok": True, "bound": True, "session_id": s.session_id}))
        return 0
    if action == "issue":
        if not s:
            raise SessionError("no active learning session for mentor issue")
        observation.record(_observation_path(), "mentor_issue", session_id=s.session_id, issue=args.type)
        print(json.dumps({"ok": True, "issue": args.type}))
        return 0
    summary = observation.report(_observation_path())
    goal = strategy.show()
    summary["goal"] = {k: goal.get(k) for k in ("status", "candidate", "deliverable", "criterion", "due_for_review", "revision")}
    summary["active_session"] = ({"session_id": s.session_id, "status": s.status,
        "concept_id": s.current_concept, "questions_used": s.questions_used,
        "task": s.data.get("task"), "bottleneck": s.data.get("bottleneck"),
        "evidence": s.data.get("evidence"), "grade_state": s.data.get("grade_state")}
        if s else None)
    summary["chat_excerpts"] = []
    summary["chat_scope"] = "unbound"
    if s and s.data.get("observation_binding"):
        binding = s.data["observation_binding"]
        db = observation.db_path()
        until = binding.get("until_id")
        if until is None:
            until = observation.watermark(db, binding)
        summary["chat_excerpts"] = observation.read_range(db, binding, until)
        summary["chat_scope"] = "active_learning_segment_only"
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def _session_dispatch(args) -> int:
    path = _session_path()
    action = args.session_action
    current = load_session(path)
    if action == "start":
        if current is not None:
            raise SessionError("existing session: resume or close it before starting another")
        goal = strategy.show()
        s = new_session(args.mode, concept_queue=[args.concept_id], concept={"concept_id": args.concept_id})
        s.data["strategy_revision"] = goal.get("revision") if goal.get("status") == "confirmed" and not goal.get("due_for_review") else None
        s.data["task"] = args.task
        s.data["bottleneck"] = args.bottleneck
        try:
            s.data["observation_binding"] = observation.bind()
        except (ValueError, OSError):
            # Non-Hermes callers can still teach; they have no chat scope.
            pass
        s.save(path)
        _note("learning_entered", session_id=s.session_id, mode=s.mode,
              concept_id=args.concept_id, reason="user_request")
        log_event("learning_entered", session_id=s.session_id, mode=s.mode,
                  concept_id=args.concept_id, reason="user_request")
    else:
        if current is None:
            raise SessionError("no active session")
        s = current
        if action == "show":
            goal = strategy.show()
            data = dict(s.to_dict())
            data["goal_needs_review"] = bool(s.data.get("strategy_revision") and
                (goal.get("status") != "confirmed" or goal.get("due_for_review") or
                 goal.get("revision") != s.data["strategy_revision"]))
            print(json.dumps(data, ensure_ascii=False))
            return 0
        if action == "resume":
            goal = strategy.show()
            if s.data.get("strategy_revision") and (goal.get("status") != "confirmed" or
                goal.get("due_for_review") or goal.get("revision") != s.data["strategy_revision"]):
                raise SessionError("strategic goal changed or is due for review; align session before resuming")
            s.resume(path)
            if s.data.get("observation_binding", {}).get("until_id") is not None:
                try:
                    s.data["observation_binding"] = observation.bind()
                    s.save(path)
                except (ValueError, OSError):
                    s.data.pop("observation_binding", None)
                    s.save(path)
            _note("learning_resumed", session_id=s.session_id, concept_id=s.current_concept,
                  reason="user_request")
            log_event("learning_resumed", session_id=s.session_id, mode=s.mode,
                      concept_id=s.current_concept, reason="user_request")
        elif action == "pause":
            if s.status != "paused":
                binding = s.data.get("observation_binding")
                if binding and "until_id" not in binding:
                    try:
                        binding["until_id"] = observation.watermark(observation.db_path(), binding)
                    except (ValueError, OSError):
                        # Preserve the session even if its Hermes transcript moved.
                        pass
                s.pause(path)
                _note("learning_paused", session_id=s.session_id, concept_id=s.current_concept,
                      reason=args.reason)
                log_event("learning_paused", session_id=s.session_id, mode=s.mode,
                          concept_id=s.current_concept, reason=args.reason)
        elif action == "ask":
            if s.status == "paused":
                raise SessionError("resume before asking")
            s.set_current_question(args.concept_id, args.question, objective=args.objective,
                                   is_transfer=args.transfer)
            s.save(path)
            _note("question_asked", session_id=s.session_id, concept_id=args.concept_id,
                  objective=args.objective)
        elif action == "answer":
            s.record_answer(args.verdict, hinted=args.hinted)
            s.save(path)
            _note("answer_evaluated", session_id=s.session_id, concept_id=s.current_concept,
                  verdict=args.verdict, hinted=bool(s.hint_level or args.hinted))
            if s.data.get("is_transfer_question"):
                _note("transfer_checked", session_id=s.session_id, concept_id=s.current_concept,
                      transfer="passed" if args.verdict == "correct" and not s.hint_level and not args.hinted else "failed")
        elif action == "hint":
            if s.status != "answer_received":
                raise SessionError("hint only after evaluated answer")
            s.advance_attempt(args.level)
            s.save(path)
            _note("hint_given", session_id=s.session_id, concept_id=s.current_concept)
        elif action == "close":
            if s.status not in ("graded", "paused"):
                raise SessionError("ungraded active session: pause instead of closing")
            concept_id = s.current_concept
            s.close(path)
            _note("learning_exited", session_id=s.session_id, concept_id=concept_id,
                  reason=args.reason)
            log_event("learning_exited", session_id=s.session_id, mode=s.mode,
                      concept_id=concept_id, reason=args.reason)
    result = dict(s.to_dict())
    if action == "answer":
        decision = s.closure_decision(budget_exhausted=not s.can_continue())
        result["decision"] = {"action": decision.action, "grade": decision.grade}
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _dispatch(args) -> int:
    if args.cmd == "observe":
        return _observe_dispatch(args)
    if args.cmd == "session":
        return _session_dispatch(args)
    if args.cmd == "strategy":
        action = args.strategy_action
        result = (strategy.show() if action == "show" else
                  strategy.propose(args.candidate, args.deliverable, args.criterion) if action == "propose" else
                  strategy.revise(args.candidate, args.revision, args.deliverable, args.criterion) if action == "revise" else
                  strategy.confirm(args.revision) if action == "confirm" else
                  strategy.expire(args.revision))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.cmd == "next":
        d = decide_next(args.first, args.latest, args.transfer,
                        extension=args.extension, budget_exhausted=args.budget_exhausted,
                        transfer_first_failed=args.transfer_first_failed)
        print(json.dumps({"action": d.action, "grade": d.grade}))
        return 0
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
        path = _session_path()
        sess = load_session(path)
        if sess is None:
            raise SessionError("no active session evidence to grade")
        svc.grade(args.concept_id, args.ease, session=sess, path=path)
        _note("grade_submitted", session_id=sess.session_id,
              concept_id=args.concept_id, ease=args.ease)
        log_event("review_graded", concept_id=args.concept_id, ease=args.ease, session_id=sess.session_id)
        print(json.dumps({"ok": True, "ease": args.ease, "session_id": sess.session_id}))
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