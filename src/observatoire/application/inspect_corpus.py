"""Use case: stored raw documents -> an overview a human can read before any analysis."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from observatoire.domain.models import (
    Candidate,
    CandidateCorpus,
    CorpusOverview,
    DocumentSegmentation,
    DocumentView,
    RawDocument,
    Source,
    SourceCorpus,
    SourceOutcome,
)
from observatoire.domain.ports import (
    CandidateMatcher,
    Clock,
    CorpusReader,
    SegmentReader,
    SourceRunHistory,
)


class InspectCorpus:
    """Groups the corpus by candidate and source, every configured person included.

    A person with no configured source still gets a row: *non suivi* is shown, not
    hidden, so coverage gaps are visible rather than read as silence.
    """

    def __init__(
        self,
        corpus: CorpusReader,
        history: SourceRunHistory,
        matcher: CandidateMatcher,
        clock: Clock,
        *,
        segments: SegmentReader | None = None,
    ) -> None:
        self._corpus = corpus
        self._history = history
        self._matcher = matcher
        self._clock = clock
        self._segments = segments

    def build(self, candidates: Sequence[Candidate], sources: Sequence[Source]) -> CorpusOverview:
        snapshot = self._snapshot()
        rows = tuple(self._candidate_corpus(c, sources, snapshot) for c in candidates)
        configured = {source.id for source in sources}
        unconfigured = sum(
            len(docs) for sid, docs in snapshot.by_source.items() if sid not in configured
        )
        return CorpusOverview(
            generated_at=self._clock.now(), candidates=rows, unconfigured_documents=unconfigured
        )

    def _snapshot(self) -> "_Snapshot":
        by_source: dict[str, list[RawDocument]] = defaultdict(list)
        for document in self._corpus.list_documents():
            by_source[document.source_id].append(document)
        listed = self._segments.list_segmentations() if self._segments else []
        return _Snapshot(
            by_source=by_source,
            latest=self._history.latest_by_source(),
            segmentations={s.document_hash: s for s in listed},
        )

    def _candidate_corpus(
        self, candidate: Candidate, sources: Sequence[Source], snapshot: "_Snapshot"
    ) -> CandidateCorpus:
        own_sources = (s for s in sources if s.candidate_id == candidate.id)
        return CandidateCorpus(
            candidate=candidate,
            sources=tuple(
                SourceCorpus(
                    source=source,
                    documents=self._views(candidate, source, snapshot),
                    last_outcome=snapshot.latest.get(source.id),
                )
                for source in own_sources
            ),
        )

    def _views(
        self, candidate: Candidate, source: Source, snapshot: "_Snapshot"
    ) -> tuple[DocumentView, ...]:
        return tuple(
            DocumentView(
                document=d,
                mentions_of_candidate=self._mentions(candidate, d.text),
                segmentation=snapshot.segmentations.get(d.content_hash),
            )
            for d in _newest_first(snapshot.by_source.get(source.id, []))
        )

    def _mentions(self, candidate: Candidate, text: str) -> int:
        found = (m.count for m in self._matcher.match(text) if m.candidate_id == candidate.id)
        return next(found, 0)


@dataclass(frozen=True)
class _Snapshot:
    """What the store holds at the time of one build."""

    by_source: dict[str, list[RawDocument]]
    latest: dict[str, SourceOutcome]
    segmentations: dict[str, DocumentSegmentation]


def _newest_first(documents: list[RawDocument]) -> list[RawDocument]:
    """Dated documents newest first, then undated ones; ties by most recent fetch."""
    by_fetch = sorted(documents, key=lambda d: d.fetched_at, reverse=True)
    dated = sorted((d for d in by_fetch if d.published_on), key=_published_on, reverse=True)
    return [*dated, *(d for d in by_fetch if d.published_on is None)]


def _published_on(document: RawDocument) -> date:
    return document.published_on or date.min
