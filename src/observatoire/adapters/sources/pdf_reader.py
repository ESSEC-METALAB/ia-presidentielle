"""SourceReader for a PDF with a text layer (programmes, white papers).

Scanned PDFs have no text layer and fail the source rather than yield nothing;
OCR is on the roadmap, not here.
"""

import io
from datetime import date

import pypdf
from pypdf.errors import PdfReadError

from observatoire.adapters.sources.documents import make_document, on_or_after
from observatoire.adapters.sources.http_client import PoliteHttpClient
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import RawDocument, Source
from observatoire.domain.ports import Clock
from observatoire.services.dates import parse_date_prefix


class PdfReader:
    def __init__(self, http: PoliteHttpClient, clock: Clock) -> None:
        self._http = http
        self._clock = clock

    def fetch(self, source: Source, since: date | None) -> list[RawDocument]:
        text = _pdf_text(self._http.get(source.url).content, source.url)
        # A PDF rarely states its own date reliably; the configured one was checked by hand.
        published_on = parse_date_prefix(source.options.get("published_on"))
        if not on_or_after(published_on, since):
            return []
        document = make_document(
            source,
            url=source.url,
            title=source.label,
            text=text,
            published_on=published_on,
            fetched_at=self._clock.now(),
        )
        return [document]


def _pdf_text(content: bytes, url: str) -> str:
    try:
        pages = pypdf.PdfReader(io.BytesIO(content)).pages
        text = "\n".join(page.extract_text() or "" for page in pages).strip()
    except (PdfReadError, ValueError) as error:
        raise SourceUnavailableError(url, f"unreadable PDF: {error}") from error
    if not text:
        raise SourceUnavailableError(url, "PDF has no text layer")
    return text
