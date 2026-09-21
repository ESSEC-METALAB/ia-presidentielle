"""SQLite store. Committed to the repo — git is the audit trail.

Holds three things: what we have already seen (dedup), what we fetched
(documents and leads), and how many items each source returned on each run
(liveness). The last one exists because ``nosdeputes.fr`` returned HTTP 200
with an empty array indefinitely, and a source that silently dies is
indistinguishable from a quiet week unless you count.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .schema import Document, Lead

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    url_hash TEXT PRIMARY KEY,
    url      TEXT NOT NULL,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    url_hash TEXT PRIMARY KEY,
    person   TEXT NOT NULL,
    source_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    url_hash TEXT PRIMARY KEY,
    person   TEXT NOT NULL,
    source_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    id       TEXT PRIMARY KEY,
    person   TEXT NOT NULL,
    axis     TEXT NOT NULL,
    status   TEXT NOT NULL,
    payload  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_runs (
    source_id TEXT NOT NULL,
    run_at    TEXT NOT NULL,
    fetched   INTEGER NOT NULL,  -- items the source returned: the liveness signal
    kept      INTEGER NOT NULL   -- items retained after matching and dedup
);
CREATE INDEX IF NOT EXISTS idx_runs ON source_runs(source_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, path: str | Path = "data/observatoire.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # --- dedup -----------------------------------------------------------

    def is_new(self, url_hash: str) -> bool:
        cur = self.db.execute("SELECT 1 FROM seen WHERE url_hash = ?", (url_hash,))
        return cur.fetchone() is None

    def mark_seen(self, url_hash: str, url: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO seen (url_hash, url, first_seen) VALUES (?,?,?)",
            (url_hash, url, _now()),
        )

    # --- writes ----------------------------------------------------------

    def add_document(self, doc: Document) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
            (doc.url_hash, doc.person, doc.source_id, _now(), doc.model_dump_json()),
        )
        self.mark_seen(doc.url_hash, doc.url)

    def add_lead(self, lead: Lead) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO leads VALUES (?,?,?,?,?)",
            (lead.url_hash, lead.person, lead.source_id, _now(), lead.model_dump_json()),
        )
        self.mark_seen(lead.url_hash, lead.url)

    def add_claim(self, claim) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?)",
            (claim.id, claim.person, str(claim.axis), str(claim.status),
             claim.model_dump_json()),
        )

    def claims(self) -> list:
        from .schema import Claim
        rows = self.db.execute("SELECT payload FROM claims").fetchall()
        return [Claim.model_validate(json.loads(r[0])) for r in rows]

    def record_run(self, source_id: str, fetched: int, kept: int) -> None:
        self.db.execute(
            "INSERT INTO source_runs (source_id, run_at, fetched, kept) VALUES (?,?,?,?)",
            (source_id, _now(), fetched, kept),
        )

    def commit(self) -> None:
        self.db.commit()

    # --- reads -----------------------------------------------------------

    def documents(self) -> list[Document]:
        rows = self.db.execute("SELECT payload FROM documents ORDER BY fetched_at").fetchall()
        return [Document.model_validate(json.loads(r[0])) for r in rows]

    def leads(self) -> list[Lead]:
        rows = self.db.execute("SELECT payload FROM leads ORDER BY fetched_at").fetchall()
        return [Lead.model_validate(json.loads(r[0])) for r in rows]

    def dead_sources(self, consecutive: int = 3) -> list[str]:
        """Sources that returned **no items at all** on their last
        ``consecutive`` runs.

        Deliberately measured on ``fetched``, not ``kept``: a healthy tech feed
        that simply has not mentioned a candidate this week is not dead, and
        alerting on it would train people to ignore the alert. ``nosdeputes.fr``
        served HTTP 200 with an empty array indefinitely — that is what this
        catches.

        A source needs at least ``consecutive`` runs before it can be called
        dead, so a newly added source is never reported on its first morning.
        """
        ids = [r[0] for r in self.db.execute("SELECT DISTINCT source_id FROM source_runs")]
        dead = []
        for sid in ids:
            counts = [
                r[0]
                for r in self.db.execute(
                    "SELECT fetched FROM source_runs WHERE source_id = ? "
                    "ORDER BY rowid DESC LIMIT ?",
                    (sid, consecutive),
                )
            ]
            if len(counts) >= consecutive and not any(counts):
                dead.append(sid)
        return sorted(dead)
