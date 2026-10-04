"""SQLite storage for raw documents and source run outcomes (schema in schema.sql)."""

import json
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from importlib import resources
from pathlib import Path

from pydantic import TypeAdapter

from observatoire.domain.models import (
    CandidateMention,
    DocumentSegmentation,
    ExcludedPassage,
    ExclusionReason,
    RawDocument,
    Segment,
    SourceOutcome,
    TrustLevel,
)

_SCHEMA = resources.files(__package__).joinpath("schema.sql").read_text(encoding="utf-8")
_DOCUMENT_COLUMNS = (
    "content_hash, source_id, candidate_id, url, title, text, published_on, fetched_at, trust_level"
)
_RUN_COLUMNS = "run_id, source_id, started_at, duration_ms, status, fetched, new, duplicates, error"
_MENTIONS = TypeAdapter(tuple[CandidateMention, ...])


class SqliteRepository:
    """DocumentRepository, CorpusReader, SourceRunLog, SourceRunHistory, SegmentStore and
    SegmentReader over one file.

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

    def segmented_versions(self) -> dict[str, str]:
        rows = self._connection.execute(
            "SELECT document_hash, segmenter_version FROM segmentations"
        )
        return {row["document_hash"]: row["segmenter_version"] for row in rows}

    def replace(self, segmentations: Sequence[DocumentSegmentation]) -> None:
        """One transaction: a document's old segments never outlive its new ones."""
        hashes = [(s.document_hash,) for s in segmentations]
        with self._connection as connection:
            for table in ("segments", "excluded_passages", "segmentations"):
                connection.executemany(f"DELETE FROM {table} WHERE document_hash = ?", hashes)
            connection.executemany(
                "INSERT INTO segmentations (document_hash, segmenter_version) VALUES (?, ?)",
                [(s.document_hash, s.segmenter_version) for s in segmentations],
            )
            connection.executemany(
                "INSERT INTO segments (document_hash, idx, text, spans, mentions)"
                " VALUES (?,?,?,?,?)",
                [_segment_row(segment) for s in segmentations for segment in s.segments],
            )
            connection.executemany(
                "INSERT INTO excluded_passages (document_hash, start_char, end_char, reason)"
                " VALUES (?,?,?,?)",
                [
                    (s.document_hash, passage.span[0], passage.span[1], passage.reason.value)
                    for s in segmentations
                    for passage in s.excluded
                ],
            )

    def list_segmentations(self) -> list[DocumentSegmentation]:
        segments: dict[str, list[Segment]] = defaultdict(list)
        for row in self._connection.execute("SELECT * FROM segments ORDER BY document_hash, idx"):
            segments[row["document_hash"]].append(_segment(row))
        excluded: dict[str, list[ExcludedPassage]] = defaultdict(list)
        for row in self._connection.execute("SELECT * FROM excluded_passages ORDER BY start_char"):
            excluded[row["document_hash"]].append(
                ExcludedPassage(
                    span=(row["start_char"], row["end_char"]), reason=ExclusionReason(row["reason"])
                )
            )
        return [
            DocumentSegmentation(
                document_hash=document_hash,
                segmenter_version=version,
                segments=tuple(segments[document_hash]),
                excluded=tuple(excluded[document_hash]),
            )
            for document_hash, version in self.segmented_versions().items()
        ]


def _segment_row(segment: Segment) -> tuple[str, int, str, str, str]:
    return (
        segment.document_hash,
        segment.index,
        segment.text,
        json.dumps([list(span) for span in segment.spans]),
        _MENTIONS.dump_json(segment.mentions).decode(),
    )


def _segment(row: sqlite3.Row) -> Segment:
    return Segment(
        document_hash=row["document_hash"],
        index=row["idx"],
        text=row["text"],
        spans=tuple((start, end) for start, end in json.loads(row["spans"])),
        mentions=_MENTIONS.validate_json(row["mentions"]),
    )


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
