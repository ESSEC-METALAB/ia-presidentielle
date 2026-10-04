"""SourceReader for a single standing HTML page, re-read on every run.

Some candidates publish a priorities page and no feed. Rewrites are caught by the
content hash: an unchanged page is a duplicate, a rewritten one is a new document.
"""

from datetime import date

from observatoire.adapters.sources.documents import make_document
from observatoire.adapters.sources.http_client import PoliteHttpClient
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import RawDocument, Source
from observatoire.domain.ports import Clock, TextExtractor


class HtmlPageReader:
    def __init__(self, http: PoliteHttpClient, extractor: TextExtractor, clock: Clock) -> None:
        self._http = http
        self._extractor = extractor
        self._clock = clock

    def fetch(self, source: Source, since: date | None) -> list[RawDocument]:
        page = self._http.get(source.url)
        extracted = self._extractor.extract(page.text, source.url)
        if extracted is None:
            raise SourceUnavailableError(source.url, "no extractable text")
        return [
            make_document(
                source,
                url=source.url,
                title=source.label,
                text=extracted.text,
                published_on=extracted.published_on,
                fetched_at=self._clock.now(),
            )
        ]
