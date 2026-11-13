from datetime import date

import pytest

from observatoire import transcribe
from observatoire.schema import Lead, Tier
from observatoire.store import Store
from observatoire.transcribe import Turn, dominant_speaker, to_document

PEOPLE = [
    {"slug": "gabriel-attal", "match": ["Attal"]},
    {"slug": "jean-luc-melenchon", "match": ["Mélenchon"]},
]

# A one-on-one interview: the guest (speaker 1) holds most of the talk time.
INTERVIEW = [
    Turn(0.0, 20.0, 0, "Bonjour, vous êtes candidat, que proposez-vous ?"),
    Turn(20.0, 70.0, 1, "Nous investirons dans l'intelligence artificielle française."),
    Turn(70.0, 80.0, 0, "Avec quel argent ?"),
    Turn(80.0, 120.0, 1, "Avec des data centers sur notre sol."),
]


def lead(title="Les 4 vérités - Gabriel Attal", person="gabriel-attal", **over):
    base = dict(person=person, source_id="shared:video:0d387a2e", title=title,
                url="https://www.youtube.com/watch?v=x1", publisher="Télématin",
                date=date(2026, 10, 23))
    return Lead(**{**base, **over})


# --- the attribution rule ----------------------------------------------------

def test_the_voice_holding_most_of_the_talk_time_is_dominant():
    assert dominant_speaker(INTERVIEW) == 1


def test_an_even_debate_has_no_dominant_voice():
    debate = [Turn(0, 60, 0, "a"), Turn(60, 120, 1, "b"), Turn(120, 180, 2, "c")]
    assert dominant_speaker(debate) is None


def test_silence_has_no_dominant_voice():
    assert dominant_speaker([]) is None


# --- the document --------------------------------------------------------------

def test_only_the_attributed_voice_reaches_the_document():
    """The journalist's questions must not become the candidate's words."""
    doc = to_document(lead(), INTERVIEW, 1)
    assert "Avec quel argent" not in doc.text
    assert [c.t for c in doc.cues] == [20, 80]
    assert doc.text.startswith("Nous investirons")


def test_a_broadcast_candidate_is_tier_one_but_unconfirmed():
    """Whose words, not who hosts — and a rule, not a record, named the speaker."""
    doc = to_document(lead(), INTERVIEW, 1)
    assert doc.tier == Tier.OWN_WORDS and doc.tier_confirmed is False
    assert (doc.kind, doc.person, doc.url) == ("video", "gabriel-attal", lead().url)


# --- the stage -----------------------------------------------------------------

@pytest.fixture
def stage(tmp_path, monkeypatch):
    """A store holding one video lead, with every download and model stubbed."""
    store = Store(tmp_path / "t.db")
    calls = {"audio": 0}

    def fake_audio(url):
        calls["audio"] += 1
        return None

    monkeypatch.setattr(transcribe, "captions", lambda url: [(0, "on parle d'intelligence artificielle")])
    monkeypatch.setattr(transcribe, "audio", fake_audio)
    monkeypatch.setattr(transcribe, "turns", lambda samples, cache, asr: INTERVIEW)
    return store, calls, tmp_path


def test_an_attributable_lead_becomes_a_document_once(stage):
    store, calls, tmp = stage
    store.add_lead(lead())
    first = transcribe.run(store, PEOPLE, tmp)
    second = transcribe.run(store, PEOPLE, tmp)
    assert (first.examined, first.promoted) == (1, 1)
    assert second.examined == 0 and calls["audio"] == 1
    assert [d.person for d in store.documents()] == ["gabriel-attal"]


def test_a_better_model_examines_the_same_lead_again(stage, monkeypatch):
    store, _, tmp = stage
    monkeypatch.setitem(transcribe.ASR, "small", transcribe.ASR["tiny"])
    store.add_lead(lead())
    transcribe.run(store, PEOPLE, tmp, asr="tiny")
    assert transcribe.run(store, PEOPLE, tmp, asr="small").examined == 1


def test_a_title_naming_two_candidates_stays_a_lead(stage):
    store, calls, tmp = stage
    store.add_lead(lead(title="Duel Attal - Mélenchon"))
    report = transcribe.run(store, PEOPLE, tmp)
    assert report.promoted == 0 and calls["audio"] == 0
    assert store.documents() == []


def test_captions_without_ai_cost_no_audio(stage, monkeypatch):
    store, calls, tmp = stage
    monkeypatch.setattr(transcribe, "captions", lambda url: [(0, "les retraites et le budget")])
    store.add_lead(lead())
    assert transcribe.run(store, PEOPLE, tmp).skipped["captions do not mention AI"] == 1
    assert calls["audio"] == 0


def test_a_failed_download_is_retried_tomorrow(stage, monkeypatch):
    store, _, tmp = stage

    def blocked(url):
        raise RuntimeError("yt-dlp exited 1: HTTP Error 403: Forbidden")

    monkeypatch.setattr(transcribe, "audio", blocked)
    store.add_lead(lead())
    assert "403" in transcribe.run(store, PEOPLE, tmp).errors[lead().url]
    assert transcribe.run(store, PEOPLE, tmp).examined == 1


def test_a_text_lead_is_not_a_video(stage):
    store, _, tmp = stage
    store.add_lead(lead(source_id="shared:rss:1a2b3c4d"))
    assert transcribe.run(store, PEOPLE, tmp).examined == 0


# --- the models ----------------------------------------------------------------

def test_a_model_that_does_not_match_its_pin_is_refused(tmp_path, monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(
        200, content=b"not the model", request=httpx.Request("GET", a[0])))
    with pytest.raises(RuntimeError, match="sha256"):
        transcribe.fetch_model(transcribe.EMBEDDING, tmp_path)
    assert not (tmp_path / transcribe.EMBEDDING.name).exists()
