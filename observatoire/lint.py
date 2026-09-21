"""Quality gates. Every one fails the build.

These are the mechanisms that make an institutional publication defensible.
They are deliberately mechanical: a reviewer can be tired, a model can be
confident, but ``quote_fr in source_text`` is either true or it is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import Claim, Document

# Judgement words. Checked in position_* and contexte_* ONLY — never in a
# quote. If a candidate calls his own plan ambitious, that is his word and it
# is evidence; censoring it would corrupt the record.
BANNED_FR = [
    "ambitieu", "audacieu", "timide", "flou", "vague", "irréaliste", "réaliste",
    "crédible", "incohérent", "insuffisant", "excessi", "modeste", "prometteu",
    "décevant", "révolutionnaire", "visionnaire", "pertinent", "dangereu",
    "remarquable", "impressionnant", "intéressant", "courageu", "raisonnable",
]
BANNED_EN = [
    "ambitious", "bold", "timid", "vague", "unrealistic", "realistic",
    "credible", "incoherent", "insufficient", "excessive", "modest",
    "promising", "disappointing", "revolutionary", "visionary", "relevant",
    "dangerous", "remarkable", "impressive", "interesting", "courageous",
    "reasonable", "sensible",
]
_BANNED = re.compile(
    r"\b(" + "|".join(BANNED_FR + BANNED_EN) + r")", re.IGNORECASE
)


@dataclass(frozen=True)
class Finding:
    gate: str
    message: str
    claim_id: str | None = None

    def __str__(self) -> str:
        where = f" [{self.claim_id}]" if self.claim_id else ""
        return f"{self.gate}{where}: {self.message}"


def check_quote_in_source(claim: Claim, source_text: str) -> list[Finding]:
    """The anti-fabrication gate. Makes an invented quote impossible to publish.

    It cannot catch a *real* quote bent into a claim it does not support —
    only the human review can. That is why the human gate exists.
    """
    if claim.quote_fr.strip() in source_text:
        return []
    return [Finding("quote-in-source",
                    f"quote not found verbatim in {claim.source_url}", claim.id)]


def check_no_evaluative_language(claim: Claim) -> list[Finding]:
    out = []
    for field in ("position_fr", "position_en", "contexte_fr", "contexte_en"):
        value = getattr(claim, field)
        for m in _BANNED.finditer(value):
            out.append(Finding("neutrality",
                               f"{field} judges rather than describes: {m.group(0)!r}",
                               claim.id))
    return out


# A real Wayback snapshot carries a 14-digit capture timestamp. The dated-query
# form (/web/2026/...) is a *request* for the nearest capture, and Wayback serves
# a "not archived" page with HTTP 200 when there is none. Checking only that the
# field is non-empty would wave a dead link through.
SNAPSHOT = re.compile(r"^https://web\.archive\.org/web/\d{14}/")


def check_archive_present(claim: Claim) -> list[Finding]:
    if not claim.archive_url:
        return [Finding("archive",
                        "no snapshot: the citation would not survive deletion", claim.id)]
    if not SNAPSHOT.match(claim.archive_url):
        return [Finding("archive",
                        f"not a capture URL, so it proves nothing: {claim.archive_url}",
                        claim.id)]
    return []


def lint(claims: list[Claim], sources: dict[str, Document]) -> list[Finding]:
    """Run every per-claim gate. ``sources`` maps source_url → document.

    Structural pluralism — every person having a cell on every axis — is not
    checked here. It is a property of the rendered grid, so it is enforced in
    the renderer, where the grid is actually built.
    """
    findings: list[Finding] = []
    for claim in claims:
        doc = sources.get(claim.source_url)
        if doc is None:
            findings.append(Finding("provenance",
                                    f"no source document for {claim.source_url}", claim.id))
        else:
            findings.extend(check_quote_in_source(claim, doc.text))
        findings.extend(check_no_evaluative_language(claim))
        findings.extend(check_archive_present(claim))
    return findings
