"""RosterSource over the MieuxVoter community list of 2027 candidacies (CSV on GitHub).

Columns used: complete_name, parti, annonce_candidature, retrait_candidature (ISO dates).
A community dataset: what it says is a lead for an editor, never evidence by itself.
"""

import csv
import io

from pydantic import ValidationError

from observatoire.adapters.sources.http_client import PoliteHttpClient
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.watch import RosterEntry
from observatoire.services.dates import parse_date_prefix

_REQUIRED = {"complete_name", "parti", "annonce_candidature", "retrait_candidature"}


class MieuxVoterRoster:
    def __init__(self, http: PoliteHttpClient, url: str, label: str) -> None:
        self._http = http
        self._url = url
        self._label = label

    @property
    def label(self) -> str:
        return self._label

    def fetch(self) -> list[RosterEntry]:
        """Any malformed content fails the list as a whole, as SourceUnavailableError."""
        text = self._http.get(self._url).text
        try:
            rows = csv.DictReader(io.StringIO(text), strict=True)  # a broken quote raises
            missing = _REQUIRED - set(rows.fieldnames or ())
            if missing:
                raise SourceUnavailableError(self._url, f"missing column(s): {sorted(missing)}")
            return [entry for row in rows if (entry := _entry(row)) is not None]
        except (csv.Error, ValidationError) as error:
            raise SourceUnavailableError(self._url, f"unreadable CSV: {error}") from error


def _field(row: dict[str | None, str | None], name: str) -> str:
    """A short row has None for its missing fields; a long one, extra values under None."""
    return (row.get(name) or "").strip()


def _entry(row: dict[str | None, str | None]) -> RosterEntry | None:
    name = _field(row, "complete_name")
    if not name:
        return None
    return RosterEntry(
        name=name,
        party=_field(row, "parti") or None,
        declared_on=parse_date_prefix(_field(row, "annonce_candidature") or None),
        withdrawn_on=parse_date_prefix(_field(row, "retrait_candidature") or None),
    )
