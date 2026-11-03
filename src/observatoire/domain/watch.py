"""The daily watch: what may need an editor's decision. It proposes; it never edits config.

Adding a candidate or an axis is an editorial decision taken under an explicit rule
(docs/methodology.md). A script that added them on its own, during an election, under an
institution's name, could create exactly the asymmetry the register exists to avoid.
"""

from datetime import date
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RosterEntry(_Frozen):
    """One person in an outside list of declared candidates: a lead, not evidence."""

    name: str
    party: str | None = None
    declared_on: date | None = None
    withdrawn_on: date | None = None


class LeadKind(StrEnum):
    DECLARED_NOT_LISTED = "declared_not_listed"  # declared there, absent from our roster
    WITHDRAWN_BUT_LISTED = "withdrawn_but_listed"  # withdrawn there, running in our roster
    # Withdrawn in our roster, but a later declaration there, not withdrawn: running again?
    DECLARED_BUT_WITHDRAWN_HERE = "declared_but_withdrawn_here"


class CandidateLead(_Frozen):
    kind: LeadKind
    name: str
    party: str | None
    on: date | None  # the declaration or withdrawal date the outside list gives


class WatchedTopic(_Frozen):
    """A subject not yet an axis, watched in AI passages (config/taxonomy.yaml)."""

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    label_fr: str
    patterns: tuple[str, ...] = Field(min_length=1)


class PassageExample(_Frozen):
    candidate_id: str
    url: str
    excerpt: str


class TopicSignal(_Frozen):
    topic: WatchedTopic
    passages: int = Field(ge=0)
    candidates: tuple[str, ...]  # who speaks about it, by id
    examples: tuple[PassageExample, ...]


def needs_review(signal: TopicSignal, threshold: int, min_candidates: int) -> bool:
    """Enough passages, from enough different people: one programme alone is not a trend."""
    return signal.passages >= threshold and len(signal.candidates) >= min_candidates


class WatchReport(_Frozen):
    generated_at: AwareDatetime
    roster_label: str
    roster_error: str | None  # the outside list could not be read: no candidate leads today
    candidate_leads: tuple[CandidateLead, ...]
    topic_signals: tuple[TopicSignal, ...]
    topic_threshold: int = Field(ge=1)
    topic_min_candidates: int = Field(default=1, ge=1)
    ai_passages: int = Field(ge=0)  # passages that pass the AI prefilter, in the window
    pending_passages: int = Field(ge=0)  # not annotated by the current annotator
    empty_passages: tuple[PassageExample, ...]  # annotated, no statement: worth a look
