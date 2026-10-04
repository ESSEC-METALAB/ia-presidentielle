"""Segmentation as the raw-corpus page shows it: per document, per candidate, per reason."""

import statistics
from collections import Counter
from dataclasses import dataclass

from observatoire.domain.models import (
    CandidateCorpus,
    CorpusOverview,
    DocumentView,
    ExclusionReason,
)

REASON_LABELS = {
    ExclusionReason.PAGE_NUMBER: "Numéro de page ou de section",
    ExclusionReason.REPEATED_IN_DOCUMENT: "Ligne courte répétée dans le document (en-tête)",
    ExclusionReason.REPEATED_IN_SOURCE: (
        "Ligne répétée dans plusieurs documents de la source (signature, rubrique)"
    ),
    ExclusionReason.RELATED_LINKS: "Liste de liens vers d'autres articles",
    ExclusionReason.INTERFACE_TEXT: "Texte d'interface (bandeau de cookies)",
    ExclusionReason.STAGE_DIRECTION: "Didascalie du compte rendu (applaudissements, exclamations…)",
    ExclusionReason.TOO_SHORT: "Passage trop court pour porter une position",
}
_EXCERPT_CHARS = 160


@dataclass(frozen=True)
class SegmentItem:
    number: int
    text: str
    others: str  # other candidates the segment names, "" when none


@dataclass(frozen=True)
class ExcludedItem:
    label: str
    excerpt: str


@dataclass(frozen=True)
class DocumentSegments:
    status: str  # "segmented", "empty" or "pending"
    label: str
    segments: tuple[SegmentItem, ...]
    excluded: tuple[ExcludedItem, ...]


@dataclass(frozen=True)
class CandidateSegmentation:
    name: str
    monitored: bool
    documents: int
    segmented: int
    empty: int
    pending: int
    segments: int
    median_chars: str
    naming_others: int


@dataclass(frozen=True)
class ExclusionRow:
    label: str
    passages: int
    characters: int


@dataclass(frozen=True)
class SegmentationSummary:
    version: str | None
    segments: int
    empty_documents: int
    pending_documents: int
    candidates: tuple[CandidateSegmentation, ...]
    exclusions: tuple[ExclusionRow, ...]


def document_segments(view: DocumentView, names: dict[str, str]) -> DocumentSegments:
    segmentation = view.segmentation
    if segmentation is None:
        return DocumentSegments(status="pending", label="non découpé", segments=(), excluded=())
    text, own = view.document.text, view.document.candidate_id
    segments = tuple(
        SegmentItem(
            number=segment.index + 1,
            text=segment.text,
            others=", ".join(
                names[m.candidate_id] for m in segment.mentions if m.candidate_id != own
            ),
        )
        for segment in segmentation.segments
    )
    excluded = tuple(
        ExcludedItem(label=REASON_LABELS[p.reason], excerpt=_excerpt(text[p.span[0] : p.span[1]]))
        for p in segmentation.excluded
    )
    count = len(segments)
    label = f"{count} segment{'s' if count > 1 else ''}" if count else "aucun passage exploitable"
    status = "segmented" if count else "empty"
    return DocumentSegments(status=status, label=label, segments=segments, excluded=excluded)


def summarize(overview: CorpusOverview) -> SegmentationSummary:
    views = [v for c in overview.candidates for s in c.sources for v in s.documents]
    versions = {v.segmentation.segmenter_version for v in views if v.segmentation}
    rows = tuple(_candidate(corpus) for corpus in overview.candidates)
    return SegmentationSummary(
        version=", ".join(sorted(versions)) or None,
        segments=sum(row.segments for row in rows),
        empty_documents=sum(row.empty for row in rows),
        pending_documents=sum(row.pending for row in rows),
        candidates=rows,
        exclusions=_exclusions(views),
    )


def _candidate(corpus: CandidateCorpus) -> CandidateSegmentation:
    views = [v for s in corpus.sources for v in s.documents]
    done = [v.segmentation for v in views if v.segmentation is not None]
    segments = [segment for s in done for segment in s.segments]
    own = corpus.candidate.id
    return CandidateSegmentation(
        name=corpus.candidate.name,
        monitored=corpus.monitored,
        documents=len(views),
        segmented=sum(1 for s in done if not s.is_empty),
        empty=sum(1 for s in done if s.is_empty),
        pending=len(views) - len(done),
        segments=len(segments),
        median_chars=f"{statistics.median(len(s.text) for s in segments):.0f}" if segments else "—",
        naming_others=sum(1 for s in segments if any(m.candidate_id != own for m in s.mentions)),
    )


def _exclusions(views: list[DocumentView]) -> tuple[ExclusionRow, ...]:
    passages: Counter[ExclusionReason] = Counter()
    characters: Counter[ExclusionReason] = Counter()
    for view in views:
        for passage in view.segmentation.excluded if view.segmentation else ():
            passages[passage.reason] += 1
            characters[passage.reason] += passage.span[1] - passage.span[0]
    return tuple(
        ExclusionRow(label=REASON_LABELS[reason], passages=count, characters=characters[reason])
        for reason, count in passages.most_common()
    )


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _EXCERPT_CHARS else flat[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
