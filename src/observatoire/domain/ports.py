"""Protocols the use cases depend on and the adapters implement.

Small on purpose (CLAUDE.md §3, I): a consumer depends only on what it calls.
TODO(step 2): LLMClient, Annotator, ScoreCalculator, ReportRenderer and
UsageTracker, with the annotation and scoring use cases.
"""

from collections.abc import Iterable
from datetime import date, datetime
from typing import Protocol

from observatoire.domain.models import (
    CandidateMention,
    CorpusOverview,
    ExtractedText,
    RawDocument,
    Source,
    SourceOutcome,
)


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
