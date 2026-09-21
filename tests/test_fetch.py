from datetime import date

import pytest

from observatoire.fetch import match_people, route, source_id, to_lead
from observatoire.schema import Document, Lead, Tier
from observatoire.store import Store

PEOPLE = [
    {"slug": "bruno-retailleau", "match": ["Retailleau"]},
    {"slug": "jean-luc-melenchon", "match": ["Mélenchon", "Melenchon"]},
    {"slug": "edouard-philippe", "match": ["Édouard Philippe", "Edouard Philippe"]},
]


def doc(tier, **over):
    base = dict(person="p", source_id="s", kind="rss", tier=tier,
                url="https://a.test/1", text="texte", title="Titre")
    return Document(**{**base, **over})


# --- tier routing: the documents/leads split is the core design decision ---

def test_press_is_demoted_to_a_lead():
    docs, leads = route([doc(Tier.PRESS)], [])
    assert docs == [] and len(leads) == 1
    assert "own words" in leads[0].reason


def test_own_words_and_party_stay_documents():
    docs, leads = route([doc(Tier.OWN_WORDS), doc(Tier.PARTY_OR_STAFF, url="https://a.test/2")], [])
    assert len(docs) == 2 and leads == []


def test_demotion_drops_the_body_but_keeps_the_receipt():
    lead = to_lead(doc(Tier.PRESS, date=date(2026, 7, 7)), "press")
    assert lead.url == "https://a.test/1" and lead.title == "Titre"
    assert lead.date == date(2026, 7, 7)
    assert not hasattr(lead, "text")


def test_existing_leads_are_preserved_through_routing():
    pre = Lead(person="p", source_id="s", title="T", url="https://b.test/1", reason="video")
    docs, leads = route([doc(Tier.PRESS, url="https://a.test/9")], [pre])
    assert len(leads) == 2 and pre in leads


def test_untitled_document_still_yields_a_usable_lead():
    assert to_lead(doc(Tier.PRESS, title=None), "press").title == "(untitled)"


# --- attribution for shared feeds -----------------------------------------

def test_matches_the_person_named():
    assert [p["slug"] for p in match_people("Bruno Retailleau et l'IA", PEOPLE)] == ["bruno-retailleau"]


def test_matches_several_people_in_one_article():
    got = {p["slug"] for p in match_people("Retailleau répond à Mélenchon", PEOPLE)}
    assert got == {"bruno-retailleau", "jean-luc-melenchon"}


def test_article_naming_nobody_is_dropped():
    assert match_people("Le marché du logement en Bretagne", PEOPLE) == []


def test_accent_variants_both_match():
    assert match_people("Melenchon propose", PEOPLE)
    assert match_people("Mélenchon propose", PEOPLE)


def test_a_bare_first_name_does_not_match():
    # "Philippe" is a common French first name; only the full name counts
    assert match_people("Philippe Martin, maire de Lyon", PEOPLE) == []
    assert match_people("Édouard Philippe, maire du Havre", PEOPLE)


def test_match_is_word_bounded():
    assert match_people("Les médias via cette initiative", PEOPLE) == []


def test_source_id_is_stable_and_distinct():
    p = {"slug": "x"}
    a = source_id(p, {"type": "rss", "url": "https://a.test/feed"})
    assert a == source_id(p, {"type": "rss", "url": "https://a.test/feed"})
    assert a != source_id(p, {"type": "rss", "url": "https://b.test/feed"})


# --- liveness: the nosdeputes.fr failure mode ------------------------------

@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def test_a_source_returning_nothing_three_times_is_dead(store):
    for _ in range(3):
        store.record_run("broken", fetched=0, kept=0)
    store.commit()
    assert store.dead_sources() == ["broken"]


def test_two_quiet_runs_are_not_yet_dead(store):
    for _ in range(2):
        store.record_run("quiet", fetched=0, kept=0)
    store.commit()
    assert store.dead_sources() == []


def test_a_healthy_feed_with_no_matches_is_not_dead(store):
    """The distinction that matters: numerama fetching 25 articles that name
    no candidate is working fine. Alerting on it would train people to ignore
    the alert."""
    for _ in range(5):
        store.record_run("tech-feed", fetched=25, kept=0)
    store.commit()
    assert store.dead_sources() == []


def test_recovery_clears_the_alert(store):
    for _ in range(3):
        store.record_run("flaky", fetched=0, kept=0)
    store.record_run("flaky", fetched=10, kept=2)
    store.commit()
    assert store.dead_sources() == []


# --- a blocked yt-dlp must not look like a quiet video ---------------------

def test_a_failing_ytdlp_raises_instead_of_returning_nothing(monkeypatch):
    """Measured 2026-09-21: from a GitHub runner YouTube answers caption
    requests with "Sign in to confirm you're not a bot" while the playlist
    listing still succeeds. Swallowing that made a blocked fetcher and a video
    with no AI content produce the same empty result."""
    import subprocess

    from observatoire import fetch

    def blocked(*a, **k):
        return subprocess.CompletedProcess(
            a[0], 1, stdout="", stderr="ERROR: [youtube] Sign in to confirm you're not a bot.")

    monkeypatch.setattr(subprocess, "run", blocked)
    with pytest.raises(RuntimeError, match="not a bot"):
        fetch._ytdlp(["--version"])


def test_a_successful_ytdlp_still_returns_its_output(monkeypatch):
    import subprocess

    from observatoire import fetch

    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="ok\n", stderr=""))
    assert fetch._ytdlp(["--version"]) == "ok\n"
