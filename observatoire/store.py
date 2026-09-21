"""SQLite store — the working cache, not the published record.

Holds three things: what we have already seen (dedup), what we fetched
(documents and leads), and how many items each source returned on each run
(liveness). The last one exists because ``nosdeputes.fr`` returned HTTP 200
with an empty array indefinitely, and a source that silently dies is
indistinguishable from a quiet week unless you count.

Claims live here while the pipeline works on them, but what gets *published*
is ``data/claims.json`` — see :func:`export_claims`. The editorial gate is a
pull-request diff and a reviewer cannot read a binary SQLite file in one.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
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
    return datetime.now(UTC).isoformat(timespec="microseconds")


# --- the published record -------------------------------------------------
#
# Claims are reviewed as a pull-request diff, so the file has to read like
# prose to a human editor, not like a database export.


def _review_order(claim) -> tuple[str, str, str]:
    """Group a person's claims together, oldest first.

    Sorting on ``id`` alone would be stable but scatters one candidate's
    claims through the file at random, and a new claim would land at a random
    line. ``date`` is nullable on purpose — a source that carries no date gets
    none — so it sorts first rather than being invented.
    """
    return (claim.person, claim.date.isoformat() if claim.date else "", claim.id)


def export_claims(path: str | Path, claims: list) -> None:
    """Write the claims a reviewer will read.

    ``ensure_ascii=False`` is not cosmetic: the quotes are French, and
    ``\\u00e9`` in a diff is not something an editor can check a quote against.
    """
    payload = [c.model_dump(mode="json") for c in sorted(claims, key=_review_order)]
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_claims(path: str | Path) -> list:
    from .schema import Claim

    return [Claim.model_validate(c) for c in json.loads(Path(path).read_text(encoding="utf-8"))]


def merge_claims(path: str | Path, new: list) -> int:
    """Add claims the file does not already carry. Returns how many.

    The file wins on every id it already has, because by then a human has
    been through it — corrected a ``contexte``, confirmed a ``tier``, moved a
    status off ``pending``. Re-exporting the pipeline's own copy over the top
    would silently undo that editing, and the SQLite cache it came from is not
    even in the repository. Merging also keeps the morning's diff to the
    claims that are genuinely new, which is the diff the editor agreed to read.
    """
    path = Path(path)
    existing = load_claims(path) if path.exists() else []
    known = {c.id for c in existing}
    added = [c for c in new if c.id not in known]
    export_claims(path, existing + added)
    return len(added)


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
