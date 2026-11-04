"""Dedup key, date parsing and alias matching."""

from datetime import date

import pytest

from observatoire.services.candidate_matcher import AliasMatcher
from observatoire.services.dates import parse_date_prefix
from observatoire.services.dedup import content_hash, text_similarity
from support import candidate


def test_layout_variants_of_one_text_share_a_dedup_key() -> None:
    original = "Le numérique  pour tous.\n\nDeuxième paragraphe."
    reflowed = "Le numérique pour tous. Deuxième paragraphe."

    assert content_hash(original) == content_hash(reflowed)


def test_different_wording_gets_a_different_dedup_key() -> None:
    assert content_hash("Le numérique pour tous.") != content_hash("Le numérique pour chacun.")


def test_similarity_ignores_case_punctuation_and_spacing() -> None:
    first = "L\u2019IA au service des Français : progrès, souveraineté, vigilance."
    second = "L \u2019 IA AU SERVICE DES FRANÇAIS — progrès souveraineté vigilance"

    assert text_similarity(first, second) == 1.0


def test_similarity_of_unrelated_texts_is_low() -> None:
    first = "Nous créerons une autorité de contrôle des algorithmes publics."
    second = "La retraite à soixante ans pour les carrières longues sera rétablie."

    assert text_similarity(first, second) < 0.1


def test_similarity_of_two_empty_texts_is_complete() -> None:
    assert text_similarity("", " … ") == 1.0


def test_similarity_of_very_short_texts_compares_their_words() -> None:
    assert text_similarity("Oui.", "oui") == 1.0
    assert text_similarity("Oui.", "Non.") == 0.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-18", date(2026, 9, 18)),
        ("20240101150000000", date(2024, 1, 1)),
        ("2026-09-18T10:00:00+02:00", date(2026, 9, 18)),
        ("2026-02-30", None),
        ("le 3 mars", None),
        ("", None),
        (None, None),
    ],
)
def test_date_parsing_refuses_to_guess(value: str | None, expected: date | None) -> None:
    assert parse_date_prefix(value) == expected


def test_aliases_match_whole_words_whatever_the_case() -> None:
    matcher = AliasMatcher([candidate(), candidate("dominique-temoin", "Dominique Témoin")])

    mentions = matcher.match("CAMILLE EXEMPLE répond à Camille Exemple ; Dominique Témoin se tait.")

    assert {(m.candidate_id, m.count) for m in mentions} == {
        ("camille-exemple", 2),
        ("dominique-temoin", 1),
    }


def test_an_alias_inside_a_longer_word_is_not_a_mention() -> None:
    matcher = AliasMatcher([candidate("x", "Exemple")])

    assert matcher.match("Un contre-Exemples, un Exemplaire.") == []
