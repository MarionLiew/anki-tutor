"""ingest.py — parse files into Source Library manifest + parsed/index.

Pipeline (doc §6.3): hash file -> parse text/pages -> write manifest + parsed
+ index -> produce DETERMINISTIC *candidate* concepts (chapter/heading-level,
see §6.4: candidates only, never batch-card creation). Actual semantic concept
extraction & dedupe happens at teach-time via prompts/concept_extraction.md.

Adapters try the richest backend available and fall back gracefully. Parsing
must never fabricate content: on failure the manifest is saved as status=failed
and no concept is produced (doc §13/§16).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from config import LIBRARY_DIR
from source_library import (
    SourceLibrary,
    _MD_HEADING,
    sha256_file,
    split_pages,
)


class IngestError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_pdf(path: Path) -> tuple[str, list[dict]]:
    """PDF -> (text_with_page_breaks, pages). Tries pypdf then pymupdf."""
    for backend in ("pypdf", "pymupdf"):
        # Each attempt starts from empty buffers: a backend that fails mid-way
        # must not leave half its text behind for the next one to append to
        # (that would duplicate pages in the parsed index).
        text, pages = "", []
        try:
            if backend == "pypdf":
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                for i, page in enumerate(reader.pages):
                    t = page.extract_text() or ""
                    text += t + "\n\f\n"
                    if t.strip():
                        pages.append({"page": i + 1, "text": t.strip()})
            else:
                import fitz  # pymupdf
                doc = fitz.open(str(path))
                try:
                    for i in range(len(doc)):
                        t = doc[i].get_text()
                        text += t + "\n\f\n"
                        if t.strip():
                            pages.append({"page": i + 1, "text": t.strip()})
                finally:
                    doc.close()
        except Exception:
            continue  # fall through to the next backend
        if text.strip():
            return text, pages
    raise IngestError(f"could not extract text from PDF: {path}")


def _parse_docx(path: Path) -> tuple[str, list[dict]]:
    text = ""
    try:
        import docx
    except ImportError as e:
        raise IngestError(f"python-docx not available: {e}") from e
    d = docx.Document(str(path))
    parts = []
    for para in d.paragraphs:
        t = para.text.strip()
        if t:
            parts.append(t)
    # tables also carry content
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    joined = "\n".join(parts)
    # page simulation: DOCX has no reliable page breaks without rendering; a
    # single coarse chunk with explicit "(document)" page anchor is honest.
    return joined + "\n\f\n", [{"page": 1, "text": joined}]


def _parse_txt(path: Path) -> tuple[str, list[dict]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text, split_pages(text)


BACKENDS = {
    ".pdf": _parse_pdf,
    ".docx": _parse_docx,
    ".txt": _parse_txt,
    ".md": _parse_txt,
}


def _ref_key(section_title: str, page: int) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", (section_title or "").strip().lower()).strip("_")
    return f"p{page}" + (f":{slug}" if slug else "")


def chunk_candidates(text: str, pages: list[dict]) -> list[dict]:
    """Deterministic heading/section-seed candidates (NOT final concepts).

    Each candidate carries a stable ref key + page. The AI extraction prompt
    later turns these into real ConceptIDs and collapses duplicates.

    Page attribution comes from splitting on the form-feed page separator the
    parsers write. Do NOT count "\\f" while iterating str.splitlines(): it treats
    \\f as a line boundary itself, so no line ever contains one and every
    candidate would silently claim page 1 (Source Library states the origin of
    every concept, so a wrong page is a wrong citation).
    """
    sections = []

    def _flush(title, lines, page):
        # A section is only a candidate if it carries text: a bare heading or
        # the blank line that precedes one is not a concept seed.
        if any(line.strip() for line in lines):
            sections.append({"title": title, "text": "\n".join(lines), "page": page})

    cur_title, cur_lines, cur_page = None, [], 1
    for page_no, page_text in enumerate(text.split("\f"), start=1):
        if page_no > 1 and cur_lines:
            # Close the section that ran to the end of the previous page, then
            # keep the heading (its text continues, credited to the new page).
            _flush(cur_title, cur_lines, cur_page)
            cur_lines = []
        for ln in page_text.splitlines():
            clean = ln.strip()
            if _MD_HEADING.match(clean):
                _flush(cur_title, cur_lines, cur_page)
                cur_title, cur_lines, cur_page = _MD_HEADING.sub("", clean), [], page_no
                continue
            if not cur_lines:
                # First content line of this section decides its page, so a
                # heading-less section is not credited to page 1 by default.
                cur_page = page_no
            cur_lines.append(ln)
    _flush(cur_title, cur_lines, cur_page)

    out = []
    for i, s in enumerate(sections):
        title = s["title"]
        body = s["text"]
        # Filter junk: untitled and too short to be a concept seed
        if title is None and len(body.strip()) < 12:
            continue
        out.append({
            "candidate_id": f"cand_{i + 1}",
            "title": title or "untitled",
            "text": body[:600],
            "page": s["page"],
            "ref": _ref_key(title, s["page"]),
        })
    return out


class IngestService:
    def __init__(self, library: SourceLibrary):
        self.library = library

    def ingest(self, src_path: Path, title: str | None = None) -> dict:
        src_path = Path(src_path)
        if not src_path.exists():
            raise IngestError(f"file not found: {src_path}")
        ext = src_path.suffix.lower()
        if ext not in BACKENDS:
            raise IngestError(f"unsupported file type '{ext}', supported: {sorted(BACKENDS)}")

        file_hash = sha256_file(src_path)

        # Dedupe by content hash before storing anything.
        existing = self.library.find_by_hash(file_hash)
        if existing:
            return {"deduplicated": existing[0]}

        stored_name = self.library.store_original(src_path)
        title = title or src_path.stem

        manifest = {
            "source_id": None,  # filled below after we make the name
            "title": title,
            "filename": src_path.name,
            "stored_name": stored_name,
            "source_hash": file_hash,
            "size_bytes": src_path.stat().st_size,
            "format": ext.lstrip("."),
            "status": "parsing",
            "candidates": [],
            "source_refs": [],
        }

        try:
            text, pages = BACKENDS[ext](src_path)
        except IngestError as e:
            manifest["status"] = "failed"
            manifest["error"] = str(e)
            self.library.save_manifest(stored_name, manifest)
            return {"failed": str(e), "manifest": manifest}

        candidates = chunk_candidates(text, pages)
        manifest["status"] = "ok"
        manifest["candidates"] = candidates
        manifest["source_refs"] = [cd["ref"] for cd in candidates if cd.get("ref")]
        manifest["page_count"] = len(pages)

        self.library.save_manifest(stored_name, manifest)
        self.library.save_parsed(stored_name, text, pages)

        return {
            "source_id": stored_name,
            "title": title,
            "hash": file_hash,
            "pages": len(pages),
            "candidate_count": len(candidates),
            "candidates": candidates,
            "manifest": manifest,
        }


def quick_probe(path: Path) -> dict:
    """Return a cheap capability check for a file without full ingest."""
    ext = path.suffix.lower()
    return {
        "exists": path.exists(),
        "format": ext.lstrip("."),
        "supported": ext in BACKENDS,
        "size_bytes": path.stat().st_size if path.exists() else None,
    }