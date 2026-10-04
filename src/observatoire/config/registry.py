"""Loads and validates config/*.yaml into domain models."""

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from observatoire.domain.errors import ConfigurationError
from observatoire.domain.models import Candidate, Source

_Model = TypeVar("_Model", bound=BaseModel)


class CrawlerSettings(BaseModel):
    """The crawler's identity and manners (CLAUDE.md §7). Not secret: versioned config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_agent: str = Field(min_length=10)
    min_delay_seconds: float = Field(ge=0)
    timeout_seconds: float = Field(gt=0)
    min_text_chars: int = Field(ge=0)
    max_redirects: int = Field(ge=0, le=10)


class Registry(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: tuple[Candidate, ...]
    sources: tuple[Source, ...]
    crawler: CrawlerSettings


class _CandidatesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[Candidate]


class _SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crawler: CrawlerSettings
    sources: list[Source]


def load_registry(config_dir: Path) -> Registry:
    candidates = _load(config_dir / "candidates.yaml", _CandidatesFile).candidates
    sources_file = _load(config_dir / "sources.yaml", _SourcesFile)
    _require_unique("candidate", [c.id for c in candidates])
    _require_unique("source", [s.id for s in sources_file.sources])
    _require_known_candidates(candidates, sources_file.sources)
    return Registry(
        candidates=tuple(candidates),
        sources=tuple(sources_file.sources),
        crawler=sources_file.crawler,
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
