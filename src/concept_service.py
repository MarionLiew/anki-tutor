"""Concept service — identity, validation, upsert, merge/retire.

Owns ConceptID semantics and the conservative lifecycle rules from doc §5.
Contains NO teaching language (doc §14: concept_service.py must not generate
pedagogical phrasing).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone

from anki_client import AnkiClient, AnkiConnectError
from config import (
    DECK,
    FIELDS,
    LEVELS,
    MANAGED_TAG,
    MODEL,
    REQUIRED_FIELDS,
    STATUS_ACTIVE,
    STATUS_MERGED,
    STATUS_RETIRED,
    VALID_STATUS,
)

_ID_SEGMENT = r"[a-z0-9\u4e00-\u9fff][a-z0-9_\u4e00-\u9fff]*"
# Same alphabet as _slug(): an ID built by make_concept_id() must always pass
# validate_concept(), which it did not while CJK was rejected here but kept there.
_ID_RE = re.compile(rf"^{_ID_SEGMENT}(\.{_ID_SEGMENT})+$")

# Tag namespaces this service owns. Any other tag on a note is left alone.
_MANAGED_TAG_PREFIXES = ("topic::", "domain::", "source::", "origin::", "error::", "level::")


class ConceptError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    return text.strip("_")


def make_concept_id(topic: str, slug: str) -> str:
    """Build a stable dotted ConceptID, e.g. ('probability','bayes_base_rate')."""
    topic = _slug(topic).replace("__", "_") or "general"
    slug = _slug(slug) or "concept"
    return f"{topic}.{slug}"


def normalize_concept_id(concept_id: str) -> str:
    cid = (concept_id or "").strip()
    if not cid:
        raise ConceptError("ConceptID is empty")
    return cid


def validate_concept(concept: dict) -> list[str]:
    """Return a list of validation problems (empty == valid)."""
    problems = []
    cid = (concept.get("concept_id") or concept.get("ConceptID") or "").strip()
    if not cid:
        problems.append("ConceptID is required")
    elif not _ID_RE.match(cid):
        problems.append(f"ConceptID '{cid}' is not a dotted stable id")
    for field, key in (
        ("Title", "title"),
        ("CoreKnowledge", "core_knowledge"),
        ("LearningObjective", "learning_objective"),
    ):
        if not (concept.get(key) or concept.get(field) or "").strip():
            problems.append(f"{field} is required")
    level = (concept.get("level") or concept.get("Level") or "").strip()
    if level not in LEVELS:
        problems.append(f"Level '{level}' must be one of {LEVELS}")
    target = (concept.get("target_level") or concept.get("TargetLevel") or "").strip()
    if target and target not in LEVELS:
        problems.append(f"TargetLevel '{target}' must be one of {LEVELS}")
    status = (concept.get("status") or concept.get("Status") or "").strip()
    if status not in VALID_STATUS:
        problems.append(f"Status '{status}' must be one of {sorted(VALID_STATUS)}")
    return problems


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except json.JSONDecodeError:
            pass
    return [p.strip() for p in text.split(",") if p.strip()]


def concept_to_note_fields(concept: dict) -> dict:
    """Convert an internal concept dict into Anki note fields."""
    prerequisites = _as_list(concept.get("prerequisites"))
    errors = _as_list(concept.get("common_errors"))
    sources = _as_list(concept.get("source_refs"))
    level = concept.get("level", "L0")
    return {
        "ConceptID": concept["concept_id"],
        "Title": concept.get("title", ""),
        "CoreKnowledge": concept.get("core_knowledge", ""),
        "LearningObjective": concept.get("learning_objective", ""),
        # Level = highest INDEPENDENTLY VERIFIED ability. TargetLevel = what the
        # teaching currently aims at. Legacy records have no TargetLevel, so it
        # falls back to Level — same meaning they had before the split.
        "Level": level,
        "TargetLevel": concept.get("target_level") or level,
        "Prerequisites": json.dumps(prerequisites, ensure_ascii=False),
        "CommonErrors": json.dumps(errors, ensure_ascii=False),
        "SourceRefs": json.dumps(sources, ensure_ascii=False),
        "SourceHash": concept.get("source_hash", "") or "",
        "Status": concept.get("status", STATUS_ACTIVE),
        "TutorInstruction": concept.get("tutor_instruction", "") or "",
        "Version": str(concept.get("version", 1)),
        "UpdatedAt": concept.get("updated_at", now_iso()),
    }


def note_to_concept(note: dict) -> dict:
    """Inverse of concept_to_note_fields."""
    f = {k: (v.get("value", "") if isinstance(v, dict) else v) for k, v in (note.get("fields") or {}).items()}
    try:
        version = int((f.get("Version") or "1").strip() or 1)
    except ValueError:
        version = 1
    return {
        "concept_id": (f.get("ConceptID") or "").strip(),
        "title": f.get("Title", ""),
        "core_knowledge": f.get("CoreKnowledge", ""),
        "learning_objective": f.get("LearningObjective", ""),
        "level": (f.get("Level") or "L0").strip(),
        # A note written before TargetLevel existed keeps its old behaviour:
        # its Level was the level teaching aimed at.
        "target_level": (f.get("TargetLevel") or f.get("Level") or "L0").strip(),
        "prerequisites": _as_list(f.get("Prerequisites")),
        "common_errors": _as_list(f.get("CommonErrors")),
        "source_refs": _as_list(f.get("SourceRefs")),
        "source_hash": f.get("SourceHash", ""),
        "status": (f.get("Status") or STATUS_ACTIVE).strip(),
        "tutor_instruction": f.get("TutorInstruction", ""),
        "version": version,
        "updated_at": f.get("UpdatedAt", ""),
        "note_id": int(note.get("noteId")) if note.get("noteId") is not None else None,
        "card_ids": note.get("_card_ids") or [],
        "tags": note.get("tags") or [],
    }


def concept_tags(concept: dict, extra: list[str] | None = None) -> list[str]:
    tags = [MANAGED_TAG]
    for key in ("domain", "topic", "source", "origin"):
        val = concept.get(key)
        if val:
            tags.append(f"{key}::{_slug(str(val))}")
    for e in _as_list(concept.get("common_errors")):
        tags.append(f"error::{_slug(e)}")
    if concept.get("level"):
        tags.append(f"level::{str(concept['level']).lower()}")
    tags.extend(extra or [])
    # dedupe, keep order
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


class ConceptService:
    """CRUD + lifecycle over Anki notes, keyed by ConceptID."""

    def __init__(self, client: AnkiClient, deck: str = DECK):
        self.client = client
        self.deck = deck

    # -- read --------------------------------------------------------------
    def get(self, concept_id: str) -> dict | None:
        note = self.client.find_concept(concept_id, deck=self.deck)
        if not note:
            return None
        concept = note_to_concept(note)
        concept["card_ids"] = self.client.cards_of_note(concept["note_id"])
        return concept

    def search(self, topic: str | None = None, level: str | None = None,
               status: str | None = None, query: str | None = None) -> list[dict]:
        """Lightweight search used by 查看掌握情况."""
        q = [f'deck:"{self.deck}"']
        if topic:
            q.append(f"tag:topic::{_slug(topic)}")
        if level:
            q.append(f"tag:level::{level.lower()}")
        ids = self.client.find_notes(" ".join(q))
        notes = self.client.notes_info(ids)
        out = []
        for n in notes:
            c = note_to_concept(n)
            if query and query.casefold() not in " ".join(
                str(c.get(k, "")) for k in ("concept_id", "title", "core_knowledge", "learning_objective")
            ).casefold():
                continue
            if status and c["status"] != status:
                continue
            out.append(c)
        return out

    # -- tags ---------------------------------------------------------------
    def _replace_managed_tags(self, note_id: int, old_tags: list[str], concept: dict) -> list[str]:
        """Bring the note's managed tags in line with the concept.

        Tags are replaced, not only accumulated: a changed topic, a raised
        level or a dropped error model must stop matching tag:: searches,
        otherwise search() reports a classification the concept no longer has.

        Only tags the concept can speak for are dropped. Classification tags
        (topic/domain/source/origin) live on the note, not in the fields, so
        they are removed only when the caller actually supplied that key —
        otherwise a later level change would silently strip a concept's topic.
        """
        new_tags = concept_tags(concept)
        stale = []
        for tag in (old_tags or []):
            namespace = tag.split("::", 1)[0] + "::"
            if namespace not in _MANAGED_TAG_PREFIXES or tag in new_tags:
                continue
            key = namespace[:-2]
            if key in ("level", "error") or key in concept:
                stale.append(tag)
        if stale:
            self.client.remove_tags([note_id], stale)
        self.client.add_tags([note_id], new_tags)
        return new_tags

    # -- create / update ---------------------------------------------------
    def create(self, concept: dict, verified_level: bool = False) -> dict:
        """Create a new concept note.

        `level` is the VERIFIED level, so a brand-new concept may only be L0
        unless verified_level=True states the learner already demonstrated it
        independently; use `target_level` for what teaching aims at (doc §5).
        """
        concept = dict(concept)
        concept["concept_id"] = normalize_concept_id(concept.get("concept_id") or "")
        concept.setdefault("level", "L0")
        concept.setdefault("status", STATUS_ACTIVE)
        problems = validate_concept(concept)
        if problems:
            raise ConceptError("; ".join(problems))
        level = (concept.get("level") or "L0").strip()
        if level != "L0" and not verified_level:
            raise ConceptError(
                f"Level '{level}' means independently VERIFIED ability, and a new concept has no evidence yet — "
                "create it with level L0 plus target_level, or pass verified_level=True when the learner has "
                "already demonstrated that level"
            )

        existing = self.get(concept["concept_id"])
        if existing:
            raise ConceptError(
                f"ConceptID '{concept['concept_id']}' already exists (note {existing['note_id']}) — "
                "use update() or merge() instead of creating a duplicate"
            )

        note_id = self.client.add_note(
            fields=concept_to_note_fields(concept),
            tags=concept_tags(concept),
            deck=self.deck,
            model=MODEL,
        )
        concept["note_id"] = note_id
        concept["card_ids"] = self.client.cards_of_note(note_id)
        return concept

    def diff(self, existing: dict, incoming: dict) -> dict:
        """Field-level diff between an existing concept and an incoming one."""
        keys = ("title", "core_knowledge", "learning_objective", "level", "status",
                "tutor_instruction", "source_hash")
        changes = {}
        for k in keys:
            a = (existing.get(k) or "")
            b = (incoming.get(k) or "")
            if str(a).strip() != str(b).strip():
                changes[k] = {"from": a, "to": b}
        # list fields: report additions/removals
        for k in ("prerequisites", "common_errors", "source_refs"):
            a = set(_as_list(existing.get(k)))
            b = set(_as_list(incoming.get(k)))
            if a != b:
                changes[k] = {"added": sorted(b - a), "removed": sorted(a - b)}
        return changes

    def update(self, concept: dict, bump_version: bool = True, merge_lists: bool = True,
               verified_level: bool = False) -> dict:
        """Update an existing note in place. Never deletes a note.

        merge_lists=True unions SourceRefs/CommonErrors/Prerequisites so we
        accumulate evidence instead of clobbering it during diff (§6.3).

        Level only moves through set_level() or verified_level=True: an
        incidental update must not claim the learner reached a higher level.
        """
        concept = dict(concept)
        cid = normalize_concept_id(concept.get("concept_id") or "")
        existing = self.get(cid)
        if not existing:
            raise ConceptError(f"ConceptID '{cid}' not found — use create()")

        incoming_level = (concept.get("level") or "").strip()
        existing_level = (existing.get("level") or "L0").strip()
        if incoming_level and incoming_level != existing_level:
            if not verified_level:
                raise ConceptError(
                    f"refusing to move Level {existing_level} -> {incoming_level} on update: Level records "
                    "independently verified ability — use set_level() after the learner demonstrated it, "
                    "or target_level for what teaching aims at"
                )
            if LEVELS.index(incoming_level) < LEVELS.index(existing_level):
                raise ConceptError(
                    f"refusing to lower Level {existing_level} -> {incoming_level} without explicit user instruction"
                )

        merged = dict(existing)
        merged.update({k: v for k, v in concept.items() if v not in (None, "")})
        if merge_lists:
            for k in ("prerequisites", "common_errors", "source_refs"):
                merged[k] = sorted(set(_as_list(existing.get(k))) | set(_as_list(concept.get(k))))
        merged["concept_id"] = cid
        if bump_version:
            merged["version"] = int(existing.get("version", 1)) + 1
        merged["updated_at"] = now_iso()

        problems = validate_concept(merged)
        if problems:
            raise ConceptError("; ".join(problems))

        note_id = existing["note_id"]
        self.client.update_note_fields(note_id, concept_to_note_fields(merged))
        merged["tags"] = self._replace_managed_tags(note_id, existing.get("tags") or [], merged)
        merged["note_id"] = note_id
        merged["card_ids"] = existing.get("card_ids") or self.client.cards_of_note(note_id)
        return merged

    def upsert(self, concept: dict, verified_level: bool = False) -> tuple[dict, bool]:
        """Create or update. Returns (concept, created_bool)."""
        cid = normalize_concept_id(concept.get("concept_id") or "")
        existing = self.get(cid)
        if existing:
            return self.update(concept, verified_level=verified_level), False
        return self.create(concept, verified_level=verified_level), True

    # -- lifecycle ---------------------------------------------------------
    def suspend(self, concept_id: str) -> dict:
        c = self.get(concept_id)
        if not c:
            raise ConceptError(f"ConceptID '{concept_id}' not found")
        self.client.suspend_cards(c["card_ids"])
        return c

    def retire(self, concept_id: str, reason: str = "") -> dict:
        """Status=retired + suspend. History is preserved (§5)."""
        c = self.get(concept_id)
        if not c:
            raise ConceptError(f"ConceptID '{concept_id}' not found")
        c["status"] = STATUS_RETIRED
        c["updated_at"] = now_iso()
        self.client.update_note_fields(c["note_id"], concept_to_note_fields(c))
        self.client.suspend_cards(c["card_ids"])
        if reason:
            self.client.add_tags([c["note_id"]], [f"retired::{_slug(reason)}"])
        return c

    def merge(self, source_id: str, canonical_id: str) -> dict:
        """Merge source concept into canonical: fold SourceRefs/CommonErrors,
        mark source merged + suspend. Nothing is deleted (§5)."""
        src = self.get(source_id)
        canon = self.get(canonical_id)
        if not src or not canon:
            raise ConceptError("both source and canonical concepts must exist")
        merged = dict(canon)
        for k in ("source_refs", "common_errors", "prerequisites"):
            merged[k] = sorted(set(_as_list(canon.get(k))) | set(_as_list(src.get(k))))
        if not merged.get("core_knowledge") and src.get("core_knowledge"):
            merged["core_knowledge"] = src["core_knowledge"]
        self.update(merged)

        src["status"] = STATUS_MERGED
        src["tutor_instruction"] = (src.get("tutor_instruction") or "") + f" [merged into {canonical_id}]"
        self.client.update_note_fields(src["note_id"], concept_to_note_fields(src))
        self.client.suspend_cards(src["card_ids"])
        self.client.add_tags([src["note_id"]], [f"merged_into::{_slug(canonical_id)}"])
        return {"canonical": self.get(canonical_id), "merged": self.get(source_id)}

    def delete_unreviewed(self, concept_id: str, confirm: bool = False) -> dict:
        """STRICT destructive path (doc §5): only unreviewed, explicitly confirmed."""
        c = self.get(concept_id)
        if not c:
            raise ConceptError(f"ConceptID '{concept_id}' not found")
        infos = self.client.cards_info(c["card_ids"])
        reviewed = any(int(ci.get("reps", 0)) > 0 for ci in infos)
        if reviewed:
            raise ConceptError(
                f"'{concept_id}' has review history (reps>0) — refusing to delete; retire instead"
            )
        if not confirm:
            raise ConceptError("delete requires confirm=True (user must confirm explicitly)")
        self.client.delete_notes([c["note_id"]])
        return {"deleted": concept_id, "note_id": c["note_id"]}

    # -- grading persistence ----------------------------------------------
    def grade(self, concept_id: str, ease: int, *, session=None, path=None) -> dict:
        """Evidence-bound, at-most-once submission.

        A persisted pending marker precedes the remote call. A timeout can mean
        Anki accepted it: do not retry until manually reconciled against Anki.
        """
        from pathlib import Path
        from config import ACTIVE_SESSION_PATH
        from session import SessionError, load_session

        path = Path(path) if path is not None else ACTIVE_SESSION_PATH
        persisted = load_session(path)
        if session is None or persisted is None or session.session_id != persisted.session_id:
            raise SessionError("grading requires the persisted current TutorSession")
        if persisted.data.get("grade_state") or session.data.get("grade_state"):
            raise SessionError("grading already submitted or outcome uncertain; reconcile manually")
        if persisted.data != session.data:
            raise SessionError("session differs from persisted state")
        if session.current_concept != concept_id or session.status != "answer_received":
            raise SessionError("concept mismatch or no evaluated answer")
        decision = session.closure_decision(budget_exhausted=not session.can_continue())
        if not ((decision.action == "close_concept" and decision.grade == ease) or
                (decision.action == "close_with_gap" and ease == 1)):
            raise SessionError(f"closure evidence does not authorize ease {ease}: {decision.action}/{decision.grade}")
        if ease not in (1, 2, 3):
            raise SessionError("Easy requires separately verified higher-level evidence")
        c = self.get(concept_id)
        if not c:
            raise ConceptError(f"ConceptID '{concept_id}' not found")
        if len(c["card_ids"]) != 1:
            raise ConceptError("expected exactly one concept card; refusing partial multi-card grading")
        card_id = c["card_ids"][0]
        before = self.client.review_history(card_id)
        session.data["grade_submission"] = {"card_id": card_id, "note_id": c["note_id"],
            "concept_id": concept_id, "ease": ease, "before": before, "submitted_at": now_iso()}
        session.data["grade_state"] = "pending"
        session.save(path)
        self.client.grade_card(card_id, ease)
        self.reconcile_grade(session, path)
        return c

    def reconcile_grade(self, session, path) -> dict:
        """Read-only reconciliation; never resubmit an uncertain review."""
        from session import SessionError
        if session.data.get("grade_state") != "pending":
            raise SessionError("no pending grade")
        submission = session.data.get("grade_submission")
        if not submission:
            raise SessionError("legacy pending lacks baseline; manual Anki audit required, no retry")
        concept = self.get(submission["concept_id"])
        if not concept or concept["note_id"] != submission["note_id"] or concept["card_ids"] != [submission["card_id"]]:
            raise SessionError("pending target identity changed; manual audit required")
        after = self.client.review_history(submission["card_id"])
        before_ids = {r["id"] for r in submission["before"]}
        new = [r for r in after if r["id"] not in before_ids]
        if not all(r in after for r in submission["before"]) or len(new) != 1 or int(new[0].get("ease", 0)) != submission["ease"]:
            raise SessionError("pending revlog absent/ambiguous/mismatched; preserved, blind retry refused")
        session.data["grade_receipt"] = {"card_id": submission["card_id"], "review": new[0], "verified_at": now_iso()}
        session.data["grade_state"] = "completed"
        session.status = "graded"
        session.save(path)
        return session.data["grade_receipt"]

    def record_error(self, concept_id: str, error_type: str) -> dict:
        """Persist a STABLE error model into CommonErrors (§11.1)."""
        c = self.get(concept_id)
        if not c:
            raise ConceptError(f"ConceptID '{concept_id}' not found")
        c["common_errors"] = sorted(set(_as_list(c.get("common_errors"))) | {error_type})
        c["updated_at"] = now_iso()
        self.client.update_note_fields(c["note_id"], concept_to_note_fields(c))
        self._replace_managed_tags(c["note_id"], c.get("tags") or [], c)
        return c

    def set_level(self, concept_id: str, level: str) -> dict:
        """Record a higher VERIFIED level (never silently lower it).

        Only call this after the learner demonstrated the level independently;
        the level teaching aims at lives in target_level and is free to change.
        """
        if level not in LEVELS:
            raise ConceptError(f"level must be one of {LEVELS}")
        c = self.get(concept_id)
        if not c:
            raise ConceptError(f"ConceptID '{concept_id}' not found")
        if LEVELS.index(level) < LEVELS.index(c.get("level", "L0")):
            raise ConceptError(
                f"refusing to lower Level {c.get('level')} -> {level} without explicit user instruction"
            )
        c["level"] = level
        c["updated_at"] = now_iso()
        self.client.update_note_fields(c["note_id"], concept_to_note_fields(c))
        c["tags"] = self._replace_managed_tags(c["note_id"], c.get("tags") or [], c)
        return c

    def set_target_level(self, concept_id: str, target_level: str) -> dict:
        """Set the level teaching aims at — a plan, not evidence of mastery.

        Falls back to the verified Level when a legacy note has no TargetLevel.
        """
        if target_level not in LEVELS:
            raise ConceptError(f"target level must be one of {LEVELS}")
        c = self.get(concept_id)
        if not c:
            raise ConceptError(f"ConceptID '{concept_id}' not found")
        c["target_level"] = target_level
        c["updated_at"] = now_iso()
        self.client.update_note_fields(c["note_id"], concept_to_note_fields(c))
        c["tags"] = self._replace_managed_tags(c["note_id"], c.get("tags") or [], c)
        return c


def safe_get(service: ConceptService, concept_id: str) -> dict | None:
    try:
        return service.get(concept_id)
    except AnkiConnectError:
        return None
