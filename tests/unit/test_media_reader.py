"""The media channel reader, on fictional API and Apify answers served by a mock transport."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from observatoire.adapters.sources.apify_client import ApifyClient
from observatoire.adapters.sources.media_reader import MediaReader
from observatoire.adapters.sources.youtube_reader import (
    SetAside,
    TranscriptCache,
    VideoLedger,
    YoutubeApi,
    video_id,
)
from observatoire.config.registry import MediaChannel, MediaSettings, media_sources
from observatoire.domain.errors import AnnotationUnavailableError
from observatoire.domain.models import Source, SpeakingTurn
from support import FrozenClock, candidate

QUESTION = "Bonjour Camille Exemple, merci d'être avec nous. Que proposez-vous sur l'IA ?"
ANSWER = "Je propose une autorité de contrôle de l'intelligence artificielle " * 20


def _source() -> Source:
    (source,) = media_sources(
        MediaSettings(
            channels=(
                MediaChannel(
                    id="tele", name="Télé", channel="UC" + "t" * 22, url="https://tele.test"
                ),
            )
        ),
        [candidate(), candidate("dominique-autre", "Dominique Autre")][:1],
    )
    return source


def _video(vid: str, title: str, minutes: int = 25, day: str = "2026-10-20") -> dict[str, Any]:
    return {
        "id": vid,
        "snippet": {
            "title": title,
            "description": "",
            "publishedAt": f"{day}T08:00:00Z",
            "liveBroadcastContent": "none",
        },
        "contentDetails": {"duration": f"PT{minutes}M"},
    }


class _Turns:
    """Line 0 is the journalist's, the rest the candidate's, sure."""

    def __init__(self, error: bool = False) -> None:
        self.calls = 0
        self.error = error

    def attribute(self, speaker: str, title: str, lines: Sequence[str]) -> list[SpeakingTurn]:
        self.calls += 1
        if self.error:
            raise AnnotationUnavailableError("mistral: HTTP 500")
        return [
            SpeakingTurn(first=0, last=0, speaker="journalist", sure=True),
            SpeakingTurn(first=1, last=len(lines) - 1, speaker="candidate", sure=True),
        ]


def _reader(
    videos: list[dict[str, Any]],
    *,
    asked: list[dict[str, Any]] | None = None,
    attributor: _Turns | None = None,
    stored: dict[str, list[str]] | None = None,
    ledger: VideoLedger | None = None,
    set_aside: SetAside | None = None,
    cache: TranscriptCache | None = None,
) -> MediaReader:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.googleapis.com":
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
        body = json.loads(request.content)
        if asked is not None:
            asked.append(body)
        segments = [{"start": 0, "text": QUESTION}, {"start": 5, "text": ANSWER}]
        return httpx.Response(
            201,
            json=[
                {
                    "metadata": {"url": u["url"]},
                    "language": "fr",
                    "transcript_text": f"{QUESTION} {ANSWER}",
                    "transcript_json": segments,
                }
                for u in body["startUrls"]
                if video_id(u["url"])
            ],
        )

    http = httpx.Client(transport=httpx.MockTransport(handle))
    return MediaReader(
        YoutubeApi(http, "key"),
        ApifyClient(http, "secret", max_charge_usd=0.5, timeout_seconds=60),
        FrozenClock(),
        speakers={"camille-exemple": "Camille Exemple"},
        daily_max_items=3,
        lookback_days=None,
        min_minutes=8,
        keep_titles=(r"\binvit[ée]", r"\bdiscours\b"),
        skip_titles=(r"\b[ée]dito", r"\bd[ée]bat"),
        stored_texts=stored,
        attributor=_Turns() if attributor is None else attributor,
        set_aside=set_aside,
        ledger=ledger,
        cache=cache,
        retry_seconds=0,
    )


def test_only_the_candidates_answers_are_kept() -> None:
    reader = _reader([_video("aaaaaaaaaaa", "Camille Exemple invitée de la matinale")])

    (document,) = reader.fetch(_source(), since=None)

    assert "merci d'être avec nous" not in document.text
    assert document.text.startswith("Je propose une autorité")
    assert document.candidate_id == "camille-exemple"
    assert document.url == "https://www.youtube.com/watch?v=aaaaaaaaaaa"


def test_the_free_filters_keep_interviews_of_this_candidate_alone() -> None:
    videos = [
        _video("aaaaaaaaaaa", "Camille Exemple invitée de la matinale"),
        _video("bbbbbbbbbbb", "L'édito : Camille Exemple invitée partout"),
        _video("ccccccccccc", "Un invité parle de tout"),
        _video("ddddddddddd", "Camille Exemple en reportage"),
        _video("eeeeeeeeeee", "Camille Exemple invitée", minutes=3),
    ]

    reasons = {s.video.id: s.reason for s in _reader(videos).screen(_source(), since=None)}

    assert reasons == {
        "aaaaaaaaaaa": None,
        "bbbbbbbbbbb": "édito, débat ou analyse",
        "ccccccccccc": "ne nomme pas le candidat",
        "ddddddddddd": "n'annonce ni interview ni discours",
        "eeeeeeeeeee": "moins de 8 min",
    }


def test_the_same_programme_on_another_channel_is_not_paid_for_twice(tmp_path: Path) -> None:
    ledger = VideoLedger(tmp_path / "ledger.json")
    first = _reader(
        [_video("aaaaaaaaaaa", "Camille Exemple invitée de la matinale")], ledger=ledger
    )
    first.fetch(_source(), since=None)
    asked: list[dict[str, Any]] = []
    simulcast = _video("bbbbbbbbbbb", "La grande interview : Camille Exemple invitée", minutes=25)

    again = _reader([simulcast], asked=asked, ledger=VideoLedger(tmp_path / "ledger.json")).fetch(
        _source(), since=None
    )

    assert again == []
    assert asked == []


def test_words_already_kept_elsewhere_are_set_aside(tmp_path: Path) -> None:
    store = tmp_path / "set-aside.json"
    reader = _reader(
        [_video("aaaaaaaaaaa", "Le discours de Camille Exemple")],
        stored={"camille-exemple": [ANSWER]},
        set_aside=SetAside(store),
    )

    assert reader.fetch(_source(), since=None) == []
    assert "déjà dans le registre" in json.loads(store.read_text(encoding="utf-8"))["aaaaaaaaaaa"]


def test_a_failed_attribution_keeps_nothing_and_remembers_nothing(tmp_path: Path) -> None:
    store = tmp_path / "set-aside.json"
    reader = _reader(
        [_video("aaaaaaaaaaa", "Camille Exemple invitée")],
        attributor=_Turns(error=True),
        set_aside=SetAside(store),
    )

    assert reader.fetch(_source(), since=None) == []
    assert not store.exists()


def test_without_an_attributor_nothing_is_transcribed() -> None:
    asked: list[dict[str, Any]] = []
    reader = _reader([_video("aaaaaaaaaaa", "Camille Exemple invitée")], asked=asked)
    reader._attributor = None

    assert reader.fetch(_source(), since=None) == []
    assert asked == []


def test_each_channel_becomes_one_source_per_candidate_on_the_register() -> None:
    settings = MediaSettings(
        channels=(
            MediaChannel(id="tele", name="Télé", channel="UC" + "t" * 22, url="https://tele.test"),
        )
    )

    sources = media_sources(
        settings, [candidate(), candidate("dominique-autre", "Dominique Autre")]
    )

    assert [s.id for s in sources] == ["camille-exemple/media/tele", "dominique-autre/media/tele"]
    assert "Dominique" in sources[0].options["others"]


def test_a_transcript_paid_for_is_never_paid_for_again(tmp_path: Path) -> None:
    cache = TranscriptCache(tmp_path / "transcripts")
    video = [_video("aaaaaaaaaaa", "Camille Exemple invitée")]
    _reader(video, attributor=_Turns(error=True), cache=cache).fetch(_source(), since=None)
    asked: list[dict[str, Any]] = []

    (document,) = _reader(video, asked=asked, cache=cache).fetch(_source(), since=None)

    assert asked == []
    assert document.text.startswith("Je propose")
