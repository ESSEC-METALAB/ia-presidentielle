"""Use case: stored documents, segments and annotations -> the public register.

Provenance is joined here, from the stored document, never taken from an annotation.
Only levels 1 and 2 (the candidate's or the party's own words) become statements: press
and third parties never do, however cleanly they were annotated.

Each passage shows one annotation: a cross-verified edition's when one covers it, else
the automatic annotator's (domain/annotation.py, `published_annotations`). Passages about
AI that nobody has annotated yet are counted as pending, per candidate, so the site never
says "aucune position identifiée" about text it has not read.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from observatoire.domain.annotation import Dimension, SegmentAnnotation, published_annotations
from observatoire.domain.models import (
    Candidate,
    RawDocument,
    Segment,
    Source,
    TrustLevel,
    in_window,
)
from observatoire.domain.ports import (
    AnnotationReader,
    Clock,
    CorpusReader,
    RelevanceFilter,
    SegmentReader,
)
from observatoire.domain.register import Register, RegisterCandidate, RegisterEntry
from observatoire.services.dedup import content_hash

_PUBLISHABLE = frozenset({TrustLevel.OWN_WORDS, TrustLevel.PARTY})


@dataclass(frozen=True)
class _Passage:
    segment: Segment
    document: RawDocument
    source: Source


class BuildRegister:
    def __init__(
        self,
        *,
        corpus: CorpusReader,
        segments: SegmentReader,
        annotations: AnnotationReader,
        relevance: RelevanceFilter,
        clock: Clock,
    ) -> None:
        self._corpus = corpus
        self._segments = segments
        self._annotations = annotations
        self._relevance = relevance
        self._clock = clock

    def build(
        self,
        candidates: Sequence[Candidate],
        sources: Sequence[Source],
        dimensions: Sequence[Dimension],
        *,
        since: date | None = None,
        verified: Sequence[str] = (),
    ) -> Register:
        """`verified`: annotator versions of cross-verified editions, in precedence order."""
        running = [c for c in candidates if c.is_running]
        documents = self._documents({c.id for c in running}, sources, since)
        passages = self._current_passages(documents, sources)
        hashes = {pid: content_hash(p.segment.text) for pid, p in passages.items()}
        chosen = published_annotations(self._annotations.list_annotations(), hashes, verified)
        return Register(
            generated_at=self._clock.now(),
            window_start=since,
            dimensions=tuple(dimensions),
            candidates=tuple(_listed(candidate, sources) for candidate in running),
            entries=_entries(passages, chosen, verified),
            annotators=_annotators(chosen, verified),
            pending=self._pending(passages, chosen),
            withdrawn=tuple(c for c in candidates if not c.is_running),
            documents=dict(Counter(d.source_id for d in documents.values())),
        )

    def _documents(
        self, people: set[str], sources: Sequence[Source], since: date | None
    ) -> dict[str, RawDocument]:
        """Running people's level-1 and level-2 documents in the window, by content hash."""
        publishable = {
            s.id for s in sources if s.candidate_id in people and s.trust_level in _PUBLISHABLE
        }
        return {
            d.content_hash: d
            for d in self._corpus.list_documents()
            if d.source_id in publishable and in_window(d.published_on, since)
        }

    def _current_passages(
        self, documents: dict[str, RawDocument], sources: Sequence[Source]
    ) -> dict[str, _Passage]:
        """Passages of the documents the register reads, with their source."""
        by_source = {s.id: s for s in sources}
        return {
            segment.id: _Passage(segment, document, by_source[document.source_id])
            for segmentation in self._segments.list_segmentations()
            if (document := documents.get(segmentation.document_hash)) is not None
            for segment in segmentation.segments
        }

    def _pending(
        self, passages: dict[str, _Passage], chosen: dict[str, SegmentAnnotation]
    ) -> dict[str, int]:
        pending: Counter[str] = Counter(
            passage.document.candidate_id
            for pid, passage in passages.items()
            if pid not in chosen and self._relevance.is_relevant(passage.segment.text)
        )
        return dict(pending)


def _entries(
    passages: dict[str, _Passage],
    chosen: dict[str, SegmentAnnotation],
    verified: Sequence[str],
) -> tuple[RegisterEntry, ...]:
    entries = [
        RegisterEntry(
            annotation=statement,
            document=passages[pid].document,
            source=passages[pid].source,
            annotator_version=annotation.annotator_version,
            verified=annotation.annotator_version in verified,
        )
        for pid, annotation in chosen.items()
        for statement in annotation.annotations
    ]
    return tuple(sorted(_one_per_quote(entries), key=lambda e: e.annotation.id))


def _annotators(chosen: dict[str, SegmentAnnotation], verified: Sequence[str]) -> tuple[str, ...]:
    used = {a.annotator_version for a in chosen.values()}
    return tuple(sorted(used, key=lambda v: (v not in verified, v)))


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
