"""Shared mock AnkiConnect backend for offline unit tests.

Implements just enough of the AnkiClient surface (in-memory) to exercise
concept_service / session / source_library / ingest without a live Anki.
Mirrors the real AnkiConnect semantics the modules rely on (deck placement,
card due flags, suspend -> queue=-1, etc.).
"""

from __future__ import annotations

import json


def _def_fields():
    return {
        "ConceptID": "", "Title": "", "CoreKnowledge": "", "LearningObjective": "",
        "Level": "L0", "Prerequisites": "[]", "CommonErrors": "[]",
        "SourceRefs": "[]", "SourceHash": "", "Status": "active",
        "TutorInstruction": "", "Version": "1", "UpdatedAt": "",
    }


class MockAnkiClient:
    """In-memory Anki clone exposing the same methods used by concept_service."""

    def __init__(self):
        self.decks = ["系统默认", "AnkiTutor", "AnkiTutor::Concepts"]
        self.models = ["AdaptiveConcept", "Basic"]
        self._notes = {}      # note_id -> {fields, tags, model, deck}
        self._cards = {}      # card_id -> {note, deck, queue, type, reps, due}
        self._next_note = 1000
        self.up = True

    # -- health ------------------------------------------------------------
    def healthcheck(self):
        if not self.up:
            from anki_client import AnkiConnectUnreachable
            raise AnkiConnectUnreachable("mock down")
        return {"version": 6, "permission": {"permission": "granted"}}

    def is_up(self):
        return self.up

    # -- decks/models ------------------------------------------------------
    def deck_names(self):
        return list(self.decks)

    def model_names(self):
        return list(self.models)

    def ensure_deck(self, deck="AnkiTutor::Concepts"):
        if deck not in self.decks:
            self.decks.append(deck)
        return deck

    def ensure_model(self, model="AdaptiveConcept"):
        if model not in self.models:
            self.models.append(model)
        return model

    # -- notes -------------------------------------------------------------
    def add_note(self, fields, tags=None, deck="AnkiTutor::Concepts",
                 model="AdaptiveConcept", allow_duplicate=False):
        if not self.up:
            from anki_client import AnkiConnectUnreachable
            raise AnkiConnectUnreachable("mock down")
        # duplicate by ConceptID
        for n in self._notes.values():
            if n["fields"].get("ConceptID") == fields.get("ConceptID"):
                if allow_duplicate:
                    break
                raise Exception("cannot create note because it is a duplicate")
        self._next_note += 1
        nid = self._next_note
        self._notes[nid] = {"fields": dict(_def_fields(), **fields), "tags": list(tags or []), "deck": deck}
        cid = self._next_note
        self._cards[cid] = {"note": nid, "deck": deck, "queue": 0, "type": 0, "reps": 0, "due": 1}
        self._ensure_deck_chain(deck)
        return nid

    def _ensure_deck_chain(self, deck):
        parts = deck.split("::")
        acc = []
        for p in parts:
            acc.append(p)
            name = "::".join(acc)
            if name not in self.decks:
                self.decks.append(name)

    def find_notes(self, query):
        nids = []
        for nid, n in self._notes.items():
            nf = n["fields"]
            q = query
            # very small query interpreter
            deck_part = None
            for part in q.split():
                if part.startswith('deck:'):
                    deck_part = part.split('"')[1] if '"' in part else part.split(':')[1]
                if part.startswith('ConceptID:'):
                    val = part.split('"')[1]
                    if nf.get("ConceptID") != val:
                        break
                if part.startswith('tag:'):
                    val = part.split(':')[1]
                    if not any(tag == val for tag in n["tags"]):
                        break
            else:
                if deck_part and not (n["deck"] == deck_part or n["deck"].startswith(deck_part + "::")):
                    continue
                nids.append(nid)
        return nids

    def notes_info(self, note_ids):
        out = []
        for nid in note_ids:
            n = self._notes.get(nid)
            if not n:
                continue
            fields = {k: {"value": v} for k, v in n["fields"].items()}
            out.append({"noteId": str(nid), "tags": list(n["tags"]), "fields": fields})
        return out

    def find_concept(self, concept_id, deck="AnkiTutor::Concepts"):
        ids = self.find_notes(f'deck:"{deck}" ConceptID:"{concept_id}"')
        if not ids:
            return None
        notes = self.notes_info(ids)
        for n in notes:
            if (n.get("fields", {}).get("ConceptID", {}).get("value", "") or "").strip() == concept_id:
                return n
        return notes[0] if notes else None

    def update_note_fields(self, note_id, fields):
        if note_id not in self._notes:
            raise Exception("note not found")
        self._notes[note_id]["fields"].update(fields)

    def add_tags(self, note_ids, tags):
        if isinstance(tags, str):
            tlist = tags.split()
        else:
            tlist = tags
        for nid in note_ids:
            if nid in self._notes:
                self._notes[nid]["tags"] = list(dict.fromkeys(self._notes[nid]["tags"] + tlist))

    def remove_tags(self, note_ids, tags):
        if isinstance(tags, str):
            tlist = tags.split()
        else:
            tlist = tags
        for nid in note_ids:
            if nid in self._notes:
                self._notes[nid]["tags"] = [t for t in self._notes[nid]["tags"] if t not in tlist]

    def delete_notes(self, note_ids):
        for nid in note_ids:
            self._notes.pop(nid, None)
            for cid in list(self._cards):
                if self._cards[cid]["note"] == nid:
                    self._cards.pop(cid, None)

    # -- cards -------------------------------------------------------------
    def find_cards(self, query):
        ids = self.find_notes(query) if query else list(self._notes)
        cards = []
        for cid, c in self._cards.items():
            if c["note"] in ids:
                cards.append(cid)
        return cards

    def cards_info(self, card_ids):
        out = []
        for cid in card_ids:
            c = self._cards.get(cid)
            if not c:
                continue
            n = self._notes.get(c["note"], {})
            fields = {k: {"value": v} for k, v in n.get("fields", {}).items()}
            out.append({
                "cardId": cid, "note": c["note"], "deckName": c["deck"],
                "queue": c["queue"], "type": c["type"], "reps": c["reps"],
                "fields": fields, "factor": 0, "interval": 0, "due": c["due"],
            })
        return out

    def cards_of_note(self, note_id):
        return [cid for cid, c in self._cards.items() if c["note"] == note_id]

    def are_due(self, card_ids):
        return [self._cards[cid]["due"] == 1 and self._cards[cid]["queue"] == 0 for cid in card_ids]

    def due_concepts(self, deck="AnkiTutor::Concepts", limit=None):
        cards = self.find_cards(f'deck:"{deck}" ')
        infos = self.cards_info(cards)
        by_note = {}
        for ci in infos:
            by_note.setdefault(int(ci["note"]), []).append(ci["cardId"])
        notes = self.notes_info(list(by_note.keys()))
        out = []
        for n in notes:
            if (n.get("fields", {}).get("Status", {}).get("value", "") or "").strip() != "active":
                continue
            nid = int(n["noteId"])
            if any(self._cards[c]["due"] == 1 for c in by_note[nid]):
                n["_card_ids"] = by_note[nid]
                out.append(n)
        return out[:limit] if limit else out

    def grade_card(self, card_id, ease):
        if card_id not in self._cards:
            raise Exception("card not found")
        self._cards[card_id]["reps"] += 1
        if ease == 1:
            self._cards[card_id]["queue"] = 1  # learning
            self._cards[card_id]["due"] = 1
        else:
            self._cards[card_id]["queue"] = 2
            self._cards[card_id]["due"] = 0

    def suspend_cards(self, card_ids):
        for cid in card_ids:
            if cid in self._cards:
                self._cards[cid]["queue"] = -1

    def unsuspend_cards(self, card_ids):
        for cid in card_ids:
            if cid in self._cards:
                self._cards[cid]["queue"] = 0