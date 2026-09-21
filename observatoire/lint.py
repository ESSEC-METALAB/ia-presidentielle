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
    fatal: bool = True
    """False for something a human should see but that must not stop
    publication. Used only by the link check: a source the candidate has
    deleted is expected, and is exactly what the archive snapshot exists for.
    """

    def __str__(self) -> str:
        where = f" [{self.claim_id}]" if self.claim_id else ""
        mark = "" if self.fatal else " (warning)"
        return f"{self.gate}{where}{mark}: {self.message}"


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


def resolves(url: str, timeout: float = 15.0) -> bool:
    """Does this URL still answer?

    HEAD first, then GET: plenty of servers answer HEAD with 405 while serving
    the page perfectly well, and treating that as rot would cry wolf.
    """
    import httpx

    from .fetch import UA

    for method in ("HEAD", "GET"):
        try:
            r = httpx.request(method, url, follow_redirects=True, timeout=timeout,
                              headers={"User-Agent": UA})
        except Exception:
            continue
        if r.status_code < 400:
            return True
        if r.status_code != 405:
            return False
    return False


def check_links(claims: list[Claim], probe=resolves) -> list[Finding]:
    """Link rot, reported honestly.

    Spec §7 asks that every ``source_url`` resolves. Taken literally that gate
    would fail the build the day a candidate deletes a page — which is the
    precise event the Wayback snapshot exists to survive, on a citation that
    still works. It would block publication over something nobody here
    controls, and would teach an editor to override the gates.

    So rot is fatal only when it leaves **no route to the evidence at all**:
    the original is gone *and* there is no real capture behind it. Otherwise
    the reader can still check the quote, and a human is told rather than the
    build being stopped.

    Requires network, so it is not part of the offline pull-request gate; the
    morning run calls it with ``--check-links``.
    """
    out = []
    for claim in claims:
        if probe(claim.source_url):
            continue
        archived = bool(claim.archive_url) and bool(SNAPSHOT.match(claim.archive_url))
        out.append(Finding(
            "link-rot",
            f"source no longer resolves: {claim.source_url}"
            + (" — the archived capture still does" if archived
               else " AND no capture stands behind it, so the quote cannot be checked"),
            claim.id, fatal=not archived))
    return out


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


if __name__ == "__main__":
    import argparse

    from .store import Store, load_claims

    # Runs over what is *published*, not over what the pipeline happens to
    # hold: claims.json is the file the editor reviews and the renderer
    # builds from, so it is the file the gates have to be true of.
    ap = argparse.ArgumentParser(description="Run every quality gate. Non-zero on any finding.")
    ap.add_argument("--claims", default="data/claims.json")
    ap.add_argument("--db", default="data/observatoire.db")
    ap.add_argument("--check-links", action="store_true",
                    help="also probe every source_url. Needs network, so the "
                         "offline pull-request gate leaves it out and the morning "
                         "run does it.")
    args = ap.parse_args()

    claims = load_claims(args.claims)
    store = Store(args.db)
    sources = {d.url: d for d in store.documents()}
    store.close()

    findings = lint(claims, sources)
    if args.check_links:
        findings += check_links(claims)

    for finding in findings:
        print(finding)
    fatal = [f for f in findings if f.fatal]
    warnings = len(findings) - len(fatal)
    print(f"{len(claims)} claims · {len(fatal)} findings"
          + (f" · {warnings} warnings" if warnings else ""))
    raise SystemExit(1 if fatal else 0)
