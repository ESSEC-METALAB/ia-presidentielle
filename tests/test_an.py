"""Assemblée nationale comptes rendus.

The first source that does not guess whose words it carries. Every other
fetcher infers the speaker from the page it came from; this one is told, by an
official record, with a stable actor id. These tests pin that difference.

The fixture reproduces the real markup, checked against
CRSANR5L17S2026O1N202 from the published archive on 2026-09-21.
"""
import io
import zipfile

import pytest

from observatoire.fetch import AN_SEANCE, _an_seances, fetch_an

SEANCE = """<?xml version='1.0' encoding='UTF-8'?>
<compteRendu xmlns="http://schemas.assemblee-nationale.fr/referentiel">
  <uid>CRSANR5L17S2026O1N202</uid>
  <metadonnees>
    <dateSeance>20260413213000000</dateSeance>
    <dateSeanceJour>lundi 13 avril 2026</dateSeanceJour>
  </metadonnees>
  <contenu>
    <paragraphe id_acteur="PA794354" roledebat="president">
      <orateurs><orateur><nom>Mme la présidente</nom></orateur></orateurs>
      <texte>La parole est à Mme Marine Le Pen.</texte>
    </paragraphe>
    <paragraphe id_acteur="PA720614">
      <orateurs><orateur><nom>Mme Marine Le Pen</nom></orateur></orateurs>
      <texte>Nous proposons un moratoire sur la reconnaissance faciale dans
      l'espace public.</texte>
    </paragraphe>
    <paragraphe id_acteur="PA720614">
      <orateurs><orateur><nom>Mme Marine Le Pen</nom></orateur></orateurs>
      <texte>L'amendement n<exposant>o</exposant> 12 le précise.</texte>
    </paragraphe>
    <paragraphe id_acteur="PA722190">
      <orateurs><orateur><nom>M. Gabriel Attal</nom></orateur></orateurs>
      <texte>Je ne partage pas cette analyse.</texte>
    </paragraphe>
    <paragraphe id_acteur="PA0">
      <orateurs><orateur><nom>M. Gabriel Attal</nom></orateur></orateurs>
      <texte>Attribution perdue par la source.</texte>
    </paragraphe>
  </contenu>
</compteRendu>
"""

OLDER = SEANCE.replace("CRSANR5L17S2026O1N202", "CRSANR5L17S2024O1N001") \
              .replace("20260413213000000", "20241015100000000") \
              .replace("lundi 13 avril 2026", "mardi 15 octobre 2024")


@pytest.fixture(autouse=True)
def downloads(monkeypatch):
    """Serve a small archive instead of the real 53 MB download, and count how
    many times it is asked for."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xml/compteRendu/N202.xml", SEANCE)
        z.writestr("xml/compteRendu/N001.xml", OLDER)
        z.writestr("xml/compteRendu/broken.xml", "<compteRendu><unclosed>")

    class Response:
        content = buf.getvalue()

        def raise_for_status(self):
            return None

    calls = []
    _an_seances.cache_clear()          # lru_cache would leak between tests
    monkeypatch.setattr("observatoire.fetch.httpx.get",
                        lambda *a, **k: (calls.append(1), Response())[1])
    yield calls
    _an_seances.cache_clear()


def fetch(acteur, slug="marine-le-pen", **over):
    return fetch_an({"acteur": acteur, "tier": "1", **over}, {"slug": slug}, "an:test")


# --- attribution is exact, not inferred ------------------------------------

def test_a_person_gets_only_their_own_words():
    docs, leads = fetch("PA720614")
    assert leads == []
    assert len(docs) == 2                      # two séances, both with her in
    assert "reconnaissance faciale" in docs[0].text
    assert "Je ne partage pas" not in docs[0].text


def test_the_chair_is_not_quoted_as_a_speaker():
    """Presiding produces "la parole est à Mme X" — procedure, not a position.
    It matters because a candidate can preside."""
    assert "La parole est à" not in fetch("PA720614")[0][0].text


def test_a_lost_attribution_is_dropped_rather_than_guessed():
    """The real archive carries a handful of PA0 paragraphs: the source itself
    does not know who spoke, so neither do we."""
    assert fetch("PA0")[0] == []


def test_a_person_who_did_not_speak_gets_nothing():
    assert fetch("PA999999")[0] == []


def test_every_turn_in_a_seance_lands_in_one_document():
    text = fetch("PA720614")[0][0].text
    assert "reconnaissance faciale" in text and "amendement" in text


def test_markup_inside_a_turn_is_flattened():
    """<exposant> marks the "o" of "n°". Dropping the tag but keeping the text
    is what makes the quote-in-source lint able to match later."""
    assert "amendement no 12" in fetch("PA720614")[0][0].text


# --- provenance -------------------------------------------------------------

def test_the_citation_url_is_the_published_seance():
    doc = fetch("PA720614")[0][0]
    assert doc.url == AN_SEANCE.format(legislature="17", uid="CRSANR5L17S2026O1N202")


def test_the_date_comes_from_the_record():
    """Never invented: the archive states it on every séance, so this source
    never exercises the nullable-date path."""
    assert str(fetch("PA720614")[0][0].date) == "2026-04-13"


def test_the_tier_is_confirmed_not_defaulted():
    """The record names the speaker, so no editor has to decide whose words
    these are. Every other source leaves this False."""
    assert fetch("PA720614")[0][0].tier_confirmed is True


def test_the_person_is_the_configured_slug():
    assert fetch("PA720614", slug="marine-le-pen")[0][0].person == "marine-le-pen"


# --- robustness -------------------------------------------------------------

def test_a_malformed_seance_does_not_lose_the_others():
    """The fixture includes an unparseable file. A bad séance is skipped, not
    guessed at, and must not take the archive down with it."""
    assert len(fetch("PA720614")[0]) == 2


def test_since_limits_the_backfill():
    docs = fetch("PA720614", since="2026-01-01")[0]
    assert [str(d.date) for d in docs] == ["2026-04-13"]


def test_the_archive_is_downloaded_once_for_many_people(downloads):
    """Four configured people must not mean four 53 MB downloads."""
    fetch("PA720614")
    fetch("PA722190", slug="gabriel-attal")
    assert len(downloads) == 1, "the parsed archive should be cached for the run"
