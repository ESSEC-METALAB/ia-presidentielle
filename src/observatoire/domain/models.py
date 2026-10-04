"""Domain entities, as frozen Pydantic v2 models.

Collection and corpus inspection only, for now. TODO(step 2): Segment,
DimensionAnnotation, DimensionScore and RunReport, once docs/methodology.md
settles what a score is.
"""

from datetime import date
from enum import IntEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class TrustLevel(IntEnum):
    """Whose words a source carries (README, "Niveaux de source")."""

    OWN_WORDS = 1
    PARTY = 2
    PRESS = 3
    THIRD_PARTY = 4


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Candidate(_Frozen):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    party: str
    aliases: tuple[str, ...] = ()


class Source(_Frozen):
    """Where a candidate's words are read from. `kind` selects the reader."""

    id: str
    candidate_id: str
    kind: str
    url: str
    trust_level: TrustLevel
    label: str
    max_items: int = Field(default=20, ge=1)
    enabled: bool = True
    # Reader-specific settings; each reader validates its own on use.
    options: dict[str, str] = Field(default_factory=dict)


class ExtractedText(_Frozen):
    text: str
    title: str | None
    # None when the page does not state a date. A date is evidence: never guessed.
    published_on: date | None


class RawDocument(_Frozen):
    """A text as collected, with its provenance. Nothing here is analysed yet."""

    source_id: str
    candidate_id: str
    url: str
    title: str | None
    text: str = Field(min_length=1)
    published_on: date | None
    fetched_at: AwareDatetime
    trust_level: TrustLevel
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceOutcome(_Frozen):
    """One source in one run. `fetched` counts what the source returned: the liveness signal."""

    run_id: str
    source_id: str
    started_at: AwareDatetime
    duration_ms: int = Field(ge=0)
    status: Literal["ok", "failed"]
    fetched: int = Field(ge=0)
    new: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    error: str | None = None


class CollectionReport(_Frozen):
    run_id: str
    outcomes: tuple[SourceOutcome, ...]

    @property
    def new_documents(self) -> int:
        return sum(outcome.new for outcome in self.outcomes)

    @property
    def failed_sources(self) -> tuple[str, ...]:
        return tuple(o.source_id for o in self.outcomes if o.status == "failed")


class CandidateMention(_Frozen):
    candidate_id: str
    count: int = Field(ge=1)


class DocumentView(_Frozen):
    document: RawDocument
    # How often the text names its own candidate. Zero is common on party feeds,
    # which carry the whole party's news: attribution by source is a default.
    mentions_of_candidate: int = Field(ge=0)


class SourceCorpus(_Frozen):
    source: Source
    documents: tuple[DocumentView, ...]
    last_outcome: SourceOutcome | None


class CandidateCorpus(_Frozen):
    candidate: Candidate
    sources: tuple[SourceCorpus, ...]

    @property
    def monitored(self) -> bool:
        """False when no source is configured: *non suivi*, not *aucune position*."""
        return bool(self.sources)


class CorpusOverview(_Frozen):
    generated_at: AwareDatetime
    candidates: tuple[CandidateCorpus, ...]
    # Stored documents whose source is no longer configured. Counted, never dropped silently.
    unconfigured_documents: int = Field(ge=0)
