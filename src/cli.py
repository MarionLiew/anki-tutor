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

from config import DECK, LEVELS, LIBRARY_DIR, MODEL, MIGRATABLE_FIELDS, ensure_dirs  # noqa: E402
from anki_client import AnkiClient, AnkiConnectUnreachable, AnkiConnectError  # noqa: E402
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
    pd.add_argument("query", nargs="?", default=None, help="literal free-text concept search")
    pgc = sub.add_parser("grade"); pgc.add_argument("concept_id"); pgc.add_argument("ease", type=int, choices=[1, 2, 3, 4])
    pr = sub.add_parser("retire"); pr.add_argument("concept_id"); pr.add_argument("--reason", default="")
    pm = sub.add_parser("merge"); pm.add_argument("source_id"); pm.add_argument("canonical_id")
    pi = sub.add_parser("ingest"); pi.add_argument("path"); pi.add_argument("--title", default=None); pi.add_argument("--list", action="store_true", default=False)
    pn = sub.add_parser("next", help="check whether the current concept can be closed")
    pn.add_argument("--first", required=True, choices=["correct", "partial", "wrong"])
    pn.add_argument("--latest", required=True, choices=["correct", "partial", "wrong"])
    pn.add_argument("--transfer", required=True, choices=["not_needed", "not_asked", "failed", "passed", "assisted_correct"])
    pn.add_argument("--extension", default="same_concept", choices=["same_concept", "new_concept"])
    pn.add_argument("--budget-exhausted", action="store_true")
    pn.add_argument("--transfer-first-failed", action="store_true")
    pn.add_argument("--hints-used", action="store_true", help="any hint was needed (forces Again)")
    pn.add_argument("--objective", default="L1", choices=LEVELS)

    pcon = sub.add_parser("concept", help="create/update the concept notes the tutor teaches")

    def _concept_fields(sp, creating: bool):
        # Title/CoreKnowledge/LearningObjective are validated by the service
        # (which also accepts them from --json), so they are not argparse-required.
        sp.add_argument("--id", dest="concept_id", required=True)
        sp.add_argument("--title", required=False)
        sp.add_argument("--core", required=False, help="core knowledge: the principle and its boundary")
        sp.add_argument("--objective", required=False, help="learning objective + how it is judged")
        sp.add_argument("--level", choices=LEVELS, default=None, help="VERIFIED level (default L0)")
        sp.add_argument("--target-level", choices=LEVELS, default=None, help="level teaching aims at")
        sp.add_argument("--error", action="append", default=[], help="stable error model (repeatable)")
        sp.add_argument("--prereq", action="append", default=[])
        sp.add_argument("--source-ref", action="append", default=[], help="library ref, e.g. p12:bayes")
        sp.add_argument("--source-hash", default="")
        sp.add_argument("--domain", default="")
        sp.add_argument("--topic", default="")
        sp.add_argument("--tutor-instruction", default="")
        sp.add_argument("--verified", action="store_true",
                        help="the learner already demonstrated --level independently (else Level stays L0)")
        sp.add_argument("--json", dest="json_path", default=None,
                        help="concept object as JSON (file path, or - for stdin); flags override it")

    cact = pcon.add_subparsers(dest="concept_action", required=True)
    for action in ("create", "update", "upsert"):
        _concept_fields(cact.add_parser(action), creating=(action == "create"))
    cerr = cact.add_parser("error"); cerr.add_argument("--id", dest="concept_id", required=True); cerr.add_argument("--type", required=True)
    clv = cact.add_parser("level")
    clv.add_argument("--id", dest="concept_id", required=True)
    clv.add_argument("--verified", choices=LEVELS, help="record a higher verified level (evidence-backed)")
    clv.add_argument("--target", choices=LEVELS, help="set the level teaching aims at (a plan)")
    for action in ("link", "unlink"):
        cp = cact.add_parser(action)
        cp.add_argument("concept_id"); cp.add_argument("track_id")
    pd.add_argument("--track", dest="track_id", default=None)

    ps = sub.add_parser("strategy", help="explicit strategic goal profile (no inference)")
    actions = ps.add_subparsers(dest="strategy_action", required=True)
    create = actions.add_parser("create")
    create.add_argument("track_id"); create.add_argument("name")
    create.add_argument("--outcome", required=True); create.add_argument("--criterion", required=True)
    actions.add_parser("list")
    actions.add_parser("migrate")
    focus = actions.add_parser("focus")
    focus.add_argument("track_id", nargs="?", help="omit to clear focus for temporary learning")
    for action in ("complete", "archive", "activate"):
        sp = actions.add_parser(action)
        sp.add_argument("track_id"); sp.add_argument("--confirmed", action="store_true")
    for action in ("propose", "revise"):
        sp = actions.add_parser(action)
        sp.add_argument("candidate", help="the user's own goal line (alpha / Polymarket / gold are examples only)")
        sp.add_argument("--outcome", required=True, help="the end result the user wants")
        sp.add_argument("--criterion", required=True, help="how the user will know it is done")
        if action == "revise":
            sp.add_argument("--revision", type=int, required=True)
    for action in ("confirm", "expire"):
        actions.add_parser(action).add_argument("--revision", type=int, required=True)
    actions.add_parser("show").add_argument("--track", dest="track_id", default=None)
    pa = actions.add_parser("asked")  # tutor just proactively asked the user for direction
    pa.add_argument("--because", choices=["cron_delivery", "session_opening", "review_due"], required=True)

    pr = actions.add_parser("roadmap")
    ract = pr.add_subparsers(dest="roadmap_action", required=True)
    ra = ract.add_parser("add")
    ra.add_argument("capability"); ra.add_argument("--kind", choices=["required", "optional"], default="required")
    re_ = ract.add_parser("evidence")
    re_.add_argument("entry_id")
    re_.add_argument("evidence")
    re_.add_argument("--clear", action="store_true", default=False)
    rg = ract.add_parser("gap")
    rg.add_argument("--serving", default="", help="current task the teaching should serve")

    psess = sub.add_parser("session", help="persist teaching evidence and resume it")
    steps = psess.add_subparsers(dest="session_action", required=True)
    start = steps.add_parser("start")
    start.add_argument("concept_id")
    start.add_argument("--mode", choices=["active_learning", "passive_review", "quick_quiz"], default="active_learning")
    start.add_argument("--task", default="", help="current user-chosen deliverable, not inferred")
    start.add_argument("--bottleneck", default="")
    start.add_argument("--temporary", action="store_true", help="learn without a Track")
    ask = steps.add_parser("ask")
    ask.add_argument("concept_id"); ask.add_argument("question")
    ask.add_argument("--objective", choices=["L0", "L1", "L2", "L3"], default="L1")
    ask.add_argument("--transfer", action="store_true")
    answer = steps.add_parser("answer")
    answer.add_argument("verdict", choices=["correct", "partial", "wrong"])
    answer.add_argument("--hinted", action="store_true")
    answer.add_argument("--rubric", help="JSON list of criterion/met/evidence items")
    answer.add_argument("--answer-text", default="")
    answer.add_argument("--spontaneous", action="store_true")
    hint = steps.add_parser("hint"); hint.add_argument("--level", type=int, default=1)
    hint.add_argument("--sent-at", help="actual delivery ISO timestamp; omit to prepare retry without counting hint")
    steps.add_parser("reconcile")
    pause = steps.add_parser("pause")
    pause.add_argument("--reason", choices=["user_request", "topic_switch", "interrupted"], default="user_request")
    close = steps.add_parser("close")
    close.add_argument("--reason", choices=["session_complete", "budget_exhausted", "user_request", "missing_concept"], default="session_complete")
    clock = steps.add_parser("time")
    clock.add_argument("seconds", type=int, help="explicit observed active study seconds, never wall waiting")
    steps.add_parser("show")
    steps.add_parser("snapshots")
    steps.add_parser("resume").add_argument("--snapshot", default=None)

    po = sub.add_parser("observe", help="bounded learning metadata + current scoped chat")
    obs = po.add_subparsers(dest="observe_action", required=True)
    for action in ("show", "bind"):
        obs.add_parser(action)
    obs.add_parser("issue").add_argument("type", choices=sorted(observation.ISSUES))

    args = p.parse_args(argv)
    try:
        from session import state_lock
        with state_lock(_session_path()):
            return _dispatch(args)
    except AnkiConnectUnreachable as e:
        print(json.dumps({"ok": False, "unreachable": True, "error": str(e)}))
        return 2
    except (ConceptError, IngestError, SessionError, ValueError, AnkiConnectError) as e:
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
    summary["goal"] = {k: goal.get(k) for k in ("status", "candidate", "outcome", "criterion", "due_for_review", "revision")}
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
    from session import assert_safe_snapshots
    if action not in ("show", "snapshots", "reconcile"):
        assert_safe_snapshots(path)
    if action == "snapshots":
        snapshots = []
        for file in sorted((path.parent / "paused_sessions").glob("*.json")):
            paused = load_session(file)
            if paused:
                snapshots.append({"key": file.stem, "session_id": paused.session_id, "track_id": paused.data.get("track_id"), "concept_id": paused.current_concept})
        print(json.dumps({"snapshots": snapshots}, ensure_ascii=False))
        return 0
    if action == "resume" and not current and not args.snapshot:
        args.snapshot = strategy.show().get("id")
    if action == "resume" and args.snapshot:
        from session import restore_snapshot
        s = restore_snapshot(args.snapshot, path)
        if not s:
            raise SessionError("no paused snapshot")
        print(json.dumps(s.to_dict(), ensure_ascii=False))
        return 0
    if current and current.data.get("grade_state") == "pending" and action not in ("show", "reconcile"):
        raise SessionError("pending grade: reconcile before changing session")
    if action == "start":
        if current and current.status == "paused":
            from session import park_session
            park_session(current, path)
            current = None
        if current is not None:
            raise SessionError("existing session: resume or close it before starting another")
        goal = strategy.show()
        s = new_session(args.mode, concept_queue=[args.concept_id], concept={"concept_id": args.concept_id})
        s.data["track_id"] = None if args.temporary else goal.get("id")
        if s.data["track_id"] and (path.parent / "paused_sessions" / (s.data["track_id"] + ".json")).exists():
            raise SessionError("paused snapshot exists for focus: resume it or use --temporary")
        s.data["strategy_revision"] = goal.get("revision") if not args.temporary and goal.get("status") == "confirmed" and not goal.get("due_for_review") else None
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
                s.pause(path, reason=args.reason)
                if s.data.get("track_id"):
                    from session import park_session
                    park_session(s, path)
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
            s.record_answer(args.verdict, hinted=args.hinted,
                rubric=json.loads(args.rubric) if args.rubric else None,
                answer_text=args.answer_text, spontaneous=args.spontaneous)
            s.save(path)
            _note("answer_evaluated", session_id=s.session_id, concept_id=s.current_concept,
                  verdict=args.verdict, hinted=bool(s.hint_level or args.hinted))
            if s.data.get("is_transfer_question"):
                transfer = "passed" if args.verdict == "correct" and not s.hint_level and not args.hinted else (
                    "assisted_correct" if args.verdict == "correct" else "failed")
                _note("transfer_checked", session_id=s.session_id, concept_id=s.current_concept,
                      transfer=transfer)
        elif action == "hint":
            if s.status != "answer_received" and not (args.sent_at and s.status == "waiting_answer" and not s.hint_level):
                raise SessionError("hint only after evaluated answer")
            if args.sent_at:
                from datetime import datetime, timezone
                sent = datetime.fromisoformat(args.sent_at)
                if sent.tzinfo is None or sent > datetime.now(timezone.utc):
                    raise SessionError("hint delivery timestamp must be timezone-aware and not future")
                s.data["hint_sent_at"] = args.sent_at
            else:
                s.data.pop("hint_sent_at", None)
            s.advance_attempt(args.level if args.sent_at else 0)
            s.save(path)
            _note("hint_given" if args.sent_at else "retry_prepared", session_id=s.session_id, concept_id=s.current_concept)
        elif action == "reconcile":
            ConceptService(AnkiClient()).reconcile_grade(s, path)
        elif action == "time":
            if args.seconds < 0 or s.status == "paused":
                raise SessionError("nonnegative measured time requires an active session")
            if s.data.get("time_accounting") != "explicit":
                s.data["legacy_wall_seconds_unverified"] = s.data.get("active_seconds", 0)
                s.data["active_seconds"] = 0
            s.data["time_accounting"] = "explicit"
            s.data["active_seconds"] += args.seconds
            s.save(path)
        elif action == "close":
            if args.reason == "missing_concept" and ConceptService(AnkiClient()).get(s.current_concept):
                raise SessionError("concept exists; missing_concept recovery refused")
            if s.status not in ("graded", "paused") and args.reason not in ("missing_concept", "budget_exhausted", "user_request"):
                raise SessionError("ungraded active session: pause instead of closing")
            if s.data.get("grade_state") == "pending":
                # A pending grade may or may not have reached Anki. Closing here
                # would drop the marker and let the same concept be graded again,
                # writing a second review — reconcile first (doc §11).
                raise SessionError(
                    "grade submission outcome is uncertain (pending): check Anki before closing, "
                    "including missing_concept recovery; never discard pending evidence"
                )
            archive = path.parent / "closed_sessions" / (s.session_id + ".json")
            s.data["closure_reason"] = args.reason
            s.data["closure_outcome"] = "graded" if s.data.get("grade_state") == "completed" else "ungraded_no_mastery_claim"
            s.save(archive)
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


_CONCEPT_SCALARS = {
    "title": "title",
    "core": "core_knowledge",
    "objective": "learning_objective",
    "level": "level",
    "target_level": "target_level",
    "source_hash": "source_hash",
    "domain": "domain",
    "topic": "topic",
    "tutor_instruction": "tutor_instruction",
}
_CONCEPT_LISTS = {
    "error": "common_errors",
    "prereq": "prerequisites",
    "source_ref": "source_refs",
}


def _concept_from_args(args) -> dict:
    """Build a concept dict from CLI flags, with an optional JSON base.

    Flags win over the JSON payload so a caller can override one field of a
    full record without rewriting it.
    """
    data: dict = {}
    if getattr(args, "json_path", None):
        raw = sys.stdin.read() if args.json_path == "-" else Path(args.json_path).read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except (OSError, ValueError) as e:
            raise ConceptError(f"--json is not a readable JSON object: {e}") from e
        if not isinstance(data, dict):
            raise ConceptError("--json must contain a JSON object")
    for flag, key in _CONCEPT_SCALARS.items():
        value = getattr(args, flag, None)
        if value:
            data[key] = value
    for flag, key in _CONCEPT_LISTS.items():
        values = getattr(args, flag, None) or []
        if values:
            existing = data.get(key) or []
            if isinstance(existing, str):
                existing = [p.strip() for p in existing.split(",") if p.strip()]
            data[key] = list(existing) + list(values)
    concept_id = (getattr(args, "concept_id", None) or data.get("concept_id") or "").strip()
    if not concept_id:
        raise ConceptError("--id is required")
    data["concept_id"] = concept_id
    return data


def _concept_dispatch(args, svc: ConceptService) -> int:
    action = args.concept_action
    if action in ("link", "unlink"):
        method = svc.link_track if action == "link" else svc.unlink_track
        print(json.dumps({"ok": True, "concept": method(args.concept_id, args.track_id)}, ensure_ascii=False))
        return 0
    if action == "error":
        c = svc.record_error(args.concept_id, args.type)
        log_event("concept_error_recorded", concept_id=args.concept_id, error_type=args.type)
        print(json.dumps({"ok": True, "concept": c}, ensure_ascii=False))
        return 0
    if action == "level":
        if bool(args.verified) == bool(args.target):
            raise ConceptError("pass exactly one of --verified <level> or --target <level>")
        if args.verified:
            c = svc.set_level(args.concept_id, args.verified)
            log_event("concept_level_verified", concept_id=args.concept_id, level=args.verified)
        else:
            c = svc.set_target_level(args.concept_id, args.target)
            log_event("concept_target_level", concept_id=args.concept_id, target_level=args.target)
        print(json.dumps({"ok": True, "concept": c}, ensure_ascii=False))
        return 0
    concept = _concept_from_args(args)
    if action == "create":
        result = svc.create(concept, verified_level=args.verified)
        created = True
    elif action == "update":
        result = svc.update(concept, verified_level=args.verified)
        created = False
    else:
        result, created = svc.upsert(concept, verified_level=args.verified)
    log_event(f"concept_{action}", concept_id=result["concept_id"], note_id=result.get("note_id"))
    print(json.dumps({"ok": True, "created": created, "concept": result}, ensure_ascii=False))
    return 0


def _dispatch(args) -> int:
    if args.cmd == "observe":
        return _observe_dispatch(args)
    if args.cmd == "session":
        return _session_dispatch(args)
    if args.cmd == "strategy":
        action = args.strategy_action
        if action == "create":
            result = strategy.create_track(args.track_id, args.name, args.outcome, args.criterion)
        elif action == "list":
            result = strategy.list_tracks()
        elif action == "migrate":
            result = strategy.migrate()
        elif action == "focus":
            result = strategy.set_focus(args.track_id)
        elif action in ("complete", "archive", "activate"):
            result = strategy.set_track_status(args.track_id, {"complete": "completed", "archive": "archived", "activate": "active"}[action], args.confirmed)
        elif action == "show":
            result = strategy.get_track(args.track_id) if args.track_id else strategy.show()
        elif action == "asked":
            result = strategy.mark_asked(getattr(args, "because", None)) or {"status": "unconfirmed", "candidates": list(strategy.CANDIDATES)}
        elif action == "roadmap":
            if args.roadmap_action == "add":
                result = strategy.roadmap_add(args.capability, kind=args.kind)
            elif args.roadmap_action == "evidence":
                result = strategy.roadmap_evidence(args.entry_id,
                    "" if getattr(args, "clear", False) else args.evidence,
                    "no_evidence" if getattr(args, "clear", False) else "evidenced")
            else:
                result = {"gap": strategy.next_gap(serving=getattr(args, "serving", "") or None)}
        elif action == "propose":
            result = strategy.propose(args.candidate, args.outcome, args.criterion)
        elif action == "revise":
            result = strategy.revise(args.candidate, args.revision, args.outcome, args.criterion)
        elif action == "confirm":
            result = strategy.confirm(args.revision)
        else:
            result = strategy.expire(args.revision)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.cmd == "next":
        d = decide_next(args.first, args.latest, args.transfer,
                        extension=args.extension, budget_exhausted=args.budget_exhausted,
                        transfer_first_failed=args.transfer_first_failed,
                        hints_used=args.hints_used, objective=args.objective)
        print(json.dumps({"action": d.action, "grade": d.grade}))
        return 0
    client = AnkiClient()

    if args.cmd == "health":
        print(json.dumps(client.healthcheck()))
        return 0

    if args.cmd == "ensure":
        deck = client.ensure_deck(DECK)
        model = client.ensure_model()
        # Schema migration: an install created before a field existed must gain
        # it here, or every later updateNoteFields naming it is rejected.
        migrate = getattr(client, "add_model_fields", None)
        raw_added = migrate(MODEL, MIGRATABLE_FIELDS) if callable(migrate) else []
        added = list(raw_added) if isinstance(raw_added, (list, tuple, set)) else []
        log_event("ensure", deck=deck, model=model, added_fields=added)
        print(json.dumps({"ok": True, "deck": deck, "model": model, "added_fields": added}))
        return 0

    svc = ConceptService(client)
    if args.cmd == "concept":
        return _concept_dispatch(args, svc)
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
        print(json.dumps(svc.search(topic=args.topic, level=args.level, query=args.query, track_id=args.track_id), ensure_ascii=False))
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