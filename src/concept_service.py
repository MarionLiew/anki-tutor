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

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*(\.[a-z0-9][a-z0-9_]*)+$")


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
    return {
        "ConceptID": concept["concept_id"],
        "Title": concept.get("title", ""),
        "CoreKnowledge": concept.get("core_knowledge", ""),
        "LearningObjective": concept.get("learning_objective", ""),
        "Level": concept.get("level", "L0"),
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
               status: str | None = None) -> list[dict]:
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
            if status and c["status"] != status:
                continue
            out.append(c)
        return out

    # -- create / update ---------------------------------------------------
    def create(self, concept: dict) -> dict:
        concept = dict(concept)
        concept["concept_id"] = normalize_concept_id(concept.get("concept_id") or "")
        problems = validate_concept(concept)
        if problems:
            raise ConceptError("; ".join(problems))

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

    def update(self, concept: dict, bump_version: bool = True, merge_lists: bool = True) -> dict:
        """Update an existing note in place. Never deletes a note.

        merge_lists=True unions SourceRefs/CommonErrors/Prerequisites so we
        accumulate evidence instead of clobbering it during diff (§6.3).
        """
        concept = dict(concept)
        cid = normalize_concept_id(concept.get("concept_id") or "")
        existing = self.get(cid)
        if not existing:
            raise ConceptError(f"ConceptID '{cid}' not found — use create()")

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

        self.client.update_note_fields(existing["note_id"], concept_to_note_fields(merged))
        # keep tags in sync (topic/level/error tags may have changed)
        self.client.add_tags([existing["note_id"]], concept_tags(merged))
        merged["note_id"] = existing["note_id"]
        merged["card_ids"] = existing.get("card_ids") or self.client.cards_of_note(existing["note_id"])
        return merged

    def upsert(self, concept: dict) -> tuple[dict, bool]:
        """Create or update. Returns (concept, created_bool)."""
        cid = normalize_concept_id(concept.get("concept_id") or "")
        existing = self.get(cid)
        if existing:
            return self.update(concept), False
        return self.create(concept), True

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
    def grade(self, concept_id: str, ease: int) -> dict:
        c = self.get(concept_id)
        if not c:
            raise ConceptError(f"ConceptID '{concept_id}' not found")
        for card_id in c["card_ids"]:
            self.client.grade_card(card_id, ease)
        return c

    def record_error(self, concept_id: str, error_type: str) -> dict:
        """Persist a STABLE error model into CommonErrors (§11.1)."""
        c = self.get(concept_id)
        if not c:
            raise ConceptError(f"ConceptID '{concept_id}' not found")
        c["common_errors"] = sorted(set(_as_list(c.get("common_errors"))) | {error_type})
        c["updated_at"] = now_iso()
        self.client.update_note_fields(c["note_id"], concept_to_note_fields(c))
        self.client.add_tags([c["note_id"]], [f"error::{_slug(error_type)}"])
        return c

    def set_level(self, concept_id: str, level: str) -> dict:
        """Raise (never silently lower) the validated mastery level."""
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
        return c


def safe_get(service: ConceptService, concept_id: str) -> dict | None:
    try:
        return service.get(concept_id)
    except AnkiConnectError:
        return None
