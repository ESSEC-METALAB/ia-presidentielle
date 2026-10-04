"""SourceReader for RSS and Atom feeds: each entry's page is fetched and extracted."""

import time
from collections.abc import Iterator
from datetime import date
from typing import Any

import feedparser
import structlog
from pydantic import BaseModel

from observatoire.adapters.sources.documents import make_document, on_or_after
from observatoire.adapters.sources.http_client import PoliteHttpClient
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import RawDocument, Source
from observatoire.domain.ports import Clock, TextExtractor

_log = structlog.get_logger(__name__)


class _FeedEntry(BaseModel):
    link: str | None
    title: str | None
    published_on: date | None

    @classmethod
    def parse(cls, entry: Any) -> "_FeedEntry":
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        return cls(
            link=entry.get("link"),
            title=entry.get("title"),
            published_on=date(*published[:3]) if isinstance(published, time.struct_time) else None,
        )


class RssReader:
    def __init__(self, http: PoliteHttpClient, extractor: TextExtractor, clock: Clock) -> None:
        self._http = http
        self._extractor = extractor
        self._clock = clock

    def fetch(self, source: Source, since: date | None) -> Iterator[RawDocument]:
        feed = feedparser.parse(self._http.get(source.url).content)
        entries = [_FeedEntry.parse(entry) for entry in feed.entries[: source.max_items]]
        if not entries and feed.get("bozo"):
            raise SourceUnavailableError(source.url, "unparseable feed")
        for entry in entries:
            if not on_or_after(entry.published_on, since):
                continue
            document = self._read(source, entry)
            if document is not None:
                yield document

    def _read(self, source: Source, entry: _FeedEntry) -> RawDocument | None:
        if not entry.link:
            return None
        try:
            page = self._http.get(entry.link)
        except SourceUnavailableError as failure:  # one bad item does not fail the feed
            _log.warning(
                "feed_item_skipped", source_id=source.id, url=entry.link, reason=failure.reason
            )
            return None
        extracted = self._extractor.extract(page.text, entry.link)
        if extracted is None:
            return None
        return make_document(
            source,
            url=entry.link,
            title=extracted.title or entry.title,
            text=extracted.text,
            published_on=extracted.published_on or entry.published_on,
            fetched_at=self._clock.now(),
        )
