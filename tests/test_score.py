"""Spectrum placement.

The properties worth pinning are the ones that keep an internal instrument from
becoming a published ranking: absence must never read as a zero, the model must
not be able to say whose position it placed, and the file must stay out of a
public repository.
"""
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from observatoire.schema import Axis, Claim, Tier, llm_json_schema
from observatoire.score import (
    SPECTRA,
    Placement,
    Reliability,
    Score,
    by_person_axis,
    place,
    reliability,
    run,
    system_prompt,
    trace,
)


def claim(person="jean-luc-melenchon", axis="souverainete", quote="un grand pôle public", **over):
    base = dict(
        axis=axis, claim_type="post", date=date(2026, 9, 14),
        quote_fr=quote,
        quote_gloss_en="a large public hub",
        position_fr="Propose la création d'un pôle public du numérique et de l'IA.",
        position_en="Proposes a public hub for digital and AI.",
        contexte_fr="Vise les infrastructures de calcul et de cloud.",
        contexte_en="Targets compute and cloud infrastructure.",
        person=person, party="LFI", tier=Tier.OWN_WORDS,
        source_url=f"https://lafranceinsoumise.fr/{quote[:6]}",
        archive_url="https://web.archive.org/web/20260918144520/https://a.test/1",
        last_verified=date(2026, 9, 18))
    return Claim(**{**base, **over})


GOOD = {"score": 4, "rationale": "Défend une maîtrise publique."}


class FakeClient:
    """Returns a fixed body, and remembers what it was asked. ``None`` is a
    real answer here — it is what the client returns for an unusable one."""

    def __init__(self, body=GOOD):
        self.body = body
        self.payloads = []

    def complete(self, payload):
        self.payloads.append(payload)
        return self.body


# --- absence is never a zero ----------------------------------------------

def test_a_person_with_no_claims_on_an_axis_is_not_placed():
    """Our coverage is uneven by construction. A candidate with no configured
    source must not come out at the bottom of a scale."""
    cells = by_person_axis([claim()])
    assert list(cells) == [("jean-luc-melenchon", Axis.SOUVERAINETE)]
    assert ("jordan-bardella", Axis.SOUVERAINETE) not in cells


def test_no_claims_produces_no_placements_at_all():
    client = FakeClient()
    assert run([], {}, client, "m") == []
    assert client.payloads == []          # nothing was even asked


# --- the model never reports provenance -----------------------------------

def test_the_model_cannot_say_whose_position_it_placed():
    with pytest.raises(ValidationError):
        Placement.model_validate(
            {"score": 4, "rationale": "x", "person": "marine-le-pen"})


def test_provenance_comes_from_the_claims_not_the_answer():
    c = claim()
    score = place("Jean-Luc Mélenchon", Axis.SOUVERAINETE, [c], FakeClient(), "m")
    assert score.person == c.person
    assert score.claim_ids == [c.id]
    assert score.n_claims == 1


def test_a_malformed_answer_is_dropped_never_guessed_at():
    assert place("X", Axis.SOUVERAINETE, [claim()], FakeClient({"score": 9}), "m") is None
    assert place("X", Axis.SOUVERAINETE, [claim()], FakeClient(None), "m") is None


# --- every placement earns at least one source ----------------------------

def test_a_placement_with_no_source_is_refused_not_produced():
    with pytest.raises(ValueError, match="at least one source"):
        place("Nobody", Axis.SOUVERAINETE, [], FakeClient(), "m")


def test_every_placement_carries_the_pages_its_evidence_came_from():
    a = claim(quote="un grand pôle public")
    b = claim(quote="qui possédera les infrastructures")
    score = place("Jean-Luc Mélenchon", Axis.SOUVERAINETE, [a, b], FakeClient(), "m")
    assert score.source_urls == sorted({a.source_url, b.source_url})
    assert len(score.source_urls) == 2


def test_a_placement_traces_back_to_its_quotes():
    c = claim()
    score = place("Jean-Luc Mélenchon", Axis.SOUVERAINETE, [c], FakeClient(), "m")
    found, missing = trace(score, [c])
    assert [x.id for x in found] == [c.id] and missing == []
    assert found[0].citation_url() and found[0].archive_url


def test_a_corrected_quote_leaves_a_detectable_dangling_reference():
    """Claim.id is the hash of source_url and quote_fr, so an editor fixing a
    typo changes it. The placement must report that, not silently show fewer
    sources than it was built on."""
    c = claim()
    score = place("Jean-Luc Mélenchon", Axis.SOUVERAINETE, [c], FakeClient(), "m")
    corrected = c.model_copy(update={"quote_fr": c.quote_fr + " corrigé"})
    found, missing = trace(score, [corrected])
    assert found == [] and missing == [c.id]


# --- reliability is derived from the sources, never from the model ---------

def test_reliability_is_not_a_field_the_model_can_set():
    with pytest.raises(ValidationError):
        Placement.model_validate({"score": 4, "rationale": "x", "reliability": "attested"})


def test_one_source_is_thin_however_good_the_quote_is():
    level, caveats = reliability([claim(tier=Tier.OWN_WORDS, tier_confirmed=True)])
    assert level is Reliability.THIN
    assert "single source" in caveats


def test_an_undated_quote_is_thin():
    level, caveats = reliability([
        claim(quote="un grand pôle public", date=None),
        claim(quote="qui possédera les infrastructures"),
    ])
    assert level is Reliability.THIN
    assert "undated quote" in caveats


def test_an_unconfirmed_tier_caps_at_sourced_rather_than_marking_a_defect():
    """tier_confirmed is False for almost everything by design — a party site
    cannot tell its own communiqué from the candidate's speech."""
    level, caveats = reliability([
        claim(quote="un grand pôle public", tier=Tier.OWN_WORDS, tier_confirmed=False),
        claim(quote="qui possédera les infra", tier=Tier.OWN_WORDS, tier_confirmed=False),
    ])
    assert level is Reliability.SOURCED
    assert caveats == ["tier unconfirmed"]


def test_attested_needs_own_words_confirmed_dated_and_corroborated():
    level, caveats = reliability([
        claim(quote="un grand pôle public", tier=Tier.OWN_WORDS, tier_confirmed=True),
        claim(quote="qui possédera les infra", tier=Tier.OWN_WORDS, tier_confirmed=True),
    ])
    assert level is Reliability.ATTESTED
    assert caveats == []


def test_the_level_always_names_what_held_it_down():
    """The point of an ordinal over a weighted number: nothing is taken on trust."""
    for claims in ([claim()], [claim(date=None)], [claim(tier=Tier.PARTY_OR_STAFF)]):
        level, caveats = reliability(claims)
        assert level is not Reliability.ATTESTED
        assert caveats, f"{level} with no stated reason"


# --- the scale is enforced by the provider, not by a description ----------

def test_the_scale_survives_strict_mode_stripping():
    """`minimum`/`maximum` are stripped for strict mode, so the 1-5 bound has
    to be an enum or it would be advice the model could ignore."""
    schema = llm_json_schema(Placement)
    assert schema["properties"]["score"]["enum"] == [1, 2, 3, 4, 5]
    assert "$ref" not in json.dumps(schema)
    assert "minimum" not in json.dumps(schema)


def test_every_axis_has_both_poles():
    assert set(SPECTRA) == set(Axis)
    for axis in Axis:
        low, high = SPECTRA[axis]
        assert low and high and low != high
        assert low in system_prompt(axis) and high in system_prompt(axis)


def test_the_prompt_says_a_coordinate_is_not_a_grade():
    sp = system_prompt(Axis.SOUVERAINETE)
    assert "not a grade" in sp
    assert "1 is not worse than 5" in sp


# --- it must not reach the public repository ------------------------------

def test_scores_are_gitignored_because_this_repository_is_public():
    """The morning job runs `git add -A data/`. Without the ignore rule it
    would commit a ranking of named candidates by itself.

    Checks the entry rather than asking git to match it: the path is written
    out literally, and what this guards against is the line being removed.
    """
    ignored = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "data/scores.json" in ignored.split()


def test_a_score_round_trips_through_json():
    """Same constraint as Claim: no computed fields, because extra='forbid'
    would reject them on read-back."""
    score = place("Jean-Luc Mélenchon", Axis.SOUVERAINETE, [claim()], FakeClient(), "m")
    assert Score.model_validate(json.loads(score.model_dump_json())) == score
