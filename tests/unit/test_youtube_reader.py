"""The YouTube channel reader, on fictional API and Apify answers served by a mock transport."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from observatoire.adapters.sources.apify_client import ApifyClient
from observatoire.adapters.sources.youtube_reader import (
    SetAside,
    YoutubeApi,
    YoutubeReader,
    containment,
    excerpt,
    seconds_of,
    video_id,
)
from observatoire.domain.errors import AnnotationUnavailableError, SourceUnavailableError
from observatoire.domain.models import Source, SpeechVerdict, TrustLevel
from support import FrozenClock

SPEECH = "Mes chers amis, nous ferons de la France une puissance de l'IA. " * 20


def _source(**options: str) -> Source:
    return Source(
        id="camille-exemple/youtube/chaine",
        candidate_id="camille-exemple",
        kind="youtube",
        url="https://www.youtube.com/@camille",
        trust_level=TrustLevel.OWN_WORDS,
        label="Camille Exemple sur YouTube",
        max_items=50,
        options={"channel": "UC" + "x" * 22, **options},
    )


def _video(vid: str, title: str, minutes: int = 30, day: str = "2026-09-20") -> dict[str, Any]:
    return {
        "id": vid,
        "snippet": {
            "title": title,
            "description": "",
            "publishedAt": f"{day}T18:00:00Z",
            "liveBroadcastContent": "none",
        },
        "contentDetails": {"duration": f"PT{minutes}M"},
    }


class _Check:
    def __init__(self, verdicts: dict[str, SpeechVerdict | Exception]) -> None:
        self.verdicts = verdicts
        self.asked: list[str] = []

    def check(self, speaker: str, title: str, transcript: str) -> SpeechVerdict:
        self.asked.append(title)
        verdict = self.verdicts.get(
            title, SpeechVerdict(single_speaker=True, speaker_is_person=True, reason="discours")
        )
        if isinstance(verdict, Exception):
            raise verdict
        return verdict


def _api_answer(request: httpx.Request, videos: list[dict[str, Any]]) -> httpx.Response:
    if "playlistItems" in str(request.url):
        items = [
            {
                "contentDetails": {
                    "videoId": v["id"],
                    "videoPublishedAt": v["snippet"]["publishedAt"],
                }
            }
            for v in videos
        ]
        return httpx.Response(200, json={"items": items})
    wanted = request.url.params["id"].split(",")
    return httpx.Response(200, json={"items": [v for v in videos if v["id"] in wanted]})


def _primary_items(
    starts: list[dict[str, str]], transcripts: dict[str, str], blocked: bool
) -> list[dict[str, Any]]:
    if blocked:
        return [
            {"url": u["url"], "error": "human verification", "error_code": "BOT_DETECTION"}
            for u in starts
        ]
    return [
        {"metadata": {"url": u["url"]}, "language": "fr", "transcript_text": transcripts[vid]}
        for u in starts
        if (vid := video_id(u["url"]) or "") in transcripts
    ]


def _fallback_items(url: str, fallback: dict[str, str]) -> list[dict[str, Any]]:
    text = fallback.get(video_id(url) or "")
    return [{"url": url, "language": "fr", "transcript_text": text}] if text else []


def _reader(
    videos: list[dict[str, Any]],
    transcripts: dict[str, str],
    *,
    asked: list[dict[str, Any]] | None = None,
    check: _Check | None = None,
    known_urls: tuple[str, ...] = (),
    stored: dict[str, list[str]] | None = None,
    set_aside: SetAside | None = None,
    lookback_days: int | None = None,
    fallback: dict[str, str] | None = None,
    blocked: bool = False,
) -> YoutubeReader:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.googleapis.com":
            return _api_answer(request, videos)
        body = json.loads(request.content)
        if "youtube_url" in body:  # the fallback actor, one video per run
            return httpx.Response(201, json=_fallback_items(body["youtube_url"], fallback or {}))
        if asked is not None:
            asked.append(body)
        return httpx.Response(201, json=_primary_items(body["startUrls"], transcripts, blocked))

    http = httpx.Client(transport=httpx.MockTransport(handle))
    return YoutubeReader(
        YoutubeApi(http, "key"),
        ApifyClient(http, "secret", max_charge_usd=0.5, timeout_seconds=60),
        FrozenClock(),
        speakers={"camille-exemple": "Camille Exemple"},
        daily_max_items=5,
        lookback_days=lookback_days,
        min_minutes=5,
        skip_titles=(r"\bentretien", r"\binvit[ée]"),
        skip_titles_only=(r"\bface [àa]\b",),
        known_urls=known_urls,
        stored_texts=stored,
        speech_check=check,
        set_aside=set_aside,
        workers=2,
        retry_seconds=0,
    )


def test_a_speech_becomes_a_document_with_its_date_and_title() -> None:
    reader = _reader([_video("aaaaaaaaaaa", "Discours à Lyon")], {"aaaaaaaaaaa": SPEECH})

    (document,) = reader.fetch(_source(), since=date(2026, 7, 1))

    assert document.url == "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    assert document.title == "Discours à Lyon"
    assert document.published_on == date(2026, 9, 20)
    assert document.text == SPEECH.strip()


def test_the_free_filters_choose_what_is_paid_for() -> None:
    asked: list[dict[str, Any]] = []
    videos = [
        _video("aaaaaaaaaaa", "Discours à Lyon"),
        _video("bbbbbbbbbbb", "Entretien sur France Inter"),
        _video("ccccccccccc", "Un extrait", minutes=2),
        _video("ddddddddddd", "Meeting à Lille"),
        _video("eeeeeeeeeee", "Meeting d'avant la fenêtre", day="2026-06-20"),
    ]
    reader = _reader(
        videos, {}, asked=asked, known_urls=("https://www.youtube.com/watch?v=ddddddddddd",)
    )

    screened = {s.video.id: s.reason for s in reader.screen(_source(), since=date(2026, 7, 1))}
    reader.fetch(_source(), since=date(2026, 7, 1))

    assert screened == {
        "aaaaaaaaaaa": None,
        "bbbbbbbbbbb": "interview ou débat (titre)",
        "ccccccccccc": "moins de 5 min",
        "ddddddddddd": "déjà collectée",
    }
    assert [u["url"] for u in asked[0]["startUrls"]] == [
        "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    ]


def test_on_another_channel_the_title_must_name_the_candidate() -> None:
    videos = [
        _video("aaaaaaaaaaa", "Discours de Camille Exemple"),
        _video("bbbbbbbbbbb", "Discours d'un autre"),
    ]
    reader = _reader(videos, {"aaaaaaaaaaa": SPEECH, "bbbbbbbbbbb": SPEECH})

    documents = reader.fetch(_source(match="Exemple"), since=None)

    assert [d.title for d in documents] == ["Discours de Camille Exemple"]


def test_nothing_to_transcribe_costs_no_apify_run() -> None:
    asked: list[dict[str, Any]] = []
    reader = _reader([_video("bbbbbbbbbbb", "Entretien")], {}, asked=asked)

    assert reader.fetch(_source(), since=None) == []
    assert asked == []


def test_an_exchange_is_set_aside_and_never_transcribed_again(tmp_path: Path) -> None:
    store = tmp_path / "set-aside.json"
    check = _Check(
        {
            "Grand oral": SpeechVerdict(
                single_speaker=False, speaker_is_person=True, reason="entretien avec un journaliste"
            )
        }
    )
    videos = [_video("aaaaaaaaaaa", "Grand oral"), _video("bbbbbbbbbbb", "Discours à Lyon")]
    reader = _reader(
        videos,
        {"aaaaaaaaaaa": "Bonjour, merci d'être avec nous. " * 9, "bbbbbbbbbbb": SPEECH},
        check=check,
        set_aside=SetAside(store),
    )

    documents = reader.fetch(_source(), since=None)
    again = _reader(videos, {}, set_aside=SetAside(store)).screen(_source(), since=None)

    assert [d.title for d in documents] == ["Discours à Lyon"]
    assert json.loads(store.read_text(encoding="utf-8")) == {
        "aaaaaaaaaaa": "entretien avec un journaliste"
    }
    assert {s.video.id: s.reason for s in again}["aaaaaaaaaaa"] == "déjà écartée"


def test_a_check_that_cannot_answer_keeps_the_video_out_without_remembering_it(
    tmp_path: Path,
) -> None:
    store = tmp_path / "set-aside.json"
    check = _Check({"Discours à Lyon": AnnotationUnavailableError("timeout")})
    reader = _reader(
        [_video("aaaaaaaaaaa", "Discours à Lyon")],
        {"aaaaaaaaaaa": SPEECH},
        check=check,
        set_aside=SetAside(store),
    )

    assert reader.fetch(_source(), since=None) == []
    assert not store.exists()


def test_an_extract_of_a_kept_speech_is_set_aside() -> None:
    clip = " ".join(SPEECH.split()[:60])
    reader = _reader(
        [_video("aaaaaaaaaaa", "Le meilleur moment")],
        {"aaaaaaaaaaa": clip},
        stored={"camille-exemple": [SPEECH]},
    )

    assert reader.fetch(_source(), since=None) == []


def test_a_daily_run_transcribes_at_most_daily_max_items() -> None:
    asked: list[dict[str, Any]] = []
    videos = [_video(f"{i:011d}", f"Discours {i}", day="2026-10-03") for i in range(8)]
    reader = _reader(videos, {}, asked=asked, lookback_days=3)

    reader.fetch(_source(), since=date(2026, 7, 1))

    assert len(asked[0]["startUrls"]) == 5


def test_a_channel_without_its_uc_id_is_a_configuration_error() -> None:
    source = _source().model_copy(update={"options": {}})

    with pytest.raises(SourceUnavailableError):
        _reader([], {}).fetch(source, since=None)


def test_helpers() -> None:
    assert seconds_of("PT1H2M3S") == 3723
    assert seconds_of("P1DT1S") == 86401
    assert video_id("https://youtu.be/aaaaaaaaaaa") == "aaaaaaaaaaa"
    assert containment("a b c d e f g h", "z a b c d e f g h y") == 1.0
    assert excerpt("x" * 10) == "x" * 10
    assert "[…]" in excerpt("x" * 5000)


def test_the_description_names_the_candidate_and_face_a_counts_in_the_title_only() -> None:
    named = _video("aaaaaaaaaaa", "Ouverture des journées d'été")
    named["snippet"]["description"] = "Le discours de Camille Exemple. Face à la crise, agir."
    show = _video("bbbbbbbbbbb", "Face à BFM : Camille Exemple")
    reader = _reader([named, show], {})

    screened = {s.video.id: s.reason for s in reader.screen(_source(match="Exemple"), since=None)}

    assert screened == {"aaaaaaaaaaa": None, "bbbbbbbbbbb": "interview ou débat (titre)"}


def test_videos_the_cheaper_actor_cannot_read_go_to_the_fallback() -> None:
    videos = [_video("aaaaaaaaaaa", "Discours à Lyon"), _video("bbbbbbbbbbb", "Meeting à Lille")]
    reader = _reader(videos, {}, blocked=True, fallback={"bbbbbbbbbbb": SPEECH})

    (document,) = reader.fetch(_source(), since=None)

    assert document.title == "Meeting à Lille"


def test_no_transcript_from_either_actor_is_a_failure_not_an_empty_day() -> None:
    reader = _reader([_video("aaaaaaaaaaa", "Discours à Lyon")], {}, blocked=True)

    with pytest.raises(SourceUnavailableError, match="BOT_DETECTION"):
        reader.fetch(_source(), since=None)


def test_a_passing_check_error_is_retried() -> None:
    class Flaky(_Check):
        def check(self, speaker: str, title: str, transcript: str) -> SpeechVerdict:
            self.asked.append(title)
            if len(self.asked) == 1:
                raise AnnotationUnavailableError("mistral: HTTP 520")
            return SpeechVerdict(single_speaker=True, speaker_is_person=True, reason="discours")

    check = Flaky({})
    reader = _reader(
        [_video("aaaaaaaaaaa", "Discours à Lyon")], {"aaaaaaaaaaa": SPEECH}, check=check
    )

    assert len(reader.fetch(_source(), since=None)) == 1
    assert check.asked == ["Discours à Lyon", "Discours à Lyon"]
