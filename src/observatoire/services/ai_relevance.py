"""Deterministic prefilter: which passages are worth sending to the annotator.

Two tiers, measured in the previous version: one strong pattern is enough, weak patterns
need corroboration. A single stray "données" in a tax debate does not make it AI.
"""

import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RelevanceSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strong_patterns: tuple[str, ...] = Field(min_length=1)
    weak_patterns: tuple[str, ...] = ()
    weak_min_distinct: int = Field(default=2, ge=1)

    @field_validator("strong_patterns", "weak_patterns")
    @classmethod
    def _compiles(cls, patterns: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"{pattern!r}: {error}") from error
        return patterns


def _alternation(patterns: Sequence[str]) -> re.Pattern[str] | None:
    if not patterns:
        return None
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


class TermRelevanceFilter:
    def __init__(self, settings: RelevanceSettings) -> None:
        self._strong = _alternation(settings.strong_patterns)
        self._weak = _alternation(settings.weak_patterns)
        self._weak_min = settings.weak_min_distinct

    def is_relevant(self, text: str) -> bool:
        if self._strong is not None and self._strong.search(text):
            return True
        if self._weak is None:
            return False
        distinct = {match.group(0).lower() for match in self._weak.finditer(text)}
        return len(distinct) >= self._weak_min
