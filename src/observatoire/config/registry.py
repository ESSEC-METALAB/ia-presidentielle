"""Loads and validates config/*.yaml into domain models."""

import re
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from observatoire.domain.annotation import Dimension
from observatoire.domain.errors import ConfigurationError
from observatoire.domain.models import Candidate, Source, TrustLevel
from observatoire.domain.scoring import ScoreScale
from observatoire.domain.watch import WatchedTopic
from observatoire.services.ai_relevance import RelevanceSettings
from observatoire.services.annotation_gates import GateSettings
from observatoire.services.candidate_matcher import alias_pattern
from observatoire.services.segmentation import SegmentationSettings

_Model = TypeVar("_Model", bound=BaseModel)


class CrawlerSettings(BaseModel):
    """The crawler's identity and manners (CLAUDE.md §7). Not secret: versioned config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_agent: str = Field(min_length=10)
    min_delay_seconds: float = Field(ge=0)
    timeout_seconds: float = Field(gt=0)
    min_text_chars: int = Field(ge=0)
    max_redirects: int = Field(ge=0, le=10)


class CollectionSettings(BaseModel):
    """What period the corpus covers. Texts published before `since` are not collected.

    `near_duplicate_similarity`: from this similarity to a stored version of the same
    source and URL, a text is the same text extracted again, not a new one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    since: date
    near_duplicate_similarity: float = Field(default=1.0, gt=0, le=1)


class SocialSettings(BaseModel):
    """How social media accounts are read through Apify (config/sources.yaml, `social`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # A daily run reads only the posts of the last days, and at most this many per
    # account; `observatoire collect --full-window` reads the whole window instead, up to
    # each source's max_items.
    lookback_days: int = Field(default=3, ge=1)
    daily_max_items: int = Field(default=15, ge=1)
    # Spending cap of one Apify run (one account), in US dollars.
    max_charge_usd: float = Field(default=0.5, gt=0)
    timeout_seconds: int = Field(default=280, ge=30, le=3600)
    # An account that stored a post less than this many hours ago is not read again: the
    # site's refresh button, pressed several times a day, does not pay Apify twice.
    min_hours_between_reads: float = Field(default=20, ge=0)


class YoutubeSettings(BaseModel):
    """How YouTube channels are read (config/sources.yaml, `youtube`): listed through the
    YouTube Data API, transcribed through Apify (the `social` cap and timeout apply)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # A daily run lists only the last days' videos, and transcribes at most this many
    # per channel; `observatoire collect --full-window` lists the whole window instead,
    # up to each source's max_items.
    lookback_days: int = Field(default=3, ge=1)
    daily_max_items: int = Field(default=5, ge=1)
    # A shorter video is a clip, often of a speech already kept. A source can set its own
    # (`options.min_minutes`).
    min_minutes: float = Field(default=5, ge=0)
    # Videos whose title (or the start of their description) matches one of these are
    # skipped before any transcript is paid for: interviews and debates, whose transcript
    # does not say who is speaking.
    skip_titles: tuple[str, ...] = ()
    # Matched against the title only: words that announce a programme in a title but are
    # ordinary phrasing in a description ("Face à la Chine…").
    skip_titles_only: tuple[str, ...] = ()

    @field_validator("skip_titles", "skip_titles_only")
    @classmethod
    def _titles_compile(cls, patterns: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"{pattern!r}: {error}") from error
        return patterns


class MediaChannel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1)
    channel: str = Field(pattern=r"^UC[\w-]{22}$")
    url: str = Field(pattern=r"^https://")


class MediaSettings(BaseModel):
    """Media channels on YouTube (config/sources.yaml, `media`): each is read for every
    candidate on the register, as one source per candidate and channel (kind: media)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lookback_days: int = Field(default=3, ge=1)
    daily_max_items: int = Field(default=3, ge=1)
    max_items: int = Field(default=40, ge=1)
    min_minutes: float = Field(default=8, ge=0)
    # The title or the start of the description must announce an interview or a speech,
    # and must not announce an editorial, a debate or an analysis.
    keep_titles: tuple[str, ...] = ()
    skip_titles: tuple[str, ...] = ()
    channels: tuple[MediaChannel, ...] = ()

    @field_validator("keep_titles", "skip_titles")
    @classmethod
    def _compile(cls, patterns: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"{pattern!r}: {error}") from error
        return patterns


def media_sources(media: MediaSettings, candidates: Sequence[Candidate]) -> list[Source]:
    """One source per candidate on the register and media channel. `match` names the
    candidate; `others`, every other candidate on the register."""
    shown = [c for c in candidates if c.on_register]
    out = []
    for channel in media.channels:
        for person in shown:
            rivals = [a for c in shown if c.id != person.id for a in (c.aliases or (c.name,))]
            out.append(
                Source(
                    id=f"{person.id}/media/{channel.id}",
                    candidate_id=person.id,
                    kind="media",
                    url=channel.url,
                    trust_level=TrustLevel.OWN_WORDS,
                    label=f"{person.name} sur {channel.name} (interviews et discours)",
                    max_items=media.max_items,
                    options={
                        "channel": channel.channel,
                        "media": channel.name,
                        "match": alias_pattern(person.aliases or (person.name,)).pattern,
                        "others": alias_pattern(rivals).pattern if rivals else "",
                    },
                )
            )
    return out


class ScoringSettings(BaseModel):
    """config/scoring.yaml: the scales statements are scored on, and how the site averages."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregation: Literal["mean"] = "mean"
    min_statements: int = Field(default=3, ge=1)
    scales: tuple[ScoreScale, ...] = ()


class TaxonomySettings(BaseModel):
    """config/taxonomy.yaml: the dimensions, the prefilter and the annotation gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    dimensions: tuple[Dimension, ...] = Field(min_length=1)
    relevance: RelevanceSettings
    gates: GateSettings

    @property
    def dimension_ids(self) -> tuple[str, ...]:
        return tuple(d.id for d in self.dimensions)


class RosterSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(pattern=r"^https://")
    label: str


class WatchSettings(BaseModel):
    """config/watch.yaml: the outside roster and the topics watched for the editors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    roster: RosterSettings
    topic_threshold: int = Field(ge=1)
    topic_min_candidates: int = Field(default=1, ge=1)
    topics: tuple[WatchedTopic, ...] = ()

    @field_validator("topics")
    @classmethod
    def _patterns_compile(cls, topics: tuple[WatchedTopic, ...]) -> tuple[WatchedTopic, ...]:
        for topic in topics:
            for pattern in topic.patterns:
                try:
                    re.compile(pattern)
                except re.error as error:
                    raise ValueError(f"{topic.id}: {pattern!r}: {error}") from error
        return topics


class VerifiedEdition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    annotator: str = Field(min_length=1)
    record: str = Field(min_length=1)  # the verification record, relative to the repository
    note: str = ""


class ExcludedDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(pattern=r"^https://")
    reason: str = Field(min_length=1)


class RegisterSettings(BaseModel):
    """config/register.yaml: which annotations the public register shows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verified_editions: tuple[VerifiedEdition, ...] = ()
    # Documents kept in the database but never shown: an editorial decision, with why.
    excluded_documents: tuple[ExcludedDocument, ...] = ()

    @property
    def excluded_urls(self) -> frozenset[str]:
        return frozenset(d.url for d in self.excluded_documents)

    @property
    def verified_annotators(self) -> tuple[str, ...]:
        return tuple(edition.annotator for edition in self.verified_editions)


class Registry(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: tuple[Candidate, ...]
    sources: tuple[Source, ...]
    crawler: CrawlerSettings
    collection: CollectionSettings
    social: SocialSettings
    youtube: YoutubeSettings
    media: MediaSettings = MediaSettings()
    segmentation: SegmentationSettings
    taxonomy: TaxonomySettings
    watch: WatchSettings
    publication: RegisterSettings  # config/register.yaml
    scoring: ScoringSettings = ScoringSettings()  # config/scoring.yaml


class _CandidatesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[Candidate]


class _SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crawler: CrawlerSettings
    collection: CollectionSettings
    social: SocialSettings = SocialSettings()  # no social source: never read
    youtube: YoutubeSettings = YoutubeSettings()
    media: MediaSettings = MediaSettings()
    sources: list[Source]


def load_registry(config_dir: Path) -> Registry:
    candidates = _load(config_dir / "candidates.yaml", _CandidatesFile).candidates
    sources_file = _load(config_dir / "sources.yaml", _SourcesFile)
    _require_unique("candidate", [c.id for c in candidates])
    sources = [*sources_file.sources, *media_sources(sources_file.media, candidates)]
    _require_unique("source", [s.id for s in sources])
    _require_known_candidates(candidates, sources)
    taxonomy = _load(config_dir / "taxonomy.yaml", TaxonomySettings)
    _require_unique("dimension", taxonomy.dimension_ids)
    return Registry(
        candidates=tuple(candidates),
        sources=tuple(sources),
        crawler=sources_file.crawler,
        collection=sources_file.collection,
        social=sources_file.social,
        youtube=sources_file.youtube,
        media=sources_file.media,
        segmentation=_load(config_dir / "segmentation.yaml", SegmentationSettings),
        taxonomy=taxonomy,
        watch=_load(config_dir / "watch.yaml", WatchSettings),
        publication=_load(config_dir / "register.yaml", RegisterSettings),
        scoring=_load(config_dir / "scoring.yaml", ScoringSettings)
        if (config_dir / "scoring.yaml").is_file()
        else ScoringSettings(),
    )


def _load(path: Path, model: type[_Model]) -> _Model:
    try:
        return model.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise ConfigurationError(f"{path}: {error}") from error


def _require_unique(what: str, ids: Sequence[str]) -> None:
    repeated = sorted(i for i, n in Counter(ids).items() if n > 1)
    if repeated:
        raise ConfigurationError(f"duplicate {what} id(s): {', '.join(repeated)}")


def _require_known_candidates(candidates: Sequence[Candidate], sources: Sequence[Source]) -> None:
    known = {c.id for c in candidates}
    unknown = sorted({s.candidate_id for s in sources} - known)
    if unknown:
        raise ConfigurationError(f"sources reference unknown candidate(s): {', '.join(unknown)}")
