"""The gates every proposed annotation passes before it is kept.

The quote gate is the anti-fabrication rule: a quote the passage does not contain cannot
be stored. It cannot catch a real quote bent into a summary it does not support; only
human review can, which is why the register says when it has not been reviewed.
"""

import re
from collections.abc import Collection, Sequence

from pydantic import BaseModel, ConfigDict, Field

from observatoire.domain.annotation import (
    DimensionAnnotation,
    RejectedDraft,
    RejectionReason,
    StatementDraft,
)
from observatoire.domain.models import Segment, Span

# Typographic variants a model may substitute when copying. Each maps to one character,
# so offsets in the normalised text are offsets in the original, and the stored quote is
# sliced from the original: matching tolerates the variant, the record never carries it.
_EQUIVALENT_CHARACTERS = str.maketrans(
    {
        "\u2019": "'",  # right single quotation mark
        "\u2018": "'",  # left single quotation mark
        "\u02bc": "'",  # modifier letter apostrophe
        "\u00a0": " ",  # no-break space
        "\u202f": " ",  # narrow no-break space
        "\u2009": " ",  # thin space
    }
)
# Fields that describe the statement in our words, by language. Never the quote or its
# gloss: if a candidate calls their own plan ambitious, that is their word and evidence.
# Each language has its own list: "sensible" judges in English and means "sensitive" in
# French ("données sensibles"), so one list for both fields would reject a faithful note.
_DESCRIPTIVE_FIELDS = {"fr": ("summary_fr", "context_fr"), "en": ("summary_en", "context_en")}


class GateSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_max_words: int = Field(ge=1)
    evaluative_stems_fr: tuple[str, ...] = ()
    evaluative_stems_en: tuple[str, ...] = ()


def _stem_pattern(stems: Sequence[str]) -> re.Pattern[str] | None:
    alternatives = "|".join(re.escape(stem) for stem in stems)
    return re.compile(rf"\b(?:{alternatives})", re.IGNORECASE) if alternatives else None


def _normalised(text: str) -> str:
    return text.translate(_EQUIVALENT_CHARACTERS)


def find_quote(passage: str, quote: str) -> Span | None:
    """Where `quote` occurs in `passage`, whitespace and apostrophe variants aside."""
    wanted = " ".join(_normalised(quote).split())
    if not wanted:
        return None
    start = _normalised(passage).find(wanted)
    return None if start < 0 else (start, start + len(wanted))


class AnnotationGates:
    def __init__(self, dimension_ids: Collection[str], settings: GateSettings) -> None:
        self._dimensions = frozenset(dimension_ids)
        self._max_words = settings.quote_max_words
        self._evaluative = {
            "fr": _stem_pattern(settings.evaluative_stems_fr),
            "en": _stem_pattern(settings.evaluative_stems_en),
        }

    def review(
        self, segment: Segment, drafts: Sequence[StatementDraft]
    ) -> tuple[list[DimensionAnnotation], list[RejectedDraft]]:
        accepted: list[DimensionAnnotation] = []
        rejected: list[RejectedDraft] = []
        for draft in drafts:
            outcome = self._check(segment, draft, {a.quote_span for a in accepted})
            if isinstance(outcome, RejectedDraft):
                rejected.append(outcome)
                continue
            accepted.append(self._accept(segment, draft, outcome, len(accepted)))
        return accepted, rejected

    def _check(
        self, segment: Segment, draft: StatementDraft, taken: set[Span]
    ) -> Span | RejectedDraft:
        if draft.dimension not in self._dimensions:
            return _reject(draft, RejectionReason.UNKNOWN_DIMENSION, draft.dimension)
        words = len(draft.quote.split())
        if words > self._max_words:
            return _reject(draft, RejectionReason.QUOTE_TOO_LONG, f"{words} words")
        span = find_quote(segment.text, draft.quote)
        if span is None:
            return _reject(draft, RejectionReason.QUOTE_NOT_IN_PASSAGE, segment.id)
        if span in taken:
            return _reject(draft, RejectionReason.DUPLICATE_QUOTE, f"{span[0]}-{span[1]}")
        judgement = self._judgement(draft)
        if judgement is not None:
            return _reject(draft, RejectionReason.EVALUATIVE_LANGUAGE, judgement)
        return span

    def _judgement(self, draft: StatementDraft) -> str | None:
        for language, fields in _DESCRIPTIVE_FIELDS.items():
            pattern = self._evaluative[language]
            if pattern is None:
                continue
            for field in fields:
                match = pattern.search(getattr(draft, field))
                if match:
                    return f"{field}: {match.group(0)!r}"
        return None

    @staticmethod
    def _accept(
        segment: Segment, draft: StatementDraft, span: Span, index: int
    ) -> DimensionAnnotation:
        return DimensionAnnotation(
            segment_id=segment.id,
            index=index,
            dimension=draft.dimension,
            quote=segment.text[span[0] : span[1]],
            quote_span=span,
            summary_fr=draft.summary_fr,
            summary_en=draft.summary_en,
            context_fr=draft.context_fr,
            context_en=draft.context_en,
            gloss_en=draft.gloss_en,
        )


def _reject(draft: StatementDraft, reason: RejectionReason, detail: str) -> RejectedDraft:
    return RejectedDraft(draft=draft, reason=reason, detail=detail)
