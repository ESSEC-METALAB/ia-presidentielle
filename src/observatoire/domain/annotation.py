"""Annotation entities: a passage, the dimension it addresses, and the exact words that show it.

The annotator proposes; code decides. A proposal (`StatementDraft`) carries no provenance:
who spoke, where and when are attached from the stored document, never reported by a
model. A proposal becomes a `DimensionAnnotation` only after the gates have found its
quote in the passage, and the stored quote is the passage's own text, not the model's copy.
"""

from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from observatoire.domain.models import Span, TrustLevel


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Dimension(_Frozen):
    """One axis of AI policy (config/taxonomy.yaml). Names a subject, never a direction."""

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    label_fr: str
    label_en: str
    definition_fr: str
    definition_en: str


class StatementDraft(_Frozen):
    """What an annotator proposes for one passage.

    `extra="forbid"` is deliberate: a model cannot slip a speaker, a URL or a date in.
    """

    dimension: str
    quote: str = Field(min_length=1)
    summary_fr: str = Field(min_length=1)
    summary_en: str = Field(min_length=1)
    context_fr: str = Field(min_length=1)
    context_en: str = Field(min_length=1)
    gloss_en: str = Field(min_length=1)


class RejectionReason(StrEnum):
    """Why a proposal was not kept. Every rejection is stored, none is corrected."""

    QUOTE_NOT_IN_PASSAGE = "quote_not_in_passage"
    QUOTE_TOO_LONG = "quote_too_long"
    DUPLICATE_QUOTE = "duplicate_quote"
    UNKNOWN_DIMENSION = "unknown_dimension"
    EVALUATIVE_LANGUAGE = "evaluative_language"


class RejectedDraft(_Frozen):
    draft: StatementDraft
    reason: RejectionReason
    detail: str


class DimensionAnnotation(_Frozen):
    """An accepted statement. `quote` is the segment's own text over `quote_span`."""

    segment_id: str
    index: int = Field(ge=0)
    dimension: str
    quote: str = Field(min_length=1)
    quote_span: Span  # character offsets in the segment's text
    summary_fr: str
    summary_en: str
    context_fr: str
    context_en: str
    gloss_en: str

    @property
    def id(self) -> str:
        """Stable while the passage is unchanged: the segment id derives from its content."""
        return f"{self.segment_id}-{self.index:02d}"


class SegmentAnnotation(_Frozen):
    """One annotator's answer for one passage, kept whole: accepted and rejected."""

    segment_id: str
    # Hash of the passage text when annotated: a re-segmented passage is annotated again.
    segment_hash: str
    annotator_version: str
    annotated_at: AwareDatetime
    annotations: tuple[DimensionAnnotation, ...]
    rejected: tuple[RejectedDraft, ...] = ()

    @property
    def is_empty(self) -> bool:
        """No AI-policy statement here: the expected answer for most passages."""
        return not self.annotations


def current_annotator(annotations: Sequence[SegmentAnnotation]) -> str | None:
    """The annotator whose work the register shows: one at a time, never a mix.

    The one that has annotated the most passages, the most recent on a tie. A new
    provider (say, Mistral after a recorded batch) takes over once it has caught up, so
    a run that stops halfway (quota, outage) never empties the register overnight.
    """
    coverage: dict[str, tuple[int, AwareDatetime]] = {}
    for annotation in annotations:
        count, latest = coverage.get(annotation.annotator_version, (0, annotation.annotated_at))
        coverage[annotation.annotator_version] = (count + 1, max(latest, annotation.annotated_at))
    if not coverage:
        return None
    return max(coverage, key=lambda version: coverage[version])


class AnnotationContext(_Frozen):
    """What the annotator is told about a passage, from the stored document and config."""

    speaker: str
    party: str
    source_label: str
    trust_level: TrustLevel
    title: str | None
    published_on: date | None


class AnnotationReport(_Frozen):
    annotator_version: str
    segments_read: int = Field(ge=0)
    not_relevant: int = Field(ge=0)  # stopped by the deterministic prefilter
    already_annotated: int = Field(ge=0)
    annotated: int = Field(ge=0)
    empty: int = Field(ge=0)  # annotated, no statement found
    pending: int = Field(ge=0)  # left for a later run by --limit
    failed: int = Field(ge=0)  # no usable answer; tried again on the next run
    statements: int = Field(ge=0)
    rejected: dict[RejectionReason, int]


class Prompt(_Frozen):
    """A rendered prompt. `version` names the template file and its content hash."""

    version: str
    system: str
    user: str


class ResponseSchema(_Frozen):
    """The JSON Schema the answer must follow, serialised: a schema, not data."""

    name: str
    json_schema: str


class LLMResponse(_Frozen):
    model: str
    content: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class UsageRecord(_Frozen):
    step: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    recorded_at: AwareDatetime
