"""SourceReader over the previous version's database (branch `daily`, data/observatoire.db).

That pipeline ran on GitHub Actions and collected from the same official sources.
Its documents keep their own URL, title, publication date and fetch time here, and
go through the same CollectDaily use case as a live run: same dedup key, same
storage, same view.
"""

import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from observatoire.adapters.sources.documents import make_document, on_or_after
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import RawDocument, Source
from observatoire.services.dates import parse_date_prefix

# Source kind in this version -> `kind` field of the previous version's payloads.
LEGACY_KINDS = {
    "rss": "rss",
    "page": "page",
    "pdf": "pdf",
    "assemblee_nationale": "an",
    "sitemap": "site",
}


class _LegacyPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str
    url: str
    title: str | None = None
    text: str = ""
    date: str | None = None


class LegacyPipelineReader:
    def __init__(self, database: Path) -> None:
        self._database = database

    def fetch(self, source: Source, since: date | None) -> list[RawDocument]:
        legacy_kind = LEGACY_KINDS.get(source.kind)
        if legacy_kind is None:
            return []
        documents = [
            make_document(
                source,
                url=payload.url,
                title=payload.title,
                text=payload.text.strip(),
                published_on=parse_date_prefix(payload.date),
                fetched_at=fetched_at,
            )
            for payload, fetched_at in self._rows(source.candidate_id)
            if payload.kind == legacy_kind and payload.text.strip()
        ]
        return [d for d in documents if on_or_after(d.published_on, since)]

    def _rows(self, person: str) -> list[tuple[_LegacyPayload, datetime]]:
        if not self._database.is_file():
            raise SourceUnavailableError(str(self._database), "legacy database not found")
        uri = f"file:{self._database}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            rows = connection.execute(
                "SELECT payload, fetched_at FROM documents WHERE person = ?", (person,)
            ).fetchall()
        return [
            (_LegacyPayload.model_validate_json(payload), datetime.fromisoformat(fetched_at))
            for payload, fetched_at in rows
        ]
