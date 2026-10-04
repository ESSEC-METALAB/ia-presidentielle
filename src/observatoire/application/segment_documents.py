"""Use case: stored raw documents -> segments, with every excluded passage accounted for."""

from collections import Counter, defaultdict
from collections.abc import Sequence

import structlog

from observatoire.domain.models import (
    DocumentSegmentation,
    ExclusionReason,
    RawDocument,
    SegmentationReport,
    Source,
    SourceSegmentation,
)
from observatoire.domain.ports import CandidateMatcher, CorpusReader, Segmenter, SegmentStore

_log = structlog.get_logger(__name__)


class SegmentDocuments:
    """Segments each configured source's documents together, then records who they name.

    A source is segmented again as a whole when any of its documents is new or was
    segmented by an older version: what counts as boilerplate depends on all of them.
    """

    def __init__(
        self,
        corpus: CorpusReader,
        store: SegmentStore,
        segmenter: Segmenter,
        matcher: CandidateMatcher,
    ) -> None:
        self._corpus = corpus
        self._store = store
        self._segmenter = segmenter
        self._matcher = matcher

    def run(self, sources: Sequence[Source], *, rebuild: bool = False) -> SegmentationReport:
        by_source: dict[str, list[RawDocument]] = defaultdict(list)
        for document in self._corpus.list_documents():
            by_source[document.source_id].append(document)
        done = {} if rebuild else self._store.segmented_versions()
        outcomes = tuple(
            self._segment_source(source, by_source[source.id], done)
            for source in sources
            if by_source.get(source.id)
        )
        configured = {source.id for source in sources}
        unconfigured = sum(len(d) for sid, d in by_source.items() if sid not in configured)
        return SegmentationReport(
            segmenter_version=self._segmenter.version,
            outcomes=outcomes,
            unconfigured_documents=unconfigured,
        )

    def _segment_source(
        self, source: Source, documents: list[RawDocument], done: dict[str, str]
    ) -> SourceSegmentation:
        version = self._segmenter.version
        if all(done.get(d.content_hash) == version for d in documents):
            return SourceSegmentation(
                source_id=source.id, resegmented=False, documents=len(documents),
                empty_documents=0, segments=0, excluded={},
            )  # fmt: skip
        results = [self._with_mentions(r) for r in self._segmenter.segment(source, documents)]
        self._store.replace(results)
        outcome = _summary(source, results)
        _log.info("source_segmented", **outcome.model_dump(mode="json"))
        return outcome

    def _with_mentions(self, segmentation: DocumentSegmentation) -> DocumentSegmentation:
        segments = tuple(
            segment.model_copy(update={"mentions": tuple(self._matcher.match(segment.text))})
            for segment in segmentation.segments
        )
        return segmentation.model_copy(update={"segments": segments})


def _summary(source: Source, results: list[DocumentSegmentation]) -> SourceSegmentation:
    excluded: Counter[ExclusionReason] = Counter(
        passage.reason for result in results for passage in result.excluded
    )
    return SourceSegmentation(
        source_id=source.id,
        resegmented=True,
        documents=len(results),
        empty_documents=sum(1 for result in results if result.is_empty),
        segments=sum(len(result.segments) for result in results),
        excluded=dict(excluded),
    )
