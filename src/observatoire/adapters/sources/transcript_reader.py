"""SourceReader for the transcript of a recorded speech, kept as a file in the repository.

A speech given on video has no text to download: its transcript is stored next to the
configuration, and the source's URL is the recording, which is what the register links
to. The transcript is a monologue (one speaker, the candidate), never an interview
where questions and answers are not labelled.
"""

from datetime import date
from pathlib import Path

from observatoire.adapters.sources.documents import make_document
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import RawDocument, Source, in_window
from observatoire.domain.ports import Clock
from observatoire.services.dates import parse_date_prefix


class TranscriptReader:
    def __init__(self, root: Path, clock: Clock) -> None:
        self._root = root
        self._clock = clock

    def fetch(self, source: Source, since: date | None) -> list[RawDocument]:
        name = source.options.get("file")
        if not name:
            raise SourceUnavailableError(source.url, "no transcript file configured")
        path = self._root / name
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise SourceUnavailableError(source.url, f"unreadable transcript: {error}") from error
        if not text:
            raise SourceUnavailableError(source.url, "empty transcript")
        # The recording's date, checked by hand: a video page states it, the file does not.
        published_on = parse_date_prefix(source.options.get("published_on"))
        if not in_window(published_on, since):
            return []
        return [
            make_document(
                source,
                url=source.url,
                title=source.label,
                text=text,
                published_on=published_on,
                fetched_at=self._clock.now(),
            )
        ]
