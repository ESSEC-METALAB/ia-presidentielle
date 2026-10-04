"""Use case: sources -> deduplicated raw documents, stored with provenance."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime

import structlog

from observatoire.domain.models import CollectionReport, RawDocument, Source, SourceOutcome
from observatoire.domain.ports import Clock, DocumentRepository, SourceReader, SourceRunLog

_log = structlog.get_logger(__name__)
_MAX_ERROR_CHARS = 300


class CollectDaily:
    """Reads each source, keeps what is new, records how every source behaved.

    A failing source never stops the run (CLAUDE.md §4): it is logged, recorded as
    failed, and the next source is read.
    """

    def __init__(
        self,
        readers: Mapping[str, SourceReader],
        repository: DocumentRepository,
        run_log: SourceRunLog,
        clock: Clock,
    ) -> None:
        self._readers = readers
        self._repository = repository
        self._run_log = run_log
        self._clock = clock

    def run(
        self, sources: Sequence[Source], *, run_id: str, since: date | None = None
    ) -> CollectionReport:
        outcomes = tuple(self._collect(source, run_id, since) for source in sources)
        return CollectionReport(run_id=run_id, outcomes=outcomes)

    def _collect(self, source: Source, run_id: str, since: date | None) -> SourceOutcome:
        started_at = self._clock.now()
        reader = self._readers.get(source.kind)
        if reader is None:
            error = f"no reader registered for kind '{source.kind}'"
            return self._finish(source, run_id, started_at, error=error)
        try:
            documents = list(reader.fetch(source, since))
        except Exception as failure:  # one failing source never stops the run
            error = f"{type(failure).__name__}: {failure}"[:_MAX_ERROR_CHARS]
            return self._finish(source, run_id, started_at, error=error)
        new, duplicates = self._store(documents)
        counts = {"fetched": len(documents), "new": new, "duplicates": duplicates}
        return self._finish(source, run_id, started_at, counts=counts)

    def _store(self, documents: list[RawDocument]) -> tuple[int, int]:
        new = 0
        for document in documents:
            if self._repository.exists(document.content_hash):
                continue
            self._repository.save(document)
            new += 1
        return new, len(documents) - new

    def _finish(
        self,
        source: Source,
        run_id: str,
        started_at: datetime,
        *,
        counts: Mapping[str, int] | None = None,
        error: str | None = None,
    ) -> SourceOutcome:
        elapsed = self._clock.now() - started_at
        outcome = SourceOutcome(
            run_id=run_id,
            source_id=source.id,
            started_at=started_at,
            duration_ms=max(0, round(elapsed.total_seconds() * 1000)),
            status="failed" if error else "ok",
            fetched=(counts or {}).get("fetched", 0),
            new=(counts or {}).get("new", 0),
            duplicates=(counts or {}).get("duplicates", 0),
            error=error,
        )
        self._run_log.record(outcome)
        _log.info("source_collected", **outcome.model_dump(mode="json", exclude={"started_at"}))
        return outcome
