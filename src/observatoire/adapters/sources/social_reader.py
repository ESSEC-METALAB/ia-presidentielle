"""SourceReader for a candidate's account on a social network, read through Apify.

One source is one account (`options.platform`, `options.account`). Each post the
account wrote becomes one document: its own words only. Reposts of other accounts are
left out, and so are other people's comments, which are never stored (personal data
of third parties). A video counts by the words it carries: the caption, plus the
French subtitles when the platform provides them (TikTok), or the transcript of the
video (YouTube, where only speeches are kept: an interview's transcript does not say
who is speaking).

The scrapers are third-party Apify actors; each platform's input and output shape
belongs to its actor, and is written here, next to it.
"""

import re
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ConfigDict

from observatoire.adapters.sources.apify_client import ApifyClient
from observatoire.adapters.sources.documents import make_document
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import RawDocument, Source, in_window
from observatoire.domain.ports import Clock

_log = structlog.get_logger(__name__)


class _Post(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    published_on: date | None
    text: str
    title: str | None = None
    subtitles_url: str | None = None  # French subtitles to append, fetched separately
    about: str = ""  # the video's description: says whether it is an interview


class _Platform(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    actor: str
    run_input: Callable[[Source, str, date | None, int], dict[str, Any]]
    posts: Callable[[Source, str, Sequence[dict[str, Any]]], Iterator[_Post]]


class SocialReader:
    def __init__(
        self,
        apify: ApifyClient,
        http: httpx.Client,
        clock: Clock,
        *,
        daily_max_items: int,
        lookback_days: int | None,
        skip_titles: Sequence[str] = (),
        known: frozenset[str] = frozenset(),
    ) -> None:
        """`lookback_days`: a daily run reads only the last days' posts, at most
        `daily_max_items`; None reads the whole window, up to each source's max_items.
        A source not in `known` (nothing stored from it yet) is read over the whole
        window once, whatever `lookback_days` says: its first run fills it in."""
        self._apify = apify
        self._http = http
        self._clock = clock
        self._daily_max_items = daily_max_items
        self._lookback_days = lookback_days
        self._skip_titles = (
            re.compile("|".join(skip_titles), re.IGNORECASE) if skip_titles else None
        )
        self._known = known

    def fetch(self, source: Source, since: date | None) -> list[RawDocument]:
        platform = _PLATFORMS.get(source.options.get("platform", ""))
        account = source.options.get("account", "")
        if platform is None or not account:
            raise SourceUnavailableError(source.url, "options.platform and options.account")
        start, limit = since, source.max_items
        if self._lookback_days is not None and source.id in self._known:
            recent = self._clock.now().date() - timedelta(days=self._lookback_days)
            start = max(since, recent) if since else recent
            limit = min(limit, self._daily_max_items)
        items = self._apify.run(
            platform.actor, platform.run_input(source, account, start, limit), label=source.url
        )
        failures = [item for item in items if item.get("error") and not _has_content(item)]
        if items and len(failures) == len(items):
            raise SourceUnavailableError(
                source.url, str(failures[0].get("errorDescription") or failures[0]["error"])
            )
        documents = []
        for post in platform.posts(source, account, items):
            if not in_window(post.published_on, start):
                continue
            if self._skip_titles and self._skip_titles.search(f"{post.title or ''}\n{post.about}"):
                continue
            text = self._with_subtitles(post)
            if not text.strip():
                continue
            documents.append(
                make_document(
                    source,
                    url=post.url,
                    title=post.title or _first_line(text),
                    text=text,
                    published_on=post.published_on,
                    fetched_at=self._clock.now(),
                )
            )
        return documents

    def _with_subtitles(self, post: _Post) -> str:
        if not post.subtitles_url:
            return post.text
        try:
            response = self._http.get(post.subtitles_url, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError as error:  # the caption still stands on its own
            _log.warning("subtitles_unavailable", url=post.url, error=type(error).__name__)
            return post.text
        spoken = webvtt_text(response.text)
        return f"{post.text}\n\n{spoken}" if post.text.strip() else spoken


def webvtt_text(vtt: str) -> str:
    """The spoken text of a WebVTT file: cues joined, timings and repeats dropped."""
    lines: list[str] = []
    for line in vtt.splitlines():
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        if line.startswith(("NOTE", "Kind:", "Language:")):
            continue
        if not lines or lines[-1] != line:
            lines.append(line)
    return " ".join(lines)


def _has_content(item: dict[str, Any]) -> bool:
    return any(item.get(key) for key in ("text", "caption", "content", "transcript_text"))


def _first_line(text: str) -> str:
    line = text.strip().split("\n", 1)[0]
    return line if len(line) <= 120 else line[:117].rstrip() + "…"


def _day(value: object) -> date | None:
    """An ISO timestamp, a Unix time in seconds or milliseconds, X's date, or YYYYMMDD."""
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, UTC).date()
    if not isinstance(value, str) or not value:
        return None
    if re.fullmatch(r"\d{8}", value):
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").date()  # X
    except ValueError:
        return None


def _same(a: object, b: str) -> bool:
    return isinstance(a, str) and a.lower().lstrip("@") == b.lower().lstrip("@")


# --- X: kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest --------------


def _x_input(source: Source, account: str, start: date | None, limit: int) -> dict[str, Any]:
    query = f"from:{account}" + (f" since:{start.isoformat()}" if start else "")
    return {"searchTerms": [query], "maxItems": limit, "queryType": "Latest"}


def _x_posts(source: Source, account: str, items: Sequence[dict[str, Any]]) -> Iterator[_Post]:
    for item in items:
        text = item.get("text") or ""
        author = (item.get("author") or {}).get("userName")
        if item.get("type") != "tweet" or not _same(author, account) or not item.get("url"):
            continue
        if item.get("isRetweet") or item.get("retweeted_tweet") or text.startswith("RT @"):
            continue  # someone else's words
        if item.get("isReply") and not _same(item.get("inReplyToUsername"), account):
            continue  # an answer to someone else: out of context without the thread
        yield _Post(url=item["url"], published_on=_day(item.get("createdAt")), text=text)


# --- Facebook: apify/facebook-posts-scraper ----------------------------------------------


def _facebook_input(source: Source, account: str, start: date | None, limit: int) -> dict[str, Any]:
    return {"startUrls": [{"url": source.url}], "resultsLimit": limit}


def _facebook_posts(
    source: Source, account: str, items: Sequence[dict[str, Any]]
) -> Iterator[_Post]:
    for item in items:
        if not item.get("url") or not item.get("text"):
            continue
        if item.get("pageName") and not _same(item.get("pageName"), account):
            continue
        yield _Post(url=item["url"], published_on=_day(item.get("time")), text=item["text"])


# --- Instagram: apify/instagram-post-scraper ---------------------------------------------


def _instagram_input(
    source: Source, account: str, start: date | None, limit: int
) -> dict[str, Any]:
    run_input: dict[str, Any] = {"username": [account], "resultsLimit": limit}
    run_input["skipPinnedPosts"] = True
    if start:  # the actor stops there: older posts are neither read nor paid for
        run_input["onlyPostsNewerThan"] = start.isoformat()
    return run_input


def _instagram_posts(
    source: Source, account: str, items: Sequence[dict[str, Any]]
) -> Iterator[_Post]:
    for item in items:
        if not item.get("url") or not _same(item.get("ownerUsername"), account):
            continue
        yield _Post(
            url=item["url"],
            published_on=_day(item.get("timestamp")),
            text=item.get("caption") or "",
        )


# --- TikTok: clockworks/tiktok-scraper ---------------------------------------------------


def _tiktok_input(source: Source, account: str, start: date | None, limit: int) -> dict[str, Any]:
    return {
        "profiles": [account],
        "resultsPerPage": limit,
        "profileSorting": "latest",
        "excludePinnedPosts": True,
    }


def _tiktok_posts(source: Source, account: str, items: Sequence[dict[str, Any]]) -> Iterator[_Post]:
    for item in items:
        author = (item.get("authorMeta") or {}).get("name")
        if not item.get("webVideoUrl") or not _same(author, account):
            continue
        subtitles = (item.get("videoMeta") or {}).get("subtitleLinks") or []
        french = next(
            (
                s.get("downloadLink")
                for s in subtitles
                if str(s.get("language", "")).startswith("fra")
            ),
            None,
        )
        yield _Post(
            url=item["webVideoUrl"],
            published_on=_day(item.get("createTimeISO") or item.get("createTime")),
            text=item.get("text") or "",
            subtitles_url=french,
        )


# --- YouTube: codepoetry/youtube-transcript-ai-scraper -----------------------------------


def _youtube_input(source: Source, account: str, start: date | None, limit: int) -> dict[str, Any]:
    return {
        "startUrls": [{"url": source.url}],
        "maxResults": limit,
        "languages": ["fr"],
        "subType": "both",
        "outputFormats": ["text"],
        "machineTranslateCaptions": False,
        "enableAiFallback": False,
    }


def _youtube_posts(
    source: Source, account: str, items: Sequence[dict[str, Any]]
) -> Iterator[_Post]:
    for item in items:
        meta = item.get("metadata") or {}
        if not meta.get("url") or not item.get("transcript_text"):
            continue
        if item.get("language") and not str(item["language"]).startswith("fr"):
            continue  # a translation is not the speaker's words
        yield _Post(
            url=meta["url"],
            published_on=_day(meta.get("publish_date") or meta.get("upload_date")),
            text=item["transcript_text"],
            title=meta.get("title"),
            about=str(meta.get("description") or "")[:300],
        )


# --- LinkedIn: harvestapi/linkedin-profile-posts -----------------------------------------


def _linkedin_input(source: Source, account: str, start: date | None, limit: int) -> dict[str, Any]:
    run_input: dict[str, Any] = {
        "targetUrls": [source.url],
        "maxPosts": limit,
        "includeReposts": False,
        "includeQuotePosts": True,
    }
    if start:  # the actor stops there: older posts are neither read nor paid for
        run_input["postedLimitDate"] = start.isoformat()
    return run_input


def _linkedin_posts(
    source: Source, account: str, items: Sequence[dict[str, Any]]
) -> Iterator[_Post]:
    for item in items:
        author = (item.get("author") or {}).get("publicIdentifier")
        if item.get("type") != "post" or not item.get("linkedinUrl") or not item.get("content"):
            continue
        if author and not _same(author, account):
            continue
        posted = item.get("postedAt") or {}
        yield _Post(
            url=item["linkedinUrl"],
            published_on=_day(posted.get("date") if isinstance(posted, dict) else posted),
            text=item["content"],
        )


_PLATFORMS = {
    "x": _Platform(
        actor="kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest",
        run_input=_x_input,
        posts=_x_posts,
    ),
    "facebook": _Platform(
        actor="apify/facebook-posts-scraper", run_input=_facebook_input, posts=_facebook_posts
    ),
    "instagram": _Platform(
        actor="apify/instagram-post-scraper", run_input=_instagram_input, posts=_instagram_posts
    ),
    "tiktok": _Platform(
        actor="clockworks/tiktok-scraper", run_input=_tiktok_input, posts=_tiktok_posts
    ),
    "youtube": _Platform(
        actor="codepoetry/youtube-transcript-ai-scraper",
        run_input=_youtube_input,
        posts=_youtube_posts,
    ),
    "linkedin": _Platform(
        actor="harvestapi/linkedin-profile-posts", run_input=_linkedin_input, posts=_linkedin_posts
    ),
}
PLATFORMS = tuple(_PLATFORMS)
