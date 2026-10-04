"""Date parsing that refuses to guess."""

import re
from datetime import date

_ISO_PREFIX = re.compile(r"^\s*(\d{4})-?(\d{2})-?(\d{2})")


def parse_date_prefix(value: str | None) -> date | None:
    """`2026-09-18`, `20260918` or `2026-09-18T10:00:00+02:00` -> a date; anything else -> None."""
    if not value:
        return None
    match = _ISO_PREFIX.match(value)
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None
