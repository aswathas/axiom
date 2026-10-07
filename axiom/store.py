"""SQLite persistence for AXIOM — patients, documents, pages, facts, audit.

Design constraints that shaped this file
---------------------------------------
* **Thread safety is not optional.** FastAPI executes sync route handlers in an
  ``anyio`` worker threadpool, so the same :class:`Store` instance is touched
  concurrently by up to ``40`` threads. We keep ONE connection opened with
  ``check_same_thread=False`` and guard every statement with an ``RLock``.
  Opening a connection per call would be simpler but leaks handles under load
  and makes the tmp_path tests slow.
* **Provenance survives the round trip.** A fact stored without its document id
  and character offsets is a fact the system is not willing to publish, so the
  ``facts`` table stores the offsets as first-class INTEGER columns, not buried
  in the JSON blob. The blob is the convenience copy; the columns are the
  contract.
* **Audit is append-only.** We never update or delete an ``audit`` row. A record
  of what the system declined to answer is the artifact that distinguishes a
  careful system from a merely quiet one.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

__all__ = ["Store", "utcnow_iso"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    dob         TEXT NOT NULL DEFAULT '',
    mrn         TEXT NOT NULL DEFAULT '',
    patient_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id     TEXT PRIMARY KEY,
    patient_id TEXT,
    filename   TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT 'unknown',
    sha256     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (patient_id) REFERENCES patients (id)
);

CREATE TABLE IF NOT EXISTS pages (
    doc_id   TEXT NOT NULL,
    page_no  INTEGER NOT NULL,
    text     TEXT NOT NULL,
    kind     TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY (doc_id, page_no),
    FOREIGN KEY (doc_id) REFERENCES documents (doc_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS facts (
    doc_id     TEXT NOT NULL,
    patient_id TEXT,
    page_no    INTEGER NOT NULL DEFAULT 1,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end   INTEGER NOT NULL DEFAULT 0,
    extractor  TEXT NOT NULL DEFAULT 'regex',
    fact_json  TEXT NOT NULL,
    PRIMARY KEY (doc_id, page_no, char_start, char_end, fact_json),
    FOREIGN KEY (doc_id) REFERENCES documents (doc_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    TEXT,
    query         TEXT NOT NULL DEFAULT '',
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_patient ON facts (patient_id);
CREATE INDEX IF NOT EXISTS idx_facts_doc     ON facts (doc_id);
CREATE INDEX IF NOT EXISTS idx_docs_patient  ON documents (patient_id);
CREATE INDEX IF NOT EXISTS idx_audit_patient ON audit (patient_id);
"""


def utcnow_iso() -> str:
    """Timezone-aware UTC timestamp. Naive local times are a bug in an audit log."""
    return datetime.now(timezone.utc).isoformat()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _loads(raw: str) -> Any:
    return json.loads(raw)


class Store:
    """Repository over a single SQLite file.

    ``path`` may be ``":memory:"`` for tests that want a truly ephemeral DB.
    """

    def __init__(self, path: str = "axiom.db") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            # WAL keeps a reader from blocking the writer; it is a no-op for
            # :memory: and simply left alone there.
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # -- lifecycle ------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- patients -------------------------------------------------------
    def create_patient(self, patient: dict[str, Any]) -> dict[str, Any]:
        """Insert a Contract 2 patient dict. Returns the stored record.

        The dict is stored verbatim as ``patient_json``; ``id``/``name``/``dob``/
        ``mrn`` are additionally lifted into columns so the list endpoint can
        answer without deserialising every row.
        """
        pid = str(patient.get("id") or patient.get("patient_id") or f"pat_{uuid.uuid4().hex[:8]}")
        record = dict(patient)
        record["id"] = pid
        record.setdefault("name", "")
        record.setdefault("dob", "")
        record.setdefault("mrn", "")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO patients (id, name, dob, mrn, patient_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (pid, record["name"], record["dob"], record["mrn"],
                 _dumps(record), utcnow_iso()),
            )
            self._conn.commit()
        return record

    def get_patient(self, patient_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT patient_json FROM patients WHERE id = ?", (str(patient_id),)
            ).fetchone()
        if row is None:
            return None
        try:
            return _loads(row["patient_json"])
        except json.JSONDecodeError:
            # A corrupt blob is a data-integrity problem, not a server error.
            return None

    def list_patients(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, dob, mrn FROM patients ORDER BY id"
            ).fetchall()
            counts = {
                r["patient_id"]: r["n"]
                for r in self._conn.execute(
                    "SELECT patient_id, COUNT(*) AS n FROM documents GROUP BY patient_id"
                ).fetchall()
            }
        return [{"id": r["id"], "name": r["name"], "dob": r["dob"], "mrn": r["mrn"],
                 "doc_count": counts.get(r["id"], 0)} for r in rows]

    def update_patient(self, patient: dict[str, Any]) -> dict[str, Any]:
        return self.create_patient(patient)

    # -- documents ------------------------------------------------------
    def save_document(self, doc_id: str, patient_id: Optional[str], filename: str,
                      kind: str, sha256: str, pages: Iterable[dict[str, Any]],
                      created_at: Optional[str] = None) -> str:
        """Persist a document and its pages in one transaction."""
        pages = list(pages)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO documents"
                " (doc_id, patient_id, filename, kind, sha256, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (str(doc_id), patient_id, filename, kind, sha256,
                 created_at or utcnow_iso()),
            )
            self._conn.executemany(
                "INSERT OR REPLACE INTO pages (doc_id, page_no, text, kind)"
                " VALUES (?, ?, ?, ?)",
                [(str(doc_id), int(p.get("page_no", i + 1)), p.get("text", ""),
                  p.get("kind", kind)) for i, p in enumerate(pages)],
            )
            self._conn.commit()
        return str(doc_id)

    def get_document(self, doc_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc_id, patient_id, filename, kind, sha256, created_at"
                " FROM documents WHERE doc_id = ?", (str(doc_id),)
            ).fetchone()
        return dict(row) if row else None

    def list_documents(self, patient_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            if patient_id is None:
                rows = self._conn.execute(
                    "SELECT doc_id, patient_id, filename, kind, sha256, created_at"
                    " FROM documents ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT doc_id, patient_id, filename, kind, sha256, created_at"
                    " FROM documents WHERE patient_id = ? ORDER BY created_at DESC",
                    (str(patient_id),),
                ).fetchall()
        return [dict(r) for r in rows]

    # -- pages ----------------------------------------------------------
    def get_page(self, doc_id: str, page_no: int) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc_id, page_no, text, kind FROM pages"
                " WHERE doc_id = ? AND page_no = ?", (str(doc_id), int(page_no))
            ).fetchone()
        return dict(row) if row else None

    def get_pages(self, doc_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc_id, page_no, text, kind FROM pages"
                " WHERE doc_id = ? ORDER BY page_no", (str(doc_id),)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- facts ----------------------------------------------------------
    def save_facts(self, patient_id: Optional[str], doc_id: str,
                   facts: Iterable[Any]) -> int:
        """Persist facts. Accepts ``Fact`` dataclasses or plain Contract 1 dicts.

        Provenance columns are read off the fact itself; a fact with an empty
        ``source_doc_id`` is stamped with ``doc_id`` so the audit trail can
        always resolve back to a document.
        """
        rows = []
        for f in facts:
            d = f.to_dict() if hasattr(f, "to_dict") else dict(f)
            did = d.get("source_doc_id") or str(doc_id)
            d["source_doc_id"] = did
            rows.append((
                did, patient_id,
                int(d.get("source_page", 1) or 1),
                int(d.get("source_char_start", 0) or 0),
                int(d.get("source_char_end", 0) or 0),
                d.get("extractor", "regex"),
                _dumps(d),
            ))
        if not rows:
            return 0
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO facts"
                " (doc_id, patient_id, page_no, char_start, char_end, extractor, fact_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            self._conn.commit()
        return len(rows)

    def get_facts_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT fact_json FROM facts WHERE patient_id = ?"
                " ORDER BY doc_id, page_no, char_start", (str(patient_id),)
            ).fetchall()
        return [_loads(r["fact_json"]) for r in rows]

    def get_facts_for_document(self, doc_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT fact_json FROM facts WHERE doc_id = ?"
                " ORDER BY page_no, char_start", (str(doc_id),)
            ).fetchall()
        return [_loads(r["fact_json"]) for r in rows]

    # -- audit ----------------------------------------------------------
    def record_audit(self, patient_id: Optional[str], query: str,
                     response: dict[str, Any]) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO audit (patient_id, query, response_json, created_at)"
                " VALUES (?, ?, ?, ?)",
                (patient_id, query, _dumps(response), utcnow_iso()),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def get_audit(self, patient_id: Optional[str] = None,
                  limit: int = 100) -> list[dict[str, Any]]:
        sql = ("SELECT id, patient_id, query, response_json, created_at FROM audit")
        args: tuple = ()
        if patient_id is not None:
            sql += " WHERE patient_id = ?"
            args = (str(patient_id),)
        sql += " ORDER BY id DESC LIMIT ?"
        args += (int(limit),)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["response"] = _loads(d.pop("response_json"))
            except json.JSONDecodeError:
                d["response"] = None
            out.append(d)
        return out