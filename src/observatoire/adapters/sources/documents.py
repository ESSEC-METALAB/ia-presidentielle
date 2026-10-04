"""The one place a reader turns collected text into a RawDocument."""

from datetime import date, datetime

from observatoire.domain.models import RawDocument, Source
from observatoire.services.dedup import content_hash


def make_document(
    source: Source,
    *,
    url: str,
    title: str | None,
    text: str,
    published_on: date | None,
    fetched_at: datetime,
) -> RawDocument:
    """Provenance comes from the source configuration, never from the content."""
    return RawDocument(
        source_id=source.id,
        candidate_id=source.candidate_id,
        url=url,
        title=title,
        text=text,
        published_on=published_on,
        fetched_at=fetched_at,
        trust_level=source.trust_level,
        content_hash=content_hash(text),
    )


def on_or_after(published_on: date | None, since: date | None) -> bool:
    """Undated documents are kept: a missing date is not evidence of age."""
    return since is None or published_on is None or published_on >= since
