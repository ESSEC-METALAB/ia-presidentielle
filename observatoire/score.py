"""Spectrum placement — an internal research instrument, never a published verdict.

Places a candidate at a coordinate between two *named poles* on one axis, from
the claims already extracted for that axis. The number is a **location, not a
grade**: 1 is not worse than 5, and neither end is the good end. That is the
whole reason this can exist beside a publication whose neutrality lint rejects
``ambitieux`` and ``timide`` — a placement says where someone stands, not how
well they scored.

Three rules hold it to the rest of the pipeline:

* **Nothing here is rendered.** ``render.py`` builds from ``data/claims.json``
  and never reads this module's output. The published grid stays quotes and
  context, so the coverage asymmetry it already declares cannot be silently
  turned into a ranking.
* **Provenance is attached by code, never by the model.** The model sees the
  poles and the quotes and returns a coordinate and its reasoning. ``person``,
  ``axis`` and ``claim_ids`` come from the call site, exactly as in
  ``extract.to_claims``.
* **Absence is never a zero.** A person with no claims on an axis is not
  placed at all. Our coverage is uneven by construction — one candidate has a
  56-page programme and three have no configured source — so a missing
  placement means we have no evidence, never that the candidate has no view.

Output carries ``n_claims`` so a placement built on one quote is visibly that.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date as Date
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .lint import check_archive_present
from .schema import Axis, Claim, Tier, llm_json_schema

# The two ends of each axis, in French to match the evidence being weighed.
# Written as descriptions of a stance, not of its quality: a reader who thinks
# one end is obviously correct is reading their own politics into the scale.
SPECTRA: dict[Axis, tuple[str, str]] = {
    Axis.REGULATION: (
        "déréglementation assumée : lever les contraintes, s'en remettre au marché",
        "encadrement contraignant : règles, interdictions, autorité de contrôle dotée de pouvoirs",
    ),
    Axis.SOUVERAINETE: (
        "ouverture assumée : recours aux fournisseurs et aux infrastructures étrangers",
        "autonomie nationale : maîtrise publique du calcul, du cloud et des données",
    ),
    Axis.ENVIRONNEMENT: (
        "déploiement d'abord : le coût environnemental n'est pas une contrainte structurante",
        "déploiement conditionné : consommation, implantation et récupération de chaleur encadrées",
    ),
    Axis.EMPLOI: (
        "adaptation par le marché : les transitions se règlent dans l'entreprise",
        "protection active : garanties publiques pour les métiers exposés",
    ),
    Axis.FORMATION: (
        "formation laissée aux acteurs existants, sans plan dédié",
        "effort public massif : école, université, filière d'ingénieurs, reconversion",
    ),
    Axis.SERVICES_PUBLICS: (
        "prudence : l'État n'automatise qu'à la marge",
        "déploiement volontariste de l'IA dans l'administration et les services publics",
    ),
    Axis.SURVEILLANCE_LIBERTES: (
        "usage sécuritaire assumé : reconnaissance, police, détection",
        "restriction stricte au nom des libertés et de la vie privée",
    ),
    Axis.SECURITE: (
        "réponse mutualisée : protection laissée aux opérateurs et à la coopération européenne",
        "dispositif national renforcé : cybersécurité des infrastructures critiques, lutte contre les ingérences",
    ),
    Axis.DEFENSE: (
        "retenue : priorité au civil, encadrement ou interdiction des systèmes d'armes autonomes",
        "montée en puissance : IA militaire, drones et systèmes autonomes, doctrine assumée",
    ),
    Axis.PEUR: (
        "risque relativisé : les dangers de l'IA tiennent à ses usages, pas à la technologie",
        "risque majeur : perte de contrôle ou danger existentiel, appel à ralentir ou à des garde-fous dédiés",
    ),
    Axis.FINANCEMENT: (
        "financement privé : rôle public limité à l'amorçage",
        "investissement public massif : budgets, commande publique, fonds dédiés",
    ),
}


class Reliability(StrEnum):
    """How well attested the evidence behind a placement is.

    Derived from the sources by :func:`reliability`, never returned by the
    model — the same rule that keeps ``person`` and ``tier`` out of
    ``ExtractedClaim``. It is ordinal, not a weighted number: each level is a
    stated rule a reader can check against the claims, and the caveats that
    demoted a placement are recorded beside it.
    """

    ATTESTED = "attested"
    """The person's own words, confirmed by an editor, dated, and corroborated
    by more than one source."""

    SOURCED = "sourced"
    """Dated and captured, from more than one source, but the tier is still the
    source's declared default — nobody has confirmed whose words these are."""

    THIN = "thin"
    """One source only, or an undated quote, or a missing capture. Readable as
    a lead, not as a settled position."""


def reliability(claims: list[Claim]) -> tuple[Reliability, list[str]]:
    """The level and the caveats that produced it, from the sources alone.

    The weakest link governs: a placement is only as attested as its least
    attested quote. ``tier_confirmed`` is False for almost everything by
    design — a party site cannot tell its own communiqué from the candidate's
    speech — so an unconfirmed tier caps a placement at ``sourced`` rather
    than marking it defective.
    """
    caveats = []
    if len({c.source_url for c in claims}) < 2:
        caveats.append("single source")
    if any(c.date is None for c in claims):
        caveats.append("undated quote")
    if any(check_archive_present(c) for c in claims):
        caveats.append("no usable capture")

    unconfirmed = []
    if any(c.tier != Tier.OWN_WORDS for c in claims):
        unconfirmed.append("not the person's own words")
    if any(not c.tier_confirmed for c in claims):
        unconfirmed.append("tier unconfirmed")

    if caveats:
        return Reliability.THIN, caveats + unconfirmed
    if unconfirmed:
        return Reliability.SOURCED, unconfirmed
    return Reliability.ATTESTED, []


class Placement(BaseModel):
    """What the model returns. A coordinate and why — nothing else.

    ``extra="forbid"`` for the same reason ``ExtractedClaim`` uses it: the
    model must not be able to inject whose position this is.
    """

    model_config = ConfigDict(extra="forbid")

    # Literal rather than a bounded int: strict mode strips `minimum` and
    # `maximum` (see schema._UNSUPPORTED), so a range would be a description
    # the model could ignore. An enum is enforced by the provider.
    score: Literal[1, 2, 3, 4, 5] = Field(
        description="Where this person stands between the two poles, 1 at the first "
        "pole and 5 at the second. This is a position, not a mark: neither end is "
        "better than the other. Use 3 when the evidence genuinely sits between them."
    )
    rationale: str = Field(
        description="One or two French sentences naming which of the quoted positions "
        "put the person there. Describe the stance; never judge whether it is a good one."
    )


SYSTEM = """You place a French political figure on one axis of AI policy, for a research instrument of the ESSEC Metalab Institute.

You are given two poles and every position this person has been recorded stating on that axis. Return the coordinate between the poles that their recorded positions support.

## A coordinate is not a grade

1 is not worse than 5. Neither pole is the correct one. You are describing where someone stands, not how good their policy is. Never reward ambition, detail or feasibility — a brief position and a developed one can sit at the same coordinate.

## Weigh only what is quoted

Place the person on the evidence given and nothing else. Do not use what you know about their party, their other policies, or their reputation. If the quoted positions only support a narrow reading, say so in the rationale rather than filling the gap.

Their own words (tier 1) carry more weight than their party's (tier 2) where the two point in different directions.

## Axis

{axis}

- **1** — {low}
- **5** — {high}"""


def system_prompt(axis: Axis) -> str:
    low, high = SPECTRA[axis]
    return SYSTEM.format(axis=axis.value, low=low, high=high)


def user_prompt(person_name: str, claims: list[Claim]) -> str:
    lines = [f"Person: {person_name}", f"Recorded positions: {len(claims)}", ""]
    for c in sorted(claims, key=lambda c: (c.date or Date.min)):
        lines += [
            f"--- {c.date or 'date non précisée'} · tier {c.tier.value}",
            f"Quote: « {c.quote_fr} »",
            f"Position: {c.position_fr}",
            f"Context: {c.contexte_fr}",
            "",
        ]
    return "\n".join(lines)


def prompt_hash(axis: Axis) -> str:
    """Recorded with every placement, for the same reason extraction records
    its own: a changed prompt explains a changed answer as much as a changed
    model does."""
    return hashlib.sha256(system_prompt(axis).encode()).hexdigest()[:16]


class Score(BaseModel):
    """A placement plus the provenance the model never saw."""

    model_config = ConfigDict(extra="forbid")

    person: str
    axis: Axis
    score: Literal[1, 2, 3, 4, 5]
    rationale: str
    low: str
    high: str
    claim_ids: list[str] = Field(description="The claims this placement was built from.")
    source_urls: list[str] = Field(
        description="The distinct pages the evidence came from. Held here as well as "
        "on the claims so a placement can never be read without seeing how many "
        "independent sources stand behind it.")
    n_claims: int = Field(description="Read a placement built on one quote as one quote.")
    reliability: Reliability
    caveats: list[str] = Field(
        description="Exactly what held the reliability down, so the level is never "
        "a number a reader has to take on trust.")
    model: str
    prompt_hash: str
    scored_on: Date


def by_person_axis(claims: list[Claim]) -> dict[tuple[str, Axis], list[Claim]]:
    """Group claims into the cells a placement can be made for.

    Only cells that have evidence appear. A person with nothing on an axis is
    absent rather than present with a low score.
    """
    out: dict[tuple[str, Axis], list[Claim]] = {}
    for c in claims:
        out.setdefault((c.person, c.axis), []).append(c)
    return out


def trace(score: Score, claims: list[Claim]) -> tuple[list[Claim], list[str]]:
    """The evidence behind a placement, and any claim id that no longer exists.

    ``Claim.id`` is content-addressed — the SHA-256 of ``source_url`` and
    ``quote_fr`` — so a quote corrected at review gets a new id and the
    placement is left pointing at one that is gone. Missing ids are returned
    rather than quietly dropped: a coordinate whose evidence cannot be produced
    is not a finding, and re-running the placement is the fix.

    Deliberately not denormalised into :class:`Score`. Copying the source URLs
    into the record would make it self-contained, but a claim corrected or
    retracted afterwards would still show its old sources as current evidence.
    A dangling id that is detected beats a stale URL that is not.
    """
    by_id = {c.id: c for c in claims}
    found = [by_id[i] for i in score.claim_ids if i in by_id]
    missing = [i for i in score.claim_ids if i not in by_id]
    return found, missing


def place(person_name: str, axis: Axis, claims: list[Claim], client, model: str,
          *, scored_on: Date | None = None) -> Score | None:
    """Place one person on one axis. ``None`` if the model gave no usable answer.

    Raises if handed no claims. Every placement earns at least one source, so
    an empty list is a caller's mistake, not a person with no views — and
    failing loudly here is what stops it being recorded as a coordinate.
    """
    if not claims:
        raise ValueError(
            f"no claims for {person_name} on {axis.value}: a placement needs at least "
            "one source behind it, and absence of evidence is not a position")
    payload = {
        "model": model,
        "system": system_prompt(axis),
        "user": user_prompt(person_name, claims),
        "schema": llm_json_schema(Placement),
    }
    body = client.complete(payload)
    if body is None:
        return None
    try:
        placement = Placement.model_validate(body)
    except Exception:
        return None  # a malformed answer is dropped, never guessed at
    low, high = SPECTRA[axis]
    level, caveats = reliability(claims)
    return Score(
        person=claims[0].person,
        axis=axis,
        score=placement.score,
        rationale=placement.rationale,
        low=low,
        high=high,
        claim_ids=sorted(c.id for c in claims),
        source_urls=sorted({c.source_url for c in claims}),
        n_claims=len(claims),
        reliability=level,
        caveats=caveats,
        model=model,
        prompt_hash=prompt_hash(axis),
        scored_on=scored_on or Date.today(),
    )


def run(claims: list[Claim], people: dict[str, str], client, model: str,
        *, scored_on: Date | None = None) -> list[Score]:
    """Place every person on every axis they have evidence on."""
    out = []
    for (person, axis), group in sorted(by_person_axis(claims).items()):
        score = place(people.get(person, person), axis, group, client, model,
                      scored_on=scored_on)
        if score is not None:
            out.append(score)
    return out


def write(path: str | Path, scores: list[Score]) -> None:
    Path(path).write_text(
        json.dumps([s.model_dump(mode="json") for s in scores], ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    import argparse

    import yaml

    from .clients import PROVIDERS, SyncClient
    from .store import load_claims

    ap = argparse.ArgumentParser(
        description="Place candidates on the policy axes. Internal research output: "
                    "not rendered, and gitignored because this repository is public.")
    ap.add_argument("--claims", default="data/claims.json")
    ap.add_argument("--sources", default="sources.yaml")
    ap.add_argument("--out", default="data/scores.json")
    ap.add_argument("--provider", default="openai", choices=sorted(PROVIDERS),
                    help="which provider to send to; --model defaults to its own")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    args.model = args.model or PROVIDERS[args.provider].default_model

    cfg = yaml.safe_load(Path(args.sources).read_text(encoding="utf-8"))
    names = {p["slug"]: p["name"] for p in cfg["people"]}
    claims = load_claims(args.claims)
    scores = run(claims, names, SyncClient(provider=args.provider), args.model)
    write(args.out, scores)

    cells = len(by_person_axis(claims))
    print(f"{len(scores)} placements from {len(claims)} claims across {cells} cells "
          f"→ {args.out}\n")
    for s in scores:
        print(f"{s.person} · {s.axis.value} · {s.score}/5 · {s.reliability.value}")
        if s.caveats:
            print(f"  caveats: {', '.join(s.caveats)}")
        # Every placement prints the evidence under it: the whole claim to being
        # a research instrument rather than an opinion is that the sources are
        # one line away, never a join the reader has to write.
        found, missing = trace(s, claims)
        for c in found:
            print(f"  « {c.quote_fr[:64]}… »")
            print(f"     {c.date or 'date non précisée'} · tier {c.tier.value} · {c.citation_url()}")
            print(f"     archive {c.archive_url}")
        for cid in missing:
            print(f"  ⚠ {cid}: claim no longer exists — re-run this placement")
        print()
