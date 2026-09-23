"""Source Library — the single source of truth for learning material.

Responsibilities (doc §6.1):
- store the original file or a stable reference,
- store parsed text with page/paragraph anchors and a SHA-256,
- support semantic lookup by source and concept-level追溯,
- produce traceable SourceRefs for Concepts.

It NEVER schedules reviews (doc §6.1). Ingest is limited to environment-clean,
deterministic adapters; heavy AI extraction lives in ingest.py + prompts.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config import INDEX_DIR, MANIFESTS_DIR, PARSED_DIR, SOURCES_DIR


class SourceError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


_MD_HEADING = re.compile(r"^#{1,6}\s+")
_PAGE_SPLIT = re.compile(r"\f")


def split_pages(text: str) -> list[dict]:
    """Split parsed text into pages, filtering blank pages."""
    pages = []
    for idx, raw in enumerate(_PAGE_SPLIT.split(text)):
        body = raw.strip()
        if body:
            pages.append({"page": idx + 1, "text": body})
    return pages


def extract_sections(text: str) -> list[dict]:
    """Very light structural chunking: markdown headings / numbered outline.

    This is NOT concept extraction — it only produces coarse, deterministic
    chunks referenced by page for later AI-driven concept extraction (doc §6.4).
    """
    lines = text.splitlines()
    sections, cur_title, cur_lines = [], None, []
    for ln in lines:
        clean = ln.strip()
        if _MD_HEADING.match(clean):
            if cur_lines or cur_title:
                sections.append({"title": cur_title, "text": "\n".join(cur_lines).strip()})
            cur_title = _MD_HEADING.sub("", clean)
            cur_lines = []
        elif re.match(r"^\d+[.、]\s*\S", clean) and len(clean) < 120:
            if cur_lines or cur_title:
                sections.append({"title": cur_title, "text": "\n".join(cur_lines).strip()})
            cur_title = clean
            cur_lines = []
        else:
            cur_lines.append(ln)
    if cur_lines or cur_title:
        sections.append({"title": cur_title, "text": "\n".join(cur_lines).strip()})
    return [s for s in sections if s.get("text") or s.get("title")]


class SourceLibrary:
    def __init__(self, root: Path):
        self.sources = Path(root) / "sources"
        self.parsed = Path(root) / "parsed"
        self.manifests = Path(root) / "manifests"
        self.index = Path(root) / "index"
        for d in (self.sources, self.parsed, self.manifests, self.index):
            d.mkdir(parents=True, exist_ok=True)

    # -- storage -----------------------------------------------------------
    def store_original(self, src_path: Path) -> str:
        """Copy the original file into the library, return its stored name."""
        if not src_path.exists():
            raise SourceError(f"source file not found: {src_path}")
        name = f"{uuid4().hex[:12]}-{src_path.name}"
        dest = self.sources / name
        shutil.copy2(str(src_path), str(dest))
        return name

    # -- manifests ---------------------------------------------------------
    def manifest_path(self, source_id: str) -> Path:
        return self.manifests / f"{source_id}.json"

    def save_manifest(self, source_id: str, data: dict) -> Path:
        data["source_id"] = source_id
        data["updated_at"] = _now_iso()
        path = self.manifest_path(source_id)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return path

    def load_manifest(self, source_id: str) -> dict | None:
        path = self.manifest_path(source_id)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def list_manifests(self) -> list[dict]:
        out = []
        for p in sorted(self.manifests.glob("*.json")):
            try:
                with p.open(encoding="utf-8") as fh:
                    out.append(json.load(fh))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    # -- parsed text -------------------------------------------------------
    def parsed_path(self, source_id: str) -> Path:
        return self.parsed / f"{source_id}.txt"

    def save_parsed(self, source_id: str, text: str, pages: list[dict]) -> None:
        self.parsed_path(source_id).write_text(text, encoding="utf-8")
        index_path = self.index / f"{source_id}.json"
        with index_path.open("w", encoding="utf-8") as fh:
            json.dump({"pages": pages, "source_id": source_id}, fh, ensure_ascii=False, indent=2)

    def load_parsed(self, source_id: str) -> str | None:
        path = self.parsed_path(source_id)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def load_pages(self, source_id: str) -> list[dict]:
        index_path = self.index / f"{source_id}.json"
        if not index_path.exists():
            return []
        with index_path.open(encoding="utf-8") as fh:
            return json.load(fh).get("pages", [])

    # -- semantic / by-source lookup --------------------------------------
    def find_by_concept(self, concept_id: str) -> list[dict]:
        """Sources (manifests) whose SourceRefs / parsed index mention a ConceptID."""
        matches = []
        needle = concept_id.lower()
        for m in self.list_manifests():
            refs = " ".join(m.get("source_refs", []))
            if needle in refs.lower() or needle in (m.get("title") or "").lower():
                matches.append(m)
        return matches

    def get_source_block(self, source_id: str, page: int, size: int = 1200) -> str:
        """Return a readable text window from a page, to show provenance (§15.1)."""
        for p in self.load_pages(source_id):
            if p["page"] == page:
                return p["text"][:size]
        return ""

    # -- dedupe by hash ----------------------------------------------------
    def find_by_hash(self, sha: str) -> list[dict]:
        return [m for m in self.list_manifests() if m.get("source_hash") == sha]


def reference_to_concept(source_id: str, title: str, page: int | None = None) -> str:
    """Format a SourceRef like 'title.pdf#page=12'. No page -> base ref."""
    base = f"{title}#page={page}" if page else title
    return base