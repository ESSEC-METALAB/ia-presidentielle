"""SourceReader for a candidate on a media's YouTube channel: their interviews and speeches.

A media channel is read for every candidate on the register (config/sources.yaml,
`media`, expanded into one source per candidate and channel). Its listing is read once
per run, whatever the number of candidates. A video is kept for a candidate only when its
title names them and no other candidate, and announces an interview or a speech; an
editorial, a debate or an analysis is left out.

An interview's captions do not say who is speaking. Mistral reads them and splits them
into speaking turns; only the turns it attributes to the candidate, and is sure of, are
kept, each as a paragraph. A journalist's question never reaches the register.

Redundancy is removed at three points:
1. before paying: a video of the same candidate, the same day or the next, of about the
   same length as one already transcribed, by any reader, is the same programme on
   another channel (`VideoLedger`);
2. after the transcript: the candidate's words found, for the most part, in a text of
   theirs already kept (a speech on their own channel, a transcript, the same interview
   elsewhere) are set aside, and remembered with why (`SetAside`);
3. on the register: a quote already shown from another source is not shown again
   (application/build_register.py).
"""

import re
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import structlog

from observatoire.adapters.sources.apify_client import ApifyClient
from observatoire.adapters.sources.documents import make_document
from observatoire.adapters.sources.youtube_reader import (
    CHECK_ATTEMPTS,
    Screened,
    SetAside,
    Transcript,
    TranscriptCache,
    Video,
    VideoLedger,
    YoutubeApi,
    containment,
    start_of,
    transcribe,
    video_id,
)
from observatoire.domain.errors import (
    AnnotationUnavailableError,
    MalformedAnnotationError,
    SourceUnavailableError,
)
from observatoire.domain.models import RawDocument, Source, SpeakingTurn
from observatoire.domain.ports import Clock, TurnAttributor

_log = structlog.get_logger(__name__)

# Lines sent to the model at once: about eight minutes of captions. A 40-minute
# interview sent whole made Mistral answer HTTP 500, and 450 lines often took longer
# than three minutes (measured on 2026-11-25).
CHUNK_LINES = 200
# Fewer words than this attributed to the candidate: not their interview.
MIN_WORDS = 150
# The candidate's words share this much of their eight-word sequences with a text of
# theirs already kept: the same speech or interview, captioned again.
MEDIA_CONTAINMENT = 0.6


class MediaReader:
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
        keep_titles: Sequence[str],
        skip_titles: Sequence[str] = (),
        known_urls: Sequence[str] = (),
        stored_texts: Mapping[str, Sequence[str]] | None = None,
        attributor: TurnAttributor | None = None,
        set_aside: SetAside | None = None,
        ledger: VideoLedger | None = None,
        cache: TranscriptCache | None = None,
        workers: int = 6,
        retry_seconds: float = 5,
    ) -> None:
        """`speakers`: candidate id -> name. `stored_texts`: candidate id -> texts of
        theirs already kept (speeches, transcripts, interviews), to recognise a repeat.
        Without an attributor, nothing is transcribed: no interview is kept unread."""
        self._api = api
        self._apify = apify
        self._clock = clock
        self._speakers = dict(speakers)
        self._daily_max_items = daily_max_items
        self._lookback_days = lookback_days
        self._min_seconds = min_minutes * 60
        self._keep = re.compile("|".join(keep_titles), re.IGNORECASE)
        self._skip = re.compile("|".join(skip_titles), re.IGNORECASE) if skip_titles else None
        self._known = {vid for url in known_urls if (vid := video_id(url))}
        self._stored = {k: list(v) for k, v in (stored_texts or {}).items()}
        self._attributor = attributor
        self._set_aside = set_aside or SetAside(None)
        self._ledger = ledger or VideoLedger(None)
        self._cache = cache or TranscriptCache(None)
        self._workers = workers
        self._retry_seconds = retry_seconds
        self._listings: dict[tuple[str, date | None], list[Video]] = {}

    def screen(self, source: Source, since: date | None) -> list[Screened]:
        """Every video of the channel in the window, with the free filters' verdict for
        this candidate. Costs nothing; the listing is read once per channel."""
        channel = source.options.get("channel", "")
        if not channel.startswith("UC") or not source.options.get("match"):
            raise SourceUnavailableError(source.url, "options.channel and options.match")
        needed = re.compile(source.options["match"], re.IGNORECASE)
        others = source.options.get("others")
        rivals = re.compile(others, re.IGNORECASE) if others else None
        start = start_of(self._clock, self._lookback_days, since)
        if (channel, start) not in self._listings:
            # A news channel publishes thousands of videos a month: read them all.
            self._listings[(channel, start)] = self._api.uploads(channel, start, limit=50000)
        return [
            Screened(video=video, reason=self._reason(source, video, needed, rivals))
            for video in self._listings[(channel, start)]
        ]

    def _reason(
        self,
        source: Source,
        video: Video,
        needed: re.Pattern[str],
        rivals: re.Pattern[str] | None,
    ) -> str | None:
        heading = f"{video.title}\n{video.description[:300]}"
        if not needed.search(video.title):
            return "ne nomme pas le candidat"
        checks = (
            (video.live, "en direct ou annoncée"),
            (bool(rivals and rivals.search(video.title)), "nomme un autre candidat"),
            (bool(self._skip and self._skip.search(heading)), "édito, débat ou analyse"),
            (not self._keep.search(heading), "n'annonce ni interview ni discours"),
            (video.seconds < self._min_seconds, f"moins de {self._min_seconds / 60:g} min"),
            (video.id in self._known, "déjà collectée"),
            (video.id in self._set_aside, "déjà écartée"),
            (bool(self._ledger.twin(source.candidate_id, video)), "même émission déjà transcrite"),
        )
        return next((reason for failed, reason in checks if failed), None)

    def fetch(self, source: Source, since: date | None) -> list[RawDocument]:
        if self._attributor is None:
            return []
        limit = source.max_items if self._lookback_days is None else self._daily_max_items
        chosen = self._without_twins(
            source.candidate_id, [s.video for s in self.screen(source, since) if s.reason is None]
        )[:limit]
        if not chosen:
            return []
        by_id = {v.id: v for v in chosen}
        transcripts = transcribe(self._apify, source.url, chosen, self._cache)
        for vid in transcripts:
            self._ledger.add(source.candidate_id, by_id[vid])
        speaker = self._speakers.get(source.candidate_id, source.candidate_id)

        def words_of(vid: str) -> str | None:
            return self._candidate_words(speaker, by_id[vid], transcripts[vid])

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            words = dict(zip(transcripts, pool.map(words_of, transcripts), strict=True))
        return [
            document
            for vid, text in words.items()
            if text is not None and (document := self._keep_one(source, by_id[vid], text))
        ]

    def _without_twins(self, candidate: str, videos: list[Video]) -> list[Video]:
        """The same programme twice in one listing (a live and its replay): once."""
        ledger = VideoLedger(None)
        out = []
        for video in videos:
            if ledger.twin(candidate, video) is None:
                ledger.add(candidate, video)
                out.append(video)
        return out

    def _keep_one(self, source: Source, video: Video, text: str) -> RawDocument | None:
        kept = self._stored.setdefault(source.candidate_id, [])
        if len(text.split()) < MIN_WORDS:
            self._set_aside.add(video.id, f"le candidat y parle peu (moins de {MIN_WORDS} mots)")
            return None
        if any(containment(text, other) >= MEDIA_CONTAINMENT for other in kept):
            self._set_aside.add(video.id, "déjà dans le registre (même discours ou interview)")
            return None
        kept.append(text)
        return make_document(
            source,
            url=video.url,
            title=video.title,
            text=text,
            published_on=video.published_on,
            fetched_at=self._clock.now(),
        )

    def _candidate_words(self, speaker: str, video: Video, transcript: Transcript) -> str | None:
        """The candidate's sure turns, one paragraph each; None when the model could not
        answer (not remembered: the next run asks again)."""
        lines = transcript.lines
        paragraphs: list[str] = []
        for start in range(0, len(lines), CHUNK_LINES):
            chunk = lines[start : start + CHUNK_LINES]
            turns = self._turns(speaker, video, chunk)
            if turns is None:
                return None
            for turn in turns:
                last = min(turn.last, len(chunk) - 1)
                if turn.speaker == "candidate" and turn.sure and turn.first <= last:
                    paragraphs.append(" ".join(chunk[turn.first : last + 1]))
        return "\n\n".join(paragraphs)

    def _turns(self, speaker: str, video: Video, lines: Sequence[str]) -> list[SpeakingTurn] | None:
        assert self._attributor is not None
        for attempt in range(1, CHECK_ATTEMPTS + 1):
            try:
                return self._attributor.attribute(speaker, video.title, lines)
            except (AnnotationUnavailableError, MalformedAnnotationError) as error:
                _log.warning("turn_attribution_unavailable", video=video.id, error=str(error))
                if attempt < CHECK_ATTEMPTS:
                    time.sleep(self._retry_seconds * attempt)
        return None
