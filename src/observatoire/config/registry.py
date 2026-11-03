"""Loads and validates config/*.yaml into domain models."""

import re
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from observatoire.domain.annotation import Dimension
from observatoire.domain.errors import ConfigurationError
from observatoire.domain.models import Candidate, Source
from observatoire.domain.watch import WatchedTopic
from observatoire.services.ai_relevance import RelevanceSettings
from observatoire.services.annotation_gates import GateSettings
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
    """What period the corpus covers. Texts published before `since` are not collected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    since: date


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


class RegisterSettings(BaseModel):
    """config/register.yaml: which annotations the public register shows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verified_editions: tuple[VerifiedEdition, ...] = ()

    @property
    def verified_annotators(self) -> tuple[str, ...]:
        return tuple(edition.annotator for edition in self.verified_editions)


class Registry(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: tuple[Candidate, ...]
    sources: tuple[Source, ...]
    crawler: CrawlerSettings
    collection: CollectionSettings
    segmentation: SegmentationSettings
    taxonomy: TaxonomySettings
    watch: WatchSettings
    publication: RegisterSettings  # config/register.yaml


class _CandidatesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[Candidate]


class _SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crawler: CrawlerSettings
    collection: CollectionSettings
    sources: list[Source]


def load_registry(config_dir: Path) -> Registry:
    candidates = _load(config_dir / "candidates.yaml", _CandidatesFile).candidates
    sources_file = _load(config_dir / "sources.yaml", _SourcesFile)
    _require_unique("candidate", [c.id for c in candidates])
    _require_unique("source", [s.id for s in sources_file.sources])
    _require_known_candidates(candidates, sources_file.sources)
    taxonomy = _load(config_dir / "taxonomy.yaml", TaxonomySettings)
    _require_unique("dimension", taxonomy.dimension_ids)
    return Registry(
        candidates=tuple(candidates),
        sources=tuple(sources_file.sources),
        crawler=sources_file.crawler,
        collection=sources_file.collection,
        segmentation=_load(config_dir / "segmentation.yaml", SegmentationSettings),
        taxonomy=taxonomy,
        watch=_load(config_dir / "watch.yaml", WatchSettings),
        publication=_load(config_dir / "register.yaml", RegisterSettings),
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
