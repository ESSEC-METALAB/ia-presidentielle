"""CandidateMatcher: finds the candidates a text names, from config/candidates.yaml aliases."""

import re
from collections.abc import Sequence

from observatoire.domain.models import Candidate, CandidateMention


class AliasMatcher:
    """Whole-word, case-insensitive alias search.

    Aliases are chosen in config to be unambiguous ("Olivier Faure", never "Faure"
    alone), so this stays a lookup, not a guess.
    """

    def __init__(self, candidates: Sequence[Candidate]) -> None:
        self._patterns = {c.id: _alias_pattern(c.aliases or (c.name,)) for c in candidates}

    def match(self, text: str) -> list[CandidateMention]:
        counts = {cid: len(pattern.findall(text)) for cid, pattern in self._patterns.items()}
        return [
            CandidateMention(candidate_id=cid, count=count)
            for cid, count in counts.items()
            if count
        ]


def _alias_pattern(aliases: Sequence[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)
