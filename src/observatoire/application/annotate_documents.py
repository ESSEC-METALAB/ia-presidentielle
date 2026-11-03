"""Use case: segments -> dimension annotations, each one quoting its passage exactly.

Most passages carry no AI-policy statement, and an empty answer is the correct one: it is
stored like any other, so the passage is not sent again. Nothing here retries or coaxes
an annotator that found nothing.
"""

from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date

import structlog

from observatoire.domain.annotation import (
    AnnotationContext,
    AnnotationReport,
    RejectionReason,
    SegmentAnnotation,
)
from observatoire.domain.errors import AnnotationUnavailableError, MalformedAnnotationError
from observatoire.domain.models import Candidate, RawDocument, Segment, Source, in_window
from observatoire.domain.ports import (
    AnnotationStore,
    Annotator,
    Clock,
    CorpusReader,
    DraftReviewer,
    RelevanceFilter,
    SegmentReader,
)
from observatoire.services.dedup import content_hash

_log = structlog.get_logger(__name__)


@dataclass
class _Tally:
    segments_read: int = 0
    not_relevant: int = 0
    already_annotated: int = 0
    annotated: int = 0
    empty: int = 0
    pending: int = 0
    failed: int = 0
    statements: int = 0
    rejected: Counter[RejectionReason] = field(default_factory=Counter)


@dataclass(frozen=True)
class _Passage:
    segment: Segment
    document: RawDocument
    context: AnnotationContext


class AnnotateDocuments:
    def __init__(
        self,
        *,
        corpus: CorpusReader,
        segments: SegmentReader,
        store: AnnotationStore,
        annotator: Annotator,
        relevance: RelevanceFilter,
        reviewer: DraftReviewer,
        clock: Clock,
    ) -> None:
        self._corpus = corpus
        self._segments = segments
        self._store = store
        self._annotator = annotator
        self._relevance = relevance
        self._reviewer = reviewer
        self._clock = clock

    def run(
        self,
        candidates: Sequence[Candidate],
        sources: Sequence[Source],
        *,
        since: date | None = None,
        limit: int | None = None,
        rebuild: bool = False,
    ) -> AnnotationReport:
        """Annotates at most `limit` passages; the rest stay pending for the next run.

        `rebuild` annotates again what this annotator already did, so that changed gates
        or prefilter apply to it too.
        """
        version = self._annotator.version
        done = {} if rebuild else self._store.annotated_segments(version)
        tally = _Tally()
        for passage in self._passages(candidates, sources, since):
            tally.segments_read += 1
            segment = passage.segment
            if not self._relevance.is_relevant(segment.text):
                tally.not_relevant += 1
            elif done.get(segment.id) == content_hash(segment.text):
                tally.already_annotated += 1
            elif limit is not None and tally.annotated + tally.failed >= limit:
                tally.pending += 1
            else:
                self._annotate(passage, tally)
        return AnnotationReport(
            annotator_version=version,
            segments_read=tally.segments_read,
            not_relevant=tally.not_relevant,
            already_annotated=tally.already_annotated,
            annotated=tally.annotated,
            empty=tally.empty,
            pending=tally.pending,
            failed=tally.failed,
            statements=tally.statements,
            rejected=dict(tally.rejected),
        )

    def _passages(
        self, candidates: Sequence[Candidate], sources: Sequence[Source], since: date | None
    ) -> Iterator[_Passage]:
        """Segments of configured sources' in-window documents, in a stable order."""
        people = {candidate.id: candidate for candidate in candidates}
        by_id = {source.id: source for source in sources}
        documents = {
            d.content_hash: d
            for d in self._corpus.list_documents()
            if d.source_id in by_id and in_window(d.published_on, since)
        }
        segmentations = sorted(self._segments.list_segmentations(), key=lambda s: s.document_hash)
        for segmentation in segmentations:
            document = documents.get(segmentation.document_hash)
            if document is None:
                continue
            context = _context(people[document.candidate_id], by_id[document.source_id], document)
            for segment in segmentation.segments:
                yield _Passage(segment, document, context)

    def _annotate(self, passage: _Passage, tally: _Tally) -> None:
        segment = passage.segment
        try:
            drafts = self._annotator.annotate(segment, passage.context)
        except (AnnotationUnavailableError, MalformedAnnotationError) as error:
            tally.failed += 1
            _log.warning("annotation_failed", segment_id=segment.id, error=str(error))
            return
        accepted, rejected = self._reviewer.review(segment, drafts)
        self._store.save_annotation(
            SegmentAnnotation(
                segment_id=segment.id,
                segment_hash=content_hash(segment.text),
                annotator_version=self._annotator.version,
                annotated_at=self._clock.now(),
                annotations=tuple(accepted),
                rejected=tuple(rejected),
            )
        )
        tally.annotated += 1
        tally.empty += not accepted
        tally.statements += len(accepted)
        tally.rejected.update(r.reason for r in rejected)
        _log.info(
            "segment_annotated",
            segment_id=segment.id,
            document_id=passage.document.content_hash[:16],
            statements=len(accepted),
            rejected=len(rejected),
        )


def _context(candidate: Candidate, source: Source, document: RawDocument) -> AnnotationContext:
    return AnnotationContext(
        speaker=candidate.name,
        party=candidate.party,
        source_label=source.label,
        trust_level=document.trust_level,
        title=document.title,
        published_on=document.published_on,
    )
