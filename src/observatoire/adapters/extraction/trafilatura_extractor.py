"""TextExtractor backed by trafilatura."""

import trafilatura
from pydantic import BaseModel, ConfigDict

from observatoire.domain.models import ExtractedText
from observatoire.services.dates import parse_date_prefix

# trafilatura's default `extensive_search` *guesses* a date when the page carries
# none, with the signature 1 January. A date is evidence: an invented one is worse
# than none (lesson carried over from the previous version, branch `daily`).
NO_DATE_GUESSING = {"extensive_search": False}


class _TrafilaturaJson(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = ""
    title: str | None = None
    date: str | None = None


class TrafilaturaExtractor:
    def __init__(self, min_chars: int) -> None:
        # Below this, a page is a teaser or a navigation page, not a text.
        self._min_chars = min_chars

    def extract(self, html: str, url: str) -> ExtractedText | None:
        raw = trafilatura.extract(
            html,
            url=url,
            output_format="json",
            with_metadata=True,
            date_extraction_params=NO_DATE_GUESSING,
        )
        if not isinstance(raw, str):
            return None
        parsed = _TrafilaturaJson.model_validate_json(raw)
        text = parsed.text.strip()
        if len(text) < self._min_chars:
            return None
        return ExtractedText(
            text=text, title=parsed.title or None, published_on=parse_date_prefix(parsed.date)
        )
