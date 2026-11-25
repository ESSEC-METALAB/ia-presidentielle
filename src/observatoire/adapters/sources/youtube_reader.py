"""SourceReader for a YouTube channel: the transcripts of the speeches it publishes.

One source is one channel (`options.channel`, its UC… id): the candidate's own, or, for
a candidate without one, the channel of their party, where `options.match` (a pattern
the title or the description must contain, the candidate's name) keeps only the videos
about them. Only speeches are kept: a transcript does not say who is speaking, so an
interview or a debate would put a journalist's question in the candidate's mouth.

Three filters, from the cheapest to the surest:
1. the listing, read through the YouTube Data API (free, with a key): the title, or the
   start of the description, must not announce an interview (`skip_titles`; some words
   only in the title, `skip_titles_only`), and the video must last at least
   `min_minutes` (a shorter one is a clip, often of a speech already kept);
2. the transcript, read through an Apify actor, paid per video transcribed: only the
   videos left by the first filter, and never one already stored or already set aside.
   The cheaper actor reads them all in one run; YouTube sometimes stops it (a bot
   check, measured on 2026-11-16), and the videos it could not read go to a second
   actor, one run per video, five times dearer but read on another route;
3. a short Mistral call on the start and the middle of the transcript: one person
   speaking alone, and that person the candidate. A video set aside there, or found to
   be an extract of a transcript already kept, is remembered with its reason, and never
   transcribed again.
"""

import json
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ConfigDict

from observatoire.adapters.sources.apify_client import ApifyClient
from observatoire.adapters.sources.documents import make_document
from observatoire.domain.errors import (
    AnnotationUnavailableError,
    MalformedAnnotationError,
    SourceUnavailableError,
)
from observatoire.domain.models import RawDocument, Source, in_window
from observatoire.domain.ports import Clock, SpeechCheck

_log = structlog.get_logger(__name__)

TRANSCRIPT_ACTOR = "codepoetry/youtube-transcript-ai-scraper"  # 0.001 USD a video
FALLBACK_ACTOR = "starvibe/youtube-video-transcript"  # 0.005 USD a video
_API = "https://www.googleapis.com/youtube/v3/"
_VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/)([\w-]{11})")
_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
# A video whose transcript shares this share of its eight-word sequences with a kept
# transcript of the same candidate is an extract of it.
EXTRACT_CONTAINMENT = 0.8
# The speech check could not answer: the video is neither stored nor remembered, and the
# next run asks again.
_RETRY = "\x00retry"
# A transcript is already paid for: a passing error (Mistral answered HTTP 520 on
# 2026-11-16) is retried before the video is left for the next run.
CHECK_ATTEMPTS = 3


class Video(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    description: str
    published_on: date | None
    seconds: int
    live: bool = False  # live now or announced: no transcript yet

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


def video_id(url: str) -> str | None:
    match = _VIDEO_ID.search(url)
    return match.group(1) if match else None


def seconds_of(duration: str) -> int:
    """An ISO 8601 duration as YouTube writes it (PT1H2M3S) in seconds."""
    match = _DURATION.fullmatch(duration or "")
    if not match:
        return 0
    days, hours, minutes, secs = (int(g or 0) for g in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + secs


class YoutubeApi:
    """The channel listings, through the YouTube Data API v3 (1 quota unit per 50 videos)."""

    def __init__(self, http: httpx.Client, key: str | None) -> None:
        self._http = http
        self._key = key

    def uploads(self, channel: str, since: date | None, *, limit: int = 5000) -> list[Video]:
        """The channel's videos published on or after `since`, newest first."""
        playlist = "UU" + channel[2:]  # a channel's uploads playlist
        ids: list[str] = []
        page: str | None = None
        while len(ids) < limit:
            params = {"part": "contentDetails", "playlistId": playlist, "maxResults": "50"}
            if page:
                params["pageToken"] = page
            answer = self._get("playlistItems", params, channel)
            items = answer.get("items") or []
            older = False
            for item in items:
                details = item.get("contentDetails") or {}
                published = _day(details.get("videoPublishedAt"))
                if since and published and published < since:
                    older = True
                    continue
                if details.get("videoId"):
                    ids.append(details["videoId"])
            page = answer.get("nextPageToken")
            if older or not page or not items:
                break
        videos: list[Video] = []
        for start in range(0, len(ids), 50):
            answer = self._get(
                "videos",
                {"part": "snippet,contentDetails", "id": ",".join(ids[start : start + 50])},
                channel,
            )
            videos.extend(_video(item) for item in answer.get("items") or [])
        return [v for v in videos if in_window(v.published_on, since)][:limit]

    def _get(self, endpoint: str, params: dict[str, str], label: str) -> dict[str, Any]:
        if not self._key:
            raise SourceUnavailableError(label, "YOUTUBE_API_KEY is not set")
        try:
            response = self._http.get(_API + endpoint, params={**params, "key": self._key})
        except httpx.HTTPError as error:
            raise SourceUnavailableError(label, f"YouTube API: {type(error).__name__}") from error
        if response.status_code >= 400:
            raise SourceUnavailableError(
                label, f"YouTube API {endpoint}: HTTP {response.status_code}"
            )
        answer = response.json()
        return answer if isinstance(answer, dict) else {}


def _video(item: dict[str, Any]) -> Video:
    snippet = item.get("snippet") or {}
    return Video(
        id=item["id"],
        title=str(snippet.get("title") or ""),
        description=str(snippet.get("description") or ""),
        published_on=_day(snippet.get("publishedAt")),
        seconds=seconds_of((item.get("contentDetails") or {}).get("duration", "")),
        live=snippet.get("liveBroadcastContent") in ("live", "upcoming"),
    )


def _day(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


class SetAside:
    """Videos set aside after their transcript was paid for, with the reason: a JSON file,
    so that they are never transcribed again."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._reasons: dict[str, str] = {}
        if path and path.exists():
            self._reasons = json.loads(path.read_text(encoding="utf-8"))

    def __contains__(self, vid: object) -> bool:
        return vid in self._reasons

    def add(self, vid: str, reason: str) -> None:
        self._reasons[vid] = reason
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._reasons, ensure_ascii=False, indent=1), encoding="utf-8"
            )


class Transcript(BaseModel):
    """A video's French captions: the whole text, and its caption lines in order."""

    model_config = ConfigDict(frozen=True)

    text: str
    lines: tuple[str, ...]


class VideoLedger:
    """Every video transcribed, by any YouTube reader, with its candidate, day and length:
    a JSON file. The same programme broadcast on two channels (an interview shown on CNews
    and Europe 1) is then transcribed once, before anything is paid for the second."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._videos: dict[str, dict[str, Any]] = {}
        if path and path.exists():
            self._videos = json.loads(path.read_text(encoding="utf-8"))

    def twin(self, candidate: str, video: Video) -> str | None:
        """Another video of this candidate, the same day or the next, of about the same
        length (a minute, or 5 %, apart): the same programme, on another channel."""
        if video.published_on is None:
            return None
        for vid, seen in self._videos.items():
            if vid == video.id or seen["candidate"] != candidate or not seen["day"]:
                continue
            days = abs((date.fromisoformat(seen["day"]) - video.published_on).days)
            if days <= 1 and abs(seen["seconds"] - video.seconds) <= max(60, 0.05 * video.seconds):
                return vid
        return None

    def add(self, candidate: str, video: Video) -> None:
        day = video.published_on.isoformat() if video.published_on else None
        self._videos[video.id] = {"candidate": candidate, "day": day, "seconds": video.seconds}
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._videos, indent=1), encoding="utf-8")


class TranscriptCache:
    """Every transcript paid for, one JSON file per video: a video whose reading failed
    after its transcript was paid for (the model did not answer) is never paid for again."""

    def __init__(self, directory: Path | None) -> None:
        self._dir = directory

    def get(self, vid: str) -> Transcript | None:
        path = self._dir / f"{vid}.json" if self._dir else None
        if path is None or not path.exists():
            return None
        return Transcript.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, vid: str, transcript: Transcript) -> None:
        if self._dir is None:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / f"{vid}.json").write_text(transcript.model_dump_json(), encoding="utf-8")


def transcribe(
    apify: ApifyClient,
    label: str,
    chosen: Sequence[Video],
    cache: TranscriptCache | None = None,
) -> dict[str, Transcript]:
    """Video id -> French captions: from the cache, else from the cheaper actor, then the
    fallback for the videos YouTube blocked. No caption at all, with errors: the source is
    unavailable."""
    cache = cache or TranscriptCache(None)
    cached = {v.id: t for v in chosen if (t := cache.get(v.id)) is not None}
    to_pay = [v for v in chosen if v.id not in cached]
    if not to_pay:
        return cached
    found = _paid(apify, label, to_pay)
    for vid, transcript in found.items():
        cache.put(vid, transcript)
    return {**cached, **found}


def _paid(apify: ApifyClient, label: str, chosen: Sequence[Video]) -> dict[str, Transcript]:
    by_id = {v.id: v for v in chosen}
    items = apify.run(
        TRANSCRIPT_ACTOR,
        {
            "startUrls": [{"url": v.url} for v in chosen],
            "maxResults": len(chosen),
            "languages": ["fr"],
            "subType": "both",
            "outputFormats": ["text", "json"],
            "machineTranslateCaptions": False,
            "enableAiFallback": False,
        },
        label=label,
    )
    transcripts = dict(_transcripts(items, by_id))
    missing = [v for v in chosen if v.id not in transcripts]
    errors = [str(i.get("error_code") or i.get("error")) for i in items if i.get("error")]
    if missing:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for found in pool.map(lambda v: _fallback(apify, label, v), missing):
                transcripts.update(found)
    if not transcripts and errors:
        raise SourceUnavailableError(label, f"no transcript: {errors[0]}")
    return transcripts


def _fallback(apify: ApifyClient, label: str, video: Video) -> dict[str, Transcript]:
    try:
        items = apify.run(
            FALLBACK_ACTOR,
            {"youtube_url": video.url, "language": "fr", "include_transcript_text": True},
            label=label,
        )
    except SourceUnavailableError as error:
        _log.warning("youtube_fallback_failed", video=video.id, error=str(error))
        return {}
    return dict(_transcripts(items, {video.id: video}))


def start_of(clock: Clock, lookback_days: int | None, since: date | None) -> date | None:
    """Where a listing starts: the window's start, or the last days' for a daily run."""
    if lookback_days is None:
        return since
    recent = clock.now().date() - timedelta(days=lookback_days)
    return max(since, recent) if since else recent


class Screened(BaseModel):
    """One listed video and why the free filters left it out (None: to transcribe)."""

    model_config = ConfigDict(frozen=True)

    video: Video
    reason: str | None


class YoutubeReader:
    def __init__(
        self,
        api: YoutubeApi,
        apify: ApifyClient,
        clock: Clock,
        *,
        speakers: Mapping[str, str],
        daily_max_items: int,
        lookback_days: int | None,
        min_minutes: float,
        skip_titles: Sequence[str] = (),
        skip_titles_only: Sequence[str] = (),
        known_urls: Sequence[str] = (),
        stored_texts: Mapping[str, Sequence[str]] | None = None,
        speech_check: SpeechCheck | None = None,
        set_aside: SetAside | None = None,
        ledger: VideoLedger | None = None,
        cache: TranscriptCache | None = None,
        workers: int = 8,
        retry_seconds: float = 5,
    ) -> None:
        """`speakers`: candidate id -> name, for the speech check. `lookback_days`: a
        daily run lists only the last days' videos and transcribes at most
        `daily_max_items` per channel; None lists the whole window, up to max_items.
        `known_urls`: videos already stored, from any source. `stored_texts`: candidate
        id -> transcripts already kept, to recognise an extract."""
        self._api = api
        self._apify = apify
        self._clock = clock
        self._speakers = dict(speakers)
        self._daily_max_items = daily_max_items
        self._lookback_days = lookback_days
        self._min_seconds = min_minutes * 60
        self._skip = re.compile("|".join(skip_titles), re.IGNORECASE) if skip_titles else None
        self._skip_title = (
            re.compile("|".join(skip_titles_only), re.IGNORECASE) if skip_titles_only else None
        )
        self._known = {vid for url in known_urls if (vid := video_id(url))}
        self._stored = {k: list(v) for k, v in (stored_texts or {}).items()}
        self._check = speech_check
        self._set_aside = set_aside or SetAside(None)
        self._ledger = ledger or VideoLedger(None)
        self._cache = cache or TranscriptCache(None)
        self._workers = workers
        self._retry_seconds = retry_seconds

    def screen(self, source: Source, since: date | None) -> list[Screened]:
        """Every video of the window, with the free filters' verdict. Costs nothing."""
        channel = source.options.get("channel", "")
        if not channel.startswith("UC"):
            raise SourceUnavailableError(source.url, "options.channel (UC…) is required")
        match = source.options.get("match")
        needed = re.compile(match, re.IGNORECASE) if match else None
        min_seconds = float(source.options.get("min_minutes", self._min_seconds / 60)) * 60
        start = start_of(self._clock, self._lookback_days, since)
        return [
            Screened(video=video, reason=self._reason(video, needed, min_seconds))
            for video in self._api.uploads(channel, start)
        ]

    def _reason(
        self, video: Video, needed: re.Pattern[str] | None, min_seconds: float
    ) -> str | None:
        if video.live:
            return "en direct ou annoncée"
        if needed and not needed.search(f"{video.title}\n{video.description}"):
            return "ne nomme pas le candidat"
        if self._skip and self._skip.search(f"{video.title}\n{video.description[:300]}"):
            return "interview ou débat (titre)"
        if self._skip_title and self._skip_title.search(video.title):
            return "interview ou débat (titre)"
        if video.seconds < min_seconds:
            return f"moins de {min_seconds / 60:g} min"
        if video.id in self._known:
            return "déjà collectée"
        if video.id in self._set_aside:
            return "déjà écartée"
        return None

    def fetch(self, source: Source, since: date | None) -> list[RawDocument]:
        chosen = [s.video for s in self.screen(source, since) if s.reason is None]
        limit = source.max_items if self._lookback_days is None else self._daily_max_items
        chosen = chosen[:limit]
        if not chosen:
            return []
        by_id = {v.id: v for v in chosen}
        transcripts = {
            k: t.text for k, t in transcribe(self._apify, source.url, chosen, self._cache).items()
        }
        for vid in transcripts:
            self._ledger.add(source.candidate_id, by_id[vid])
        speaker = self._speakers.get(source.candidate_id, source.candidate_id)
        verdicts = self._verdicts(speaker, [(by_id[k], t) for k, t in transcripts.items()])
        kept = self._stored.setdefault(source.candidate_id, [])
        documents: list[RawDocument] = []
        for vid, text in transcripts.items():
            video = by_id[vid]
            verdict = verdicts.get(vid)
            if verdict == _RETRY:
                continue
            if verdict is not None:
                self._set_aside.add(vid, verdict)
                _log.info("youtube_video_set_aside", video=vid, reason=verdict)
                continue
            if any(containment(text, other) >= EXTRACT_CONTAINMENT for other in kept):
                self._set_aside.add(vid, "extrait d'une vidéo déjà gardée")
                continue
            kept.append(text)
            documents.append(
                make_document(
                    source,
                    url=video.url,
                    title=video.title,
                    text=text,
                    published_on=video.published_on,
                    fetched_at=self._clock.now(),
                )
            )
        return documents

    def _verdicts(self, speaker: str, videos: list[tuple[Video, str]]) -> dict[str, str | None]:
        """Video id -> why it is set aside (absent when kept). Without a check, all kept."""
        if self._check is None:
            return {}

        def check(pair: tuple[Video, str]) -> str | None:
            return self._one(speaker, *pair)

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            reasons = list(pool.map(check, videos))
        return {v.id: r for (v, _), r in zip(videos, reasons, strict=True) if r is not None}

    def _one(self, speaker: str, video: Video, text: str) -> str | None:
        assert self._check is not None
        for attempt in range(1, CHECK_ATTEMPTS + 1):
            try:
                verdict = self._check.check(speaker, video.title, excerpt(text))
            except (AnnotationUnavailableError, MalformedAnnotationError) as error:
                _log.warning("speech_check_unavailable", video=video.id, error=str(error))
                if attempt < CHECK_ATTEMPTS:
                    time.sleep(self._retry_seconds * attempt)
                continue
            return None if verdict.kept else verdict.reason
        return _RETRY


def _transcripts(
    items: Sequence[dict[str, Any]], by_id: Mapping[str, Video]
) -> Iterator[tuple[str, Transcript]]:
    for item in items:
        meta = item.get("metadata") or {}
        vid = video_id(str(meta.get("url") or item.get("url") or ""))
        text = " ".join(str(item.get("transcript_text") or "").split())
        if vid is None or vid not in by_id or not text:
            continue
        if item.get("language") and not str(item["language"]).startswith("fr"):
            continue  # a translation is not the speaker's words
        lines = _lines(item.get("transcript_json") or item.get("transcript")) or _sentences(text)
        yield vid, Transcript(text=text, lines=lines)


def _lines(segments: object) -> tuple[str, ...]:
    """Caption lines from either actor: a list of {text}, or that list as a JSON string."""
    if isinstance(segments, str):
        try:
            segments = json.loads(segments)
        except ValueError:
            return ()
    if not isinstance(segments, list):
        return ()
    texts = (" ".join(str(s.get("text", "")).split()) for s in segments if isinstance(s, dict))
    return tuple(t for t in texts if t)


def _sentences(text: str) -> tuple[str, ...]:
    return tuple(p for p in re.split(r"(?<=[.?!])\s+", text) if p)


def excerpt(text: str, size: int = 1500) -> str:
    """The start and the middle of a transcript: enough to tell a speech from an exchange."""
    if len(text) <= 2 * size:
        return text
    middle = len(text) // 2
    return f"{text[:size]}\n[…]\n{text[middle : middle + size]}"


def _shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i : i + n]) for i in range(max(0, len(words) - n + 1))}


def containment(part: str, whole: str) -> float:
    """The share of `part`'s eight-word sequences found in `whole`."""
    a = _shingles(part)
    return len(a & _shingles(whole)) / len(a) if a else 0.0
