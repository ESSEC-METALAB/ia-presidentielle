"""The social media reader, on fictional Apify answers served by a mock transport."""

import json
from datetime import date
from typing import Any

import httpx
import pytest

from observatoire.adapters.sources.apify_client import ApifyClient
from observatoire.adapters.sources.social_reader import SocialReader, webvtt_text
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import Source, TrustLevel
from support import FrozenClock

SUBTITLES = "https://cdn.test/subtitles.vtt"


def _source(platform: str, account: str = "camille_exemple", max_items: int = 50) -> Source:
    return Source(
        id=f"camille-exemple/{platform}/{account}",
        candidate_id="camille-exemple",
        kind="social",
        url=f"https://{platform}.test/{account}",
        trust_level=TrustLevel.OWN_WORDS,
        label=f"Camille Exemple sur {platform}",
        max_items=max_items,
        options={"platform": platform, "account": account},
    )


def _reader(
    items: list[dict[str, Any]],
    *,
    lookback_days: int | None = None,
    token: str | None = "secret",
    asked: list[dict[str, Any]] | None = None,
    skip_titles: tuple[str, ...] = (),
    known: frozenset[str] = frozenset({"camille-exemple/x/camille_exemple"}),
) -> SocialReader:
    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == SUBTITLES:
            return httpx.Response(200, text="WEBVTT\n\n00:00.000 --> 00:02.000\nL'IA à l'école.\n")
        if asked is not None:
            asked.append({"url": str(request.url), "input": json.loads(request.content)})
        return httpx.Response(201, json=items)

    http = httpx.Client(transport=httpx.MockTransport(handle))
    apify = ApifyClient(http, token, max_charge_usd=0.5, timeout_seconds=60)
    return SocialReader(
        apify,
        http,
        FrozenClock(),
        daily_max_items=10,
        lookback_days=lookback_days,
        skip_titles=skip_titles,
        known=known,
    )


def _tweet(text: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": "tweet",
        "url": f"https://x.test/status/{abs(hash(text))}",
        "text": text,
        "createdAt": "Mon Sep 14 10:00:00 +0000 2026",
        "author": {"userName": "camille_exemple"},
        **fields,
    }


def test_a_post_becomes_a_document_of_the_account_with_its_date() -> None:
    reader = _reader([_tweet("Nous créerons une autorité de contrôle de l'IA.")])

    (document,) = reader.fetch(_source("x"), since=date(2026, 7, 1))

    assert document.text == "Nous créerons une autorité de contrôle de l'IA."
    assert document.published_on == date(2026, 9, 14)
    assert document.url.startswith("https://x.test/status/")
    assert document.trust_level == TrustLevel.OWN_WORDS


def test_reposts_and_answers_to_others_are_not_the_candidates_words() -> None:
    reader = _reader(
        [
            _tweet("RT @autre: un texte d'un autre compte"),
            _tweet("Republié", isRetweet=True),
            _tweet("Réponse à un autre", isReply=True, inReplyToUsername="autre"),
            _tweet("Suite de mon fil", isReply=True, inReplyToUsername="camille_exemple"),
            _tweet("Écrit par un autre", author={"userName": "autre"}),
        ]
    )

    documents = reader.fetch(_source("x"), since=None)

    assert [d.text for d in documents] == ["Suite de mon fil"]


def test_posts_before_the_window_are_left_out() -> None:
    reader = _reader([_tweet("Ancien", createdAt="Tue Jun 02 10:00:00 +0000 2026")])

    assert reader.fetch(_source("x"), since=date(2026, 7, 1)) == []


def test_a_daily_run_asks_only_for_the_last_days_and_a_few_posts() -> None:
    asked: list[dict[str, Any]] = []
    reader = _reader([], lookback_days=3, asked=asked)

    reader.fetch(_source("x"), since=date(2026, 7, 1))

    (call,) = asked
    assert "kaitoeasyapi~twitter-x-data-tweet-scraper" in call["url"]
    assert "maxTotalChargeUsd=0.5" in call["url"]
    assert call["input"]["maxItems"] == 10
    assert call["input"]["searchTerms"] == ["from:camille_exemple since:2026-10-01"]


def test_a_new_account_is_read_over_the_whole_window_on_its_first_run() -> None:
    asked: list[dict[str, Any]] = []
    reader = _reader([], lookback_days=3, asked=asked, known=frozenset())

    reader.fetch(_source("x", max_items=40), since=date(2026, 7, 1))

    assert asked[0]["input"]["maxItems"] == 40
    assert asked[0]["input"]["searchTerms"] == ["from:camille_exemple since:2026-07-01"]


def test_the_whole_window_is_read_up_to_the_sources_limit() -> None:
    asked: list[dict[str, Any]] = []
    reader = _reader([], lookback_days=None, asked=asked)

    reader.fetch(_source("x", max_items=40), since=date(2026, 7, 1))

    assert asked[0]["input"]["maxItems"] == 40
    assert asked[0]["input"]["searchTerms"] == ["from:camille_exemple since:2026-07-01"]


def test_a_tiktok_video_carries_its_caption_and_its_french_subtitles() -> None:
    video = {
        "webVideoUrl": "https://tiktok.test/@camille_exemple/video/1",
        "createTimeISO": "2026-10-02T08:00:00.000Z",
        "text": "Mon programme",
        "authorMeta": {"name": "camille_exemple"},
        "videoMeta": {
            "subtitleLinks": [
                {"language": "eng-US", "downloadLink": "https://cdn.test/en.vtt"},
                {"language": "fra-FR", "downloadLink": SUBTITLES},
            ]
        },
    }

    (document,) = _reader([video]).fetch(_source("tiktok"), since=None)

    assert document.text == "Mon programme\n\nL'IA à l'école."


def test_a_youtube_interview_is_skipped_and_a_speech_is_kept() -> None:
    def video(title: str) -> dict[str, Any]:
        return {
            "metadata": {
                "url": f"https://youtube.test/{len(title)}",
                "title": title,
                "publish_date": "20261011",
            },
            "language": "fr",
            "transcript_text": "Mes chers amis, l'IA va changer le travail.",
        }

    answered = video("Vous président")
    answered["metadata"]["description"] = (
        "Pendant trois heures, j'ai répondu aux questions de BFMTV."
    )
    reader = _reader(
        [video("Discours à Clermont-Ferrand"), video("Entretien sur France Inter"), answered],
        skip_titles=(r"\bentretien", r"\bquestions?\b"),
    )

    (document,) = reader.fetch(_source("youtube"), since=None)

    assert document.title == "Discours à Clermont-Ferrand"
    assert document.published_on == date(2026, 10, 11)


def test_comments_returned_by_a_scraper_are_never_stored() -> None:
    post = {
        "url": "https://instagram.test/p/1",
        "timestamp": "2026-10-27T19:08:43.000Z",
        "ownerUsername": "camille_exemple",
        "caption": "Défendons la recherche en IA.",
        "latestComments": [{"text": "Un commentaire d'un internaute"}],
        "firstComment": "Un commentaire d'un internaute",
    }

    (document,) = _reader([post]).fetch(_source("instagram"), since=None)

    assert "internaute" not in document.text


def test_an_account_the_scraper_cannot_read_fails_the_source() -> None:
    reader = _reader([{"url": "https://facebook.test/x", "error": "not_available"}])

    with pytest.raises(SourceUnavailableError, match="not_available"):
        reader.fetch(_source("facebook"), since=None)


def test_without_a_token_nothing_is_asked() -> None:
    with pytest.raises(SourceUnavailableError, match="APIFY_TOKEN"):
        _reader([], token=None).fetch(_source("x"), since=None)


def test_webvtt_keeps_the_words_only() -> None:
    vtt = (
        "WEBVTT\n\n1\n00:00.000 --> 00:01.000\n<c>Bonjour</c>\n\n"
        "2\n00:01.000 --> 00:02.000\nBonjour\nà tous\n"
    )

    assert webvtt_text(vtt) == "Bonjour à tous"
