"""SQLite storage for raw documents and source run outcomes (schema in schema.sql)."""

import sqlite3
from datetime import date, datetime
from importlib import resources
from pathlib import Path

from observatoire.domain.models import RawDocument, SourceOutcome, TrustLevel

_SCHEMA = resources.files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")
_DOCUMENT_COLUMNS = (
    "content_hash, source_id, candidate_id, url, title, text, published_on, fetched_at, trust_level"
)
_RUN_COLUMNS = "run_id, source_id, started_at, duration_ms, status, fetched, new, duplicates, error"


class SqliteRepository:
    """DocumentRepository, CorpusReader, SourceRunLog and SourceRunHistory over one file.

    Each write commits on its own, so a crash partway through a long run keeps the
    work already done.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def exists(self, content_hash: str) -> bool:
        query = "SELECT 1 FROM documents WHERE content_hash = ?"
        return self._connection.execute(query, (content_hash,)).fetchone() is not None

    def save(self, document: RawDocument) -> None:
        values = (
            document.content_hash,
            document.source_id,
            document.candidate_id,
            document.url,
            document.title,
            document.text,
            document.published_on.isoformat() if document.published_on else None,
            document.fetched_at.isoformat(),
            int(document.trust_level),
        )
        with self._connection:
            self._connection.execute(
                f"INSERT OR IGNORE INTO documents ({_DOCUMENT_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)",
                values,
            )

    def list_documents(self) -> list[RawDocument]:
        rows = self._connection.execute(f"SELECT {_DOCUMENT_COLUMNS} FROM documents")
        return [_document(row) for row in rows]

    def record(self, outcome: SourceOutcome) -> None:
        values = (
            outcome.run_id,
            outcome.source_id,
            outcome.started_at.isoformat(),
            outcome.duration_ms,
            outcome.status,
            outcome.fetched,
            outcome.new,
            outcome.duplicates,
            outcome.error,
        )
        with self._connection:
            self._connection.execute(
                f"INSERT OR REPLACE INTO source_runs ({_RUN_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)",
                values,
            )

    def latest_by_source(self) -> dict[str, SourceOutcome]:
        rows = self._connection.execute(
            f"SELECT {_RUN_COLUMNS} FROM source_runs AS r WHERE started_at = "
            "(SELECT MAX(started_at) FROM source_runs WHERE source_id = r.source_id)"
        )
        return {row["source_id"]: _outcome(row) for row in rows}


def _document(row: sqlite3.Row) -> RawDocument:
    published_on = row["published_on"]
    return RawDocument(
        content_hash=row["content_hash"],
        source_id=row["source_id"],
        candidate_id=row["candidate_id"],
        url=row["url"],
        title=row["title"],
        text=row["text"],
        published_on=date.fromisoformat(published_on) if published_on else None,
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        trust_level=TrustLevel(row["trust_level"]),
    )


def _outcome(row: sqlite3.Row) -> SourceOutcome:
    return SourceOutcome(
        run_id=row["run_id"],
        source_id=row["source_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        duration_ms=row["duration_ms"],
        status=row["status"],
        fetched=row["fetched"],
        new=row["new"],
        duplicates=row["duplicates"],
        error=row["error"],
    )
