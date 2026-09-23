"""AnkiConnect HTTP client.

Pure transport + CRUD. Contains NO teaching logic (doc §14: anki_client.py
must not carry pedagogical decisions) and never fabricates success — when
AnkiConnect is unreachable the caller gets an exception and must report
"not persisted" rather than pretending the write happened (doc §16).

Uses only the standard library (urllib) so it runs under any interpreter the
Hermes runtime hands it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from config import (
    ANKI_API_KEY,
    ANKI_URL,
    ANKI_VERSION,
    CARD_TEMPLATES,
    DECK,
    FIELDS,
    MANAGED_TAG,
    MODEL,
    MODEL_CSS,
)


class AnkiConnectError(RuntimeError):
    """Any failure talking to AnkiConnect (network, HTTP, or API-level error)."""


class AnkiConnectUnreachable(AnkiConnectError):
    """AnkiConnect could not be contacted at all — nothing was persisted."""


class AnkiClient:
    def __init__(self, url: str = ANKI_URL, api_key: str | None = ANKI_API_KEY, timeout: float = 15.0):
        self.url = url
        self.api_key = api_key
        self.timeout = timeout

    # -- transport ---------------------------------------------------------
    def invoke(self, action: str, **params):
        payload = {"action": action, "version": ANKI_VERSION}
        if params:
            payload["params"] = params
        if self.api_key:
            payload["key"] = self.api_key
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise AnkiConnectUnreachable(f"AnkiConnect unreachable at {self.url}: {exc}") from exc

        if isinstance(body, dict) and body.get("error"):
            raise AnkiConnectError(f"{action} failed: {body['error']}")
        return body.get("result") if isinstance(body, dict) else body

    # -- health ------------------------------------------------------------
    def healthcheck(self) -> dict:
        version = self.invoke("version")
        permission = self.invoke("requestPermission")
        return {"version": version, "permission": permission}

    def is_up(self) -> bool:
        try:
            self.invoke("version")
            return True
        except AnkiConnectError:
            return False

    # -- decks / models ----------------------------------------------------
    def deck_names(self) -> list[str]:
        return self.invoke("deckNames") or []

    def model_names(self) -> list[str]:
        return self.invoke("modelNames") or []

    def ensure_deck(self, deck: str = DECK) -> str:
        if deck not in self.deck_names():
            self.invoke("createDeck", deck=deck)
        return deck

    def ensure_model(self, model: str = MODEL) -> str:
        if model not in self.model_names():
            self.invoke(
                "createModel",
                modelName=model,
                inOrderFields=FIELDS,
                css=MODEL_CSS,
                isCloze=False,
                cardTemplates=CARD_TEMPLATES,
            )
        return model

    def model_field_names(self, model: str = MODEL) -> list[str]:
        return self.invoke("modelFieldNames", modelName=model) or []

    # -- notes -------------------------------------------------------------
    def find_notes(self, query: str) -> list[int]:
        return self.invoke("findNotes", query=query) or []

    def notes_info(self, note_ids: list[int]) -> list[dict]:
        if not note_ids:
            return []
        return self.invoke("notesInfo", notes=note_ids) or []

    def find_concept(self, concept_id: str, deck: str = DECK) -> dict | None:
        """Return the note dict for a ConceptID, or None if absent.

        ConceptID is stored as a field, so search both by field and by the
        escaped literal to stay robust across Anki search quirks.
        """
        query = f'deck:"{deck}" ConceptID:"{concept_id}"'
        ids = self.find_notes(query)
        if not ids:
            return None
        notes = self.notes_info(ids)
        for n in notes:
            if (n.get("fields", {}).get("ConceptID", {}).get("value", "") or "").strip() == concept_id:
                return n
        return notes[0] if notes else None

    def add_note(
        self,
        fields: dict,
        tags: list[str] | None = None,
        deck: str = DECK,
        model: str = MODEL,
        allow_duplicate: bool = False,
    ) -> int:
        note = {
            "deckName": deck,
            "modelName": model,
            "fields": fields,
            "tags": tags or [MANAGED_TAG],
            "options": {"allowDuplicate": allow_duplicate, "duplicateScope": "deck"},
        }
        result = self.invoke("addNote", note=note)
        if result is None:
            raise AnkiConnectError("addNote returned None (duplicate rejected?)")
        note_id = int(result)
        # Anki 26.x: createNote's note_type()['did'] does not reliably stick,
        # so cards can land in the default deck. Force the target deck after
        # the fact via changeDeck (raw did update) — idempotent + explicit.
        card_ids = self.cards_of_note(note_id)
        if card_ids and deck:
            self.invoke("changeDeck", cards=card_ids, deck=deck)
        return note_id

    def update_note_fields(self, note_id: int, fields: dict) -> None:
        self.invoke("updateNoteFields", note={"id": int(note_id), "fields": fields})

    def add_tags(self, note_ids: list[int], tags: list[str]) -> None:
        if note_ids:
            self.invoke("addTags", notes=note_ids, tags=" ".join(tags))

    def remove_tags(self, note_ids: list[int], tags: list[str]) -> None:
        if note_ids:
            self.invoke("removeTags", notes=note_ids, tags=" ".join(tags))

    def delete_notes(self, note_ids: list[int]) -> None:
        """DESTRUCTIVE — deletes notes AND their cards. Only for strict cases."""
        if note_ids:
            self.invoke("deleteNotes", notes=note_ids)

    # -- cards -------------------------------------------------------------
    def find_cards(self, query: str) -> list[int]:
        return self.invoke("findCards", query=query) or []

    def cards_info(self, card_ids: list[int]) -> list[dict]:
        if not card_ids:
            return []
        return self.invoke("cardsInfo", cards=card_ids) or []

    def are_due(self, card_ids: list[int]) -> list[bool]:
        if not card_ids:
            return []
        return self.invoke("areDue", cards=card_ids) or []

    def cards_of_note(self, note_id: int) -> list[int]:
        return self.find_cards(f"nid:{note_id}")

    def due_concepts(self, deck: str = DECK, limit: int | None = None) -> list[dict]:
        """Active, due notes in the deck, each annotated with its card ids.

        Returns note dicts with an extra "_card_ids" key. Excludes retired /
        merged notes via the Status field search.
        """
        card_ids = self.find_cards(f'deck:"{deck}" is:due')
        if not card_ids:
            return []
        infos = self.cards_info(card_ids)
        by_note: dict[int, list[int]] = {}
        for c in infos:
            by_note.setdefault(int(c["note"]), []).append(int(c["cardId"]))
        notes = self.notes_info(list(by_note.keys()))
        out = []
        for n in notes:
            status = (n.get("fields", {}).get("Status", {}).get("value", "") or "").strip()
            if status != "active":
                continue
            n["_card_ids"] = by_note.get(int(n["noteId"]), [])
            out.append(n)
        if limit is not None:
            out = out[:limit]
        return out

    def grade_card(self, card_id: int, ease: int) -> None:
        """Write an Again/Hard/Good/Easy answer back to Anki (1-4)."""
        if ease not in (1, 2, 3, 4):
            raise ValueError(f"ease must be 1-4, got {ease}")
        self.invoke("answerCards", answers=[{"cardId": int(card_id), "ease": int(ease)}])

    def suspend_cards(self, card_ids: list[int]) -> None:
        if card_ids:
            self.invoke("suspend", cards=card_ids)

    def unsuspend_cards(self, card_ids: list[int]) -> None:
        if card_ids:
            self.invoke("unsuspend", cards=card_ids)
