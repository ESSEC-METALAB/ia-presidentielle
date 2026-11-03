"""RosterSource over the MieuxVoter community list of 2027 candidacies (CSV on GitHub).

Columns used: complete_name, parti, annonce_candidature, retrait_candidature (ISO dates).
A community dataset: what it says is a lead for an editor, never evidence by itself.
"""

import csv
import io

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
        rows = csv.DictReader(io.StringIO(self._http.get(self._url).text))
        missing = _REQUIRED - set(rows.fieldnames or ())
        if missing:
            raise SourceUnavailableError(self._url, f"missing column(s): {sorted(missing)}")
        return [
            RosterEntry(
                name=row["complete_name"].strip(),
                party=row["parti"].strip() or None,
                declared_on=parse_date_prefix(row["annonce_candidature"]),
                withdrawn_on=parse_date_prefix(row["retrait_candidature"]),
            )
            for row in rows
            if row["complete_name"].strip()
        ]
