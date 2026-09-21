"""The claims file is the published record and the thing an editor reviews.

It is not a database export: it is read by a human in a pull-request diff, so
these tests pin the properties that make it readable, not just correct.
"""
from datetime import date

from observatoire.schema import Claim, Tier
from observatoire.store import export_claims, load_claims, merge_claims

BASE = dict(
    axis="souverainete", claim_type="discours", date=date(2026, 7, 7),
    quote_fr="l'IA sera la souveraineté même",
    quote_gloss_en="AI will be sovereignty itself",
    position_fr="Place l'IA au rang d'enjeu de souveraineté.",
    position_en="Frames AI as a sovereignty question.",
    contexte_fr="Analogie avec le nucléaire.", contexte_en="A nuclear analogy.",
    party="LR", tier=Tier.OWN_WORDS, last_verified=date(2026, 9, 18),
)


def claim(person="bruno-retailleau", url="https://republicains.fr/a", **over):
    return Claim(**{**BASE, "person": person, "source_url": url, **over})


# --- the round trip -------------------------------------------------------

def test_a_claim_survives_the_round_trip(tmp_path):
    """The canary for a ``computed_field`` creeping onto Claim.

    Pydantic serialises a computed field, and ``extra="forbid"`` then rejects
    it on read-back — so the export would write a file it cannot itself load.
    ``Claim.id`` is a plain property for exactly this reason.
    """
    path = tmp_path / "claims.json"
    original = [claim(), claim(person="olivier-faure", url="https://parti-socialiste.fr/b")]
    export_claims(path, original)
    assert load_claims(path) == original


def test_a_claim_with_no_date_exports(tmp_path):
    """A source that carries no date gets none. The export must not choke on
    it, and must not sort it by inventing one."""
    path = tmp_path / "claims.json"
    export_claims(path, [claim(date=None)])
    assert load_claims(path)[0].date is None


# --- what makes the diff reviewable ---------------------------------------

def test_claims_are_grouped_by_person_oldest_first(tmp_path):
    path = tmp_path / "claims.json"
    export_claims(path, [
        claim(person="olivier-faure", url="https://parti-socialiste.fr/b"),
        claim(date=date(2026, 8, 1), url="https://republicains.fr/c"),
        claim(date=date(2026, 7, 7)),
    ])
    out = load_claims(path)
    assert [c.person for c in out] == ["bruno-retailleau", "bruno-retailleau", "olivier-faure"]
    assert [c.date for c in out[:2]] == [date(2026, 7, 7), date(2026, 8, 1)]


def test_the_export_is_stable_across_runs(tmp_path):
    """Input order must not move lines. Otherwise every run produces a diff
    that looks like an edit and reviewing it means reading the whole file."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    claims = [claim(), claim(person="olivier-faure", url="https://parti-socialiste.fr/b")]
    export_claims(a, claims)
    export_claims(b, list(reversed(claims)))
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


# --- merging must not undo the editor ------------------------------------

def test_a_new_claim_is_added(tmp_path):
    path = tmp_path / "claims.json"
    export_claims(path, [claim()])
    assert merge_claims(path, [claim(url="https://republicains.fr/new")]) == 1
    assert len(load_claims(path)) == 2


def test_an_edited_claim_is_not_overwritten_by_the_pipeline(tmp_path):
    """The reviewed version wins. An editor corrects a contexte in the PR; the
    next morning's run must not quietly put the model's wording back."""
    path = tmp_path / "claims.json"
    export_claims(path, [claim(contexte_fr="Corrigé à la relecture.")])

    assert merge_claims(path, [claim()]) == 0
    assert load_claims(path)[0].contexte_fr == "Corrigé à la relecture."


def test_merging_into_a_file_that_does_not_exist_yet(tmp_path):
    path = tmp_path / "claims.json"
    assert merge_claims(path, [claim()]) == 1
    assert len(load_claims(path)) == 1


def test_french_is_readable_in_the_diff(tmp_path):
    """An editor checks a quote against the source by eye. ``\\u00e9`` defeats
    that, so the file is written as UTF-8, not escaped ASCII."""
    path = tmp_path / "claims.json"
    export_claims(path, [claim()])
    assert "souveraineté" in path.read_text(encoding="utf-8")
