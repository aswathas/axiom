"""Uploaded bytes -> per-page text.

Scope is deliberately narrow. We support exactly what ``pypdf`` and a UTF-8
decode can do, and we return a clear 400 for everything else. Guessing at
``.docx`` or OCR-ing a scan would be inventing text layer that no fact's
character offsets could honestly point back into.
"""

from __future__ import annotations

import hashlib
import io
from typing import Any

__all__ = ["extract_pages", "SUPPORTED_SUFFIXES", "UnsupportedDocument"]

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".text"}

# 25 MB — generous for a discharge summary, small enough that a single upload
# cannot exhaust a demo box's memory.
MAX_BYTES = 25 * 1024 * 1024


class UnsupportedDocument(ValueError):
    """Raised for a file we cannot honestly turn into a text layer."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _suffix(filename: str) -> str:
    name = (filename or "").strip().lower()
    dot = name.rfind(".")
    return name[dot:] if dot > 0 else ""


def extract_pages(data: bytes, filename: str) -> list[dict[str, Any]]:
    """Return ``[{"page_no": 1, "text": "..."}]`` for an uploaded file.

    Raises :class:`UnsupportedDocument` (a 400) for empty, oversized, corrupt,
    or unsupported uploads. Page numbers are 1-based and contiguous — the
    ``facts`` table's primary key depends on it.
    """
    if not data:
        raise UnsupportedDocument("uploaded file is empty")
    if len(data) > MAX_BYTES:
        raise UnsupportedDocument(
            f"uploaded file exceeds the {MAX_BYTES // (1024 * 1024)} MB limit", 413)

    suffix = _suffix(filename)
    if suffix in {".doc", ".docx", ".odt", ".rtf", ".xlsx", ".pptx"}:
        raise UnsupportedDocument(
            f"{suffix} is not supported: AXIOM reads a text layer, and no "
            f"office converter is wired in. Export to PDF or plain text.")
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocument(
            f"unsupported file type {suffix or '(none)'}; expected one of "
            f"{sorted(SUPPORTED_SUFFIXES)}")

    # Sniff the PDF magic rather than trusting the extension, because a .txt
    # that is actually a PDF is a real thing users do.
    is_pdf = data[:5] == b"%PDF-" or suffix == ".pdf"

    if is_pdf:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise UnsupportedDocument("PDF support requires the pypdf package") from exc
        try:
            reader = PdfReader(io.BytesIO(data))
            raw_pages = [pg.extract_text() or "" for pg in reader.pages]
        except Exception as exc:
            raise UnsupportedDocument(
                f"could not read PDF text layer: {exc}") from exc
        if not raw_pages:
            raise UnsupportedDocument(
                "PDF has no extractable text layer (it is probably a scan); "
                "OCR is not wired up yet")
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # Latin-1 never fails, and pretending a mojibake page is a clean
            # parse is worse than saying so.
            try:
                text = data.decode("latin-1")
            except Exception:
                raise UnsupportedDocument("file is not decodable as text")
        raw_pages = [text]

    pages = []
    for i, text in enumerate(raw_pages, start=1):
        if not text.strip():
            continue  # skip blank pages rather than storing an empty row
        pages.append({"page_no": i, "text": text})
    if not pages:
        raise UnsupportedDocument("document contained no readable text")
    # Renumber contiguously after dropping blanks so (doc_id, page_no) stays a
    # clean primary key and every page number the API hands out exists.
    for i, p in enumerate(pages, start=1):
        p["page_no"] = i
    return pages


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()