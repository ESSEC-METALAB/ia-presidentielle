"""Protocols the use cases depend on and the adapters implement.

Small on purpose (CLAUDE.md §3, I): a consumer depends only on what it calls.
TODO: ScoreCalculator, with the scoring use case, if the register ever publishes one.
"""

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Protocol

from observatoire.domain.annotation import (
    AnnotationContext,
    DimensionAnnotation,
    LLMResponse,
    Prompt,
    RejectedDraft,
    ResponseSchema,
    SegmentAnnotation,
    StatementDraft,
    UsageRecord,
)
from observatoire.domain.models import (
    CandidateMention,
    CorpusOverview,
    DocumentSegmentation,
    ExtractedText,
    RawDocument,
    Segment,
    Source,
    SourceOutcome,
)
from observatoire.domain.register import Register
from observatoire.domain.watch import RosterEntry, WatchReport


class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware current time."""
        ...


class SourceReader(Protocol):
    def fetch(self, source: Source, since: date | None) -> Iterable[RawDocument]:
        """Documents published on or after `since`; undated documents are always kept."""
        ...


class TextExtractor(Protocol):
    def extract(self, html: str, url: str) -> ExtractedText | None:
        """Main text of a page, or None when there is no usable body."""
        ...


class DocumentRepository(Protocol):
    def exists(self, content_hash: str) -> bool: ...

    def save(self, document: RawDocument) -> None: ...


class CorpusReader(Protocol):
    def list_documents(self) -> list[RawDocument]: ...


class SourceRunLog(Protocol):
    def record(self, outcome: SourceOutcome) -> None: ...


class SourceRunHistory(Protocol):
    def latest_by_source(self) -> dict[str, SourceOutcome]: ...


class CandidateMatcher(Protocol):
    def match(self, text: str) -> list[CandidateMention]:
        """Candidates named in `text`, with how often."""
        ...


class CorpusRenderer(Protocol):
    def render(self, overview: CorpusOverview) -> str: ...


class Segmenter(Protocol):
    @property
    def version(self) -> str:
        """Changes whenever the rules or their settings change."""
        ...

    def segment(
        self, source: Source, documents: Sequence[RawDocument]
    ) -> list[DocumentSegmentation]:
        """All documents of one source at once: boilerplate is what repeats across them."""
        ...


class SegmentStore(Protocol):
    def segmented_versions(self) -> dict[str, str]:
        """Document content hash -> version of the segmenter that last processed it."""
        ...

    def replace(self, segmentations: Sequence[DocumentSegmentation]) -> None: ...


class SegmentReader(Protocol):
    def list_segmentations(self) -> list[DocumentSegmentation]: ...


class LLMClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete(self, prompt: Prompt, schema: ResponseSchema) -> LLMResponse:
        """Raises AnnotationUnavailableError when no answer can be had now."""
        ...


class Annotator(Protocol):
    @property
    def version(self) -> str:
        """Model, prompt and taxonomy: changes whenever any of them changes."""
        ...

    def annotate(self, segment: Segment, context: AnnotationContext) -> list[StatementDraft]:
        """Proposals only. Raises AnnotationUnavailableError or MalformedAnnotationError."""
        ...


class RelevanceFilter(Protocol):
    def is_relevant(self, text: str) -> bool:
        """Cheap and deterministic: decides which passages are worth annotating."""
        ...


class DraftReviewer(Protocol):
    def review(
        self, segment: Segment, drafts: Sequence[StatementDraft]
    ) -> tuple[list[DimensionAnnotation], list[RejectedDraft]]:
        """Accepted annotations, quoting the passage's own text, and rejections with why."""
        ...


class AnnotationStore(Protocol):
    def annotated_segments(self, annotator_version: str) -> dict[str, str]:
        """Segment id -> hash of the passage text it was annotated on, for this version."""
        ...

    def save_annotation(self, annotation: SegmentAnnotation) -> None: ...


class AnnotationReader(Protocol):
    def list_annotations(self) -> list[SegmentAnnotation]: ...


class UsageTracker(Protocol):
    def record_usage(self, record: UsageRecord) -> None: ...


class RegisterRenderer(Protocol):
    def render(self, register: Register) -> str: ...


class RosterSource(Protocol):
    @property
    def label(self) -> str: ...

    def fetch(self) -> list[RosterEntry]:
        """Raises SourceUnavailableError when the list cannot be read."""
        ...


class WatchRenderer(Protocol):
    def render(self, report: WatchReport) -> str: ...
