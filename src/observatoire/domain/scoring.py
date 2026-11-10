"""Scores of a published statement on the scales of config/scoring.yaml.

The scorer proposes, for each scale, a score from 1 to 5, the reason and the words of
the quote it rests on; code keeps the score only when those words are in the quote. A
scale that does not apply is left empty. Scores describe a stated position, never the
quality of a candidate.
"""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScoreScale(_Frozen):
    """One scale (config/scoring.yaml): what 1 and 5 mean, overall and per axis."""

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    label_fr: str
    label_en: str
    low_fr: str
    low_en: str
    high_fr: str
    high_en: str
    question_en: str
    # Axis id -> {1: ..., 3: ..., 5: ...}: what the ends and the middle mean on that axis.
    anchors: dict[str, dict[int, str]] = Field(default_factory=dict)


class ScaleDraft(_Frozen):
    """What a scorer proposes on one scale. `score` None: the scale does not apply."""

    scale: str
    score: int | None = Field(default=None, ge=1, le=5)
    reason_fr: str = ""
    reason_en: str = ""
    evidence: str = ""  # words of the quote


class ScoreDraft(_Frozen):
    scores: tuple[ScaleDraft, ...]


class ScaleScore(_Frozen):
    """An accepted score on one scale, with why."""

    scale: str
    score: int = Field(ge=1, le=5)
    reason_fr: str
    reason_en: str
    evidence: str


class StatementScore(_Frozen):
    """The scores of one statement, keyed like its framing (passage id and quote hash).

    `dropped`: scales the scorer scored but whose evidence code could not find in the
    quote: those scores are not kept.
    """

    key: str
    scorer_version: str
    scored_at: AwareDatetime
    scores: tuple[ScaleScore, ...]
    dropped: tuple[str, ...] = ()
