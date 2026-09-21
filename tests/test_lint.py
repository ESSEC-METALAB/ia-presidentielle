from datetime import date

import pytest

from observatoire.lint import (
    check_archive_present,
    check_links,
    check_no_evaluative_language,
    check_quote_in_source,
    lint,
)
from observatoire.schema import Claim, Document, Tier

SOURCE = ("Bruno Retailleau propose d'instaurer un pourcentage de souveraineté "
          "applicable à tout logiciel ou équipement acquis par l'État.")


def document(text=SOURCE):
    return Document(person="bruno-retailleau", source_id="s", kind="pdf",
                    tier=Tier.OWN_WORDS, url="https://a.test/1", text=text)


def claim(**over):
    base = dict(
        axis="souverainete", claim_type="programme", date=date(2026, 7, 7),
        quote_fr="un pourcentage de souveraineté applicable à tout logiciel",
        quote_gloss_en="a sovereignty percentage applicable to any software",
        position_fr="Propose un seuil de souveraineté sur les logiciels de l'État.",
        position_en="Proposes a sovereignty threshold on state software.",
        contexte_fr="Vise les marchés publics ; aucun seuil chiffré n'est donné.",
        contexte_en="Targets public procurement; no numeric threshold is given.",
        person="bruno-retailleau", party="LR", tier=Tier.OWN_WORDS,
        source_url="https://a.test/1",
        archive_url="https://web.archive.org/web/20260918144520/https://a.test/1",
        last_verified=date(2026, 9, 18),
    )
    return Claim(**{**base, **over})


def test_a_clean_claim_passes_every_gate():
    assert lint([claim()], {"https://a.test/1": document()}) == []


# --- anti-fabrication -----------------------------------------------------

def test_invented_quote_is_caught():
    f = check_quote_in_source(claim(quote_fr="je promets deux cents milliards"), SOURCE)
    assert len(f) == 1 and f[0].gate == "quote-in-source"


def test_paraphrased_quote_is_caught():
    """A model that tidies the French breaks the evidence chain."""
    f = check_quote_in_source(claim(quote_fr="un pourcentage de souveraineté pour tout logiciel"), SOURCE)
    assert len(f) == 1


def test_surrounding_whitespace_is_tolerated():
    assert check_quote_in_source(
        claim(quote_fr="  un pourcentage de souveraineté applicable  "), SOURCE) == []


# --- neutrality, and its one exemption ------------------------------------

@pytest.mark.parametrize("field,text", [
    ("position_fr", "Une proposition ambitieuse de 23 milliards."),
    ("contexte_fr", "Un objectif parfaitement irréaliste."),
    ("position_en", "Proposes a bold investment plan."),
    ("contexte_en", "A remarkable shift in policy."),
])
def test_judgement_in_our_own_prose_is_caught(field, text):
    f = check_no_evaluative_language(claim(**{field: text}))
    assert f and f[0].gate == "neutrality"


def test_the_candidates_own_judgement_words_are_never_censored():
    """If he calls his own plan ambitious, that is his word and it is evidence.
    The neutrality gate applies to our prose, never to the quote."""
    c = claim(quote_fr="un plan ambitieux et audacieux pour la souveraineté",
              quote_gloss_en="an ambitious and bold plan for sovereignty")
    assert check_no_evaluative_language(c) == []


def test_describing_a_figure_is_not_judging_it():
    assert check_no_evaluative_language(
        claim(position_fr="Propose un investissement de 23 milliards d'euros.")) == []


# --- receipts -------------------------------------------------------------

def test_missing_snapshot_is_caught():
    f = check_archive_present(claim(archive_url=None))
    assert len(f) == 1 and f[0].gate == "archive"


def test_claim_with_no_source_document_is_caught():
    f = lint([claim()], {})
    assert len(f) == 1 and f[0].gate == "provenance"


def test_every_finding_names_the_claim():
    c = claim(quote_fr="inventé", archive_url=None, position_fr="Vraiment ambitieux.")
    findings = lint([c], {"https://a.test/1": document()})
    assert len(findings) == 3
    assert all(f.claim_id == c.id for f in findings)
    assert {f.gate for f in findings} == {"quote-in-source", "neutrality", "archive"}


# --- a receipt has to actually be a receipt ------------------------------

def test_a_real_capture_url_passes():
    assert check_archive_present(claim(
        archive_url="https://web.archive.org/web/20260918144520/https://a.test/1")) == []


@pytest.mark.parametrize("url", [
    # the dated-query form is a *request* for the nearest capture. Wayback
    # serves a "not archived" page with HTTP 200 when there is none, so this
    # proves nothing on its own.
    "https://web.archive.org/web/2026/https://a.test/1",
    "https://web.archive.org/x",
    "https://a.test/1",
    "https://archive.today/abc",
])
def test_anything_without_a_capture_timestamp_is_rejected(url):
    f = check_archive_present(claim(archive_url=url))
    assert len(f) == 1 and "proves nothing" in f[0].message


# --- link rot: reported, but fatal only when the evidence is unreachable ---


CAPTURE = "https://web.archive.org/web/20260918144520/https://a.test/1"


def test_a_live_source_produces_nothing():
    assert check_links([claim()], probe=lambda url: True) == []


def test_a_deleted_source_with_a_capture_warns_but_does_not_stop_publication():
    """A candidate deleting a page is the event the snapshot exists for. The
    reader can still check the quote, so failing the build would block
    publication over something nobody here controls."""
    found = check_links([claim(archive_url=CAPTURE)], probe=lambda url: False)
    assert len(found) == 1 and found[0].fatal is False
    assert "archived capture still does" in found[0].message


def test_a_deleted_source_with_no_capture_is_fatal():
    """No route to the evidence at all: the quote cannot be checked by anyone."""
    found = check_links([claim(archive_url=None)], probe=lambda url: False)
    assert len(found) == 1 and found[0].fatal is True
    assert "cannot be checked" in found[0].message


def test_a_dated_query_url_does_not_count_as_a_capture():
    """Wayback answers the dated-query form with HTTP 200 and a "not archived"
    page, so it proves nothing — the same trap check_archive_present exists for."""
    rotten = claim(archive_url="https://web.archive.org/web/2026/https://a.test/1")
    assert check_links([rotten], probe=lambda url: False)[0].fatal is True


def test_a_warning_says_so_when_printed():
    found = check_links([claim(archive_url=CAPTURE)], probe=lambda url: False)
    assert "(warning)" in str(found[0])
