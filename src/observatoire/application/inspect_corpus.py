"""Use case: stored raw documents -> an overview a human can read before any analysis."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from observatoire.domain.models import (
    Candidate,
    CandidateCorpus,
    CorpusOverview,
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
    ) -> None:
        self._corpus = corpus
        self._history = history
        self._matcher = matcher
        self._clock = clock

    def build(self, candidates: Sequence[Candidate], sources: Sequence[Source]) -> CorpusOverview:
        by_source: dict[str, list[RawDocument]] = defaultdict(list)
        for document in self._corpus.list_documents():
            by_source[document.source_id].append(document)
        latest = self._history.latest_by_source()
        rows = tuple(
            self._candidate_corpus(candidate, sources, by_source, latest)
            for candidate in candidates
        )
        configured = {source.id for source in sources}
        unconfigured = sum(len(docs) for sid, docs in by_source.items() if sid not in configured)
        return CorpusOverview(
            generated_at=self._clock.now(), candidates=rows, unconfigured_documents=unconfigured
        )

    def _candidate_corpus(
        self,
        candidate: Candidate,
        sources: Sequence[Source],
        by_source: dict[str, list[RawDocument]],
        latest: dict[str, SourceOutcome],
    ) -> CandidateCorpus:
        own_sources = (s for s in sources if s.candidate_id == candidate.id)
        return CandidateCorpus(
            candidate=candidate,
            sources=tuple(
                SourceCorpus(
                    source=source,
                    documents=self._views(candidate, by_source.get(source.id, [])),
                    last_outcome=latest.get(source.id),
                )
                for source in own_sources
            ),
        )

    def _views(
        self, candidate: Candidate, documents: list[RawDocument]
    ) -> tuple[DocumentView, ...]:
        return tuple(
            DocumentView(document=d, mentions_of_candidate=self._mentions(candidate, d.text))
            for d in _newest_first(documents)
        )

    def _mentions(self, candidate: Candidate, text: str) -> int:
        found = (m.count for m in self._matcher.match(text) if m.candidate_id == candidate.id)
        return next(found, 0)


def _newest_first(documents: list[RawDocument]) -> list[RawDocument]:
    """Dated documents newest first, then undated ones; ties by most recent fetch."""
    by_fetch = sorted(documents, key=lambda d: d.fetched_at, reverse=True)
    dated = sorted((d for d in by_fetch if d.published_on), key=_published_on, reverse=True)
    return [*dated, *(d for d in by_fetch if d.published_on is None)]


def _published_on(document: RawDocument) -> date:
    return document.published_on or date.min
