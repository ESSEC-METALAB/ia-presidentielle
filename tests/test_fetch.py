from datetime import date

import pytest

from observatoire import fetch
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
    _, leads = route([doc(Tier.PRESS, url="https://a.test/9")], [pre])
    assert len(leads) == 2 and pre in leads


def test_untitled_document_still_yields_a_usable_lead():
    assert to_lead(doc(Tier.PRESS, title=None), "press").title == "(untitled)"


# --- feeds go through the same politeness as pages ---------------------------

def test_a_feed_is_requested_through_get_and_a_refusal_yields_nothing(monkeypatch):
    # `get` carries the timeout, the user agent and the robots.txt check. A
    # feed parsed straight from its URL had none of the three.
    asked = []
    monkeypatch.setattr(fetch, "get", lambda url, timeout=30.0: asked.append(url))
    assert fetch.fetch_rss({"url": "https://a.test/feed", "tier": "2"}, {"slug": "p"}, "s") == ([], [])
    assert asked == ["https://a.test/feed"]


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


# --- video: one fetcher for every site yt-dlp can list ---------------------

VIDEO_SRC = {"type": "video", "url": "https://videos.test/chaine", "tier": "1", "max": 2}
PERSON = {"slug": "bruno-retailleau"}


def test_a_multi_speaker_video_becomes_a_lead_at_the_url_the_site_reports(monkeypatch):
    """No URL is rebuilt from an id: that only ever worked for one site."""
    monkeypatch.setattr(fetch, "_ytdlp", lambda args: (
        "https://videos.test/video/x1\t20261105\tRetailleau face aux lecteurs\n"))
    docs, leads = fetch.fetch_video({**VIDEO_SRC, "speakers": "multi"}, PERSON, "s")
    assert docs == []
    assert [(x.url, x.title, x.date) for x in leads] == [
        ("https://videos.test/video/x1", "Retailleau face aux lecteurs", date(2026, 11, 5))]


def test_a_listing_without_titles_is_completed_from_the_video_itself(monkeypatch):
    """Measured 2026-11-12: a Dailymotion channel lists ids and nothing else,
    and a lead titled "NA" can be neither read nor matched to a person."""
    def ytdlp(args):
        if "--flat-playlist" in args:
            return "https://videos.test/video/x1\tNA\tNA\n"
        assert args[-1] == "https://videos.test/video/x1"
        return "https://videos.test/video/x1\t20261112\tLe vrai titre\n"

    monkeypatch.setattr(fetch, "_ytdlp", ytdlp)
    _, leads = fetch.fetch_video({**VIDEO_SRC, "speakers": "multi"}, PERSON, "s")
    assert (leads[0].title, leads[0].date) == ("Le vrai titre", date(2026, 11, 12))


def test_titles_are_asked_for_in_french_on_every_lookup(monkeypatch):
    """Measured 2026-11-12: without it YouTube machine-translates titles for
    the client, so a BFMTV title came back as "Gabriel Attal, Renaissance
    presidential candidate, speaks from..." — not what the channel published."""
    calls = []

    def ytdlp(args):
        calls.append(args)
        if "--flat-playlist" in args:
            return "https://videos.test/video/x1\tNA\tNA\n"
        return "https://videos.test/video/x1\t20261112\tLe vrai titre\n"

    monkeypatch.setattr(fetch, "_ytdlp", ytdlp)
    fetch.fetch_video({**VIDEO_SRC, "speakers": "multi"}, PERSON, "s")
    assert len(calls) == 2
    assert all("youtube:lang=fr" in args for args in calls)


def test_a_single_speaker_video_becomes_a_document_with_its_cues(monkeypatch):
    from pathlib import Path

    from test_transcript import VTT

    def ytdlp(args):
        if "--flat-playlist" in args:
            return "https://videos.test/video/x1\t20261105\tDiscours\n"
        out = args[args.index("-o") + 1]
        Path(out.replace("%(id)s.%(ext)s", "x1.fr.vtt")).write_text(VTT, encoding="utf-8")
        return ""

    monkeypatch.setattr(fetch, "_ytdlp", ytdlp)
    docs, leads = fetch.fetch_video({**VIDEO_SRC, "speakers": "single"}, PERSON, "s")
    assert leads == []
    assert (docs[0].url, docs[0].kind) == ("https://videos.test/video/x1", "video")
    assert docs[0].cues[0].t == 10 and "puissance de calcul" in docs[0].text


# --- a shared item naming two people belongs to both ------------------------

def test_a_shared_lead_naming_two_people_is_kept_for_each(tmp_path, monkeypatch):
    """Measured 2026-11-12: 211 leads were kept across 17 channels but 201
    stored — the leads table was keyed by URL alone, so a debate naming two
    candidates was filed under whichever was matched last. Coverage per
    candidate is what the site states; losing one silently skews it."""
    import yaml

    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({
        "people": [{"slug": s, "match": m, "sources": []} for s, m in
                   (("marine-le-pen", ["Marine Le Pen"]), ("jean-luc-melenchon", ["Mélenchon"]))],
        "shared": [{"type": "video", "url": "https://videos.test/chaine", "tier": "3",
                    "speakers": "multi"}],
    }, allow_unicode=True), encoding="utf-8")
    monkeypatch.setitem(fetch.FETCHERS, "video", lambda src, person, sid: ([], [Lead(
        person=person["slug"], source_id=sid, title="Duel Marine Le Pen - Mélenchon",
        url="https://videos.test/video/x1")]))
    store = Store(tmp_path / "t.db")
    fetch.run(sources, store, do_archive=False)
    assert sorted(lead.person for lead in store.leads()) == ["jean-luc-melenchon", "marine-le-pen"]
