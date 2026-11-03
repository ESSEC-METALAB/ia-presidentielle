"""Use case: stored documents, segments and annotations -> the public register.

Provenance is joined here, from the stored document, never taken from an annotation.
Only levels 1 and 2 (the candidate's or the party's own words) become statements: press
and third parties never do, however cleanly they were annotated.
"""

from collections.abc import Sequence
from datetime import date

from observatoire.domain.annotation import Dimension, SegmentAnnotation
from observatoire.domain.models import (
    Candidate,
    RawDocument,
    Segment,
    Source,
    TrustLevel,
    in_window,
)
from observatoire.domain.ports import AnnotationReader, Clock, CorpusReader, SegmentReader
from observatoire.domain.register import Register, RegisterCandidate, RegisterEntry
from observatoire.services.dedup import content_hash

_PUBLISHABLE = frozenset({TrustLevel.OWN_WORDS, TrustLevel.PARTY})


class BuildRegister:
    def __init__(
        self,
        *,
        corpus: CorpusReader,
        segments: SegmentReader,
        annotations: AnnotationReader,
        clock: Clock,
    ) -> None:
        self._corpus = corpus
        self._segments = segments
        self._annotations = annotations
        self._clock = clock

    def build(
        self,
        candidates: Sequence[Candidate],
        sources: Sequence[Source],
        dimensions: Sequence[Dimension],
        *,
        since: date | None = None,
    ) -> Register:
        running = [c for c in candidates if c.is_running]
        stored = self._annotations.list_annotations()
        version = _latest_version(stored)
        return Register(
            generated_at=self._clock.now(),
            window_start=since,
            dimensions=tuple(dimensions),
            candidates=tuple(_listed(candidate, sources) for candidate in running),
            entries=self._entries(
                {c.id for c in running},
                [s for s in sources if s.trust_level in _PUBLISHABLE],
                [a for a in stored if a.annotator_version == version],
                since,
            ),
            annotator_version=version,
            withdrawn=tuple(c for c in candidates if not c.is_running),
        )

    def _entries(
        self,
        people: set[str],
        sources: Sequence[Source],
        annotations: Sequence[SegmentAnnotation],
        since: date | None,
    ) -> tuple[RegisterEntry, ...]:
        by_source = {s.id: s for s in sources if s.candidate_id in people}
        documents = {
            d.content_hash: d
            for d in self._corpus.list_documents()
            if d.source_id in by_source and in_window(d.published_on, since)
        }
        current = self._current_segments(documents)
        entries: list[RegisterEntry] = []
        for annotation in annotations:
            found = current.get(annotation.segment_id)
            if found is None or content_hash(found[0].text) != annotation.segment_hash:
                continue  # passage gone or re-segmented since: annotated again before shown
            document = found[1]
            entries.extend(
                RegisterEntry(
                    annotation=statement, document=document, source=by_source[document.source_id]
                )
                for statement in annotation.annotations
            )
        return tuple(sorted(_one_per_quote(entries), key=lambda e: e.annotation.id))

    def _current_segments(
        self, documents: dict[str, RawDocument]
    ) -> dict[str, tuple[Segment, RawDocument]]:
        return {
            segment.id: (segment, documents[segmentation.document_hash])
            for segmentation in self._segments.list_segmentations()
            if segmentation.document_hash in documents
            for segment in segmentation.segments
        }


def _one_per_quote(entries: Sequence[RegisterEntry]) -> list[RegisterEntry]:
    """One statement per person, page and quote.

    A standing page that is rewritten is stored again under a new content hash, so its
    unchanged sentences come back as new passages. Shown twice, they would count twice.
    The copy kept is the archived one, else the most recently fetched.
    """
    kept: dict[tuple[str, str, str], RegisterEntry] = {}
    for entry in entries:
        key = (entry.document.candidate_id, entry.document.url, entry.annotation.quote)
        current = kept.get(key)
        if current is None or _preferred(entry) > _preferred(current):
            kept[key] = entry
    return list(kept.values())


def _preferred(entry: RegisterEntry) -> tuple[bool, str]:
    return entry.document.archive_url is not None, entry.document.fetched_at.isoformat()


def _listed(candidate: Candidate, sources: Sequence[Source]) -> RegisterCandidate:
    own = tuple(s for s in sources if s.candidate_id == candidate.id and s.enabled)
    return RegisterCandidate(candidate=candidate, sources=own)


def _latest_version(annotations: Sequence[SegmentAnnotation]) -> str | None:
    """The register shows one annotator's work at a time: the most recent one."""
    if not annotations:
        return None
    return max(annotations, key=lambda a: a.annotated_at).annotator_version
