"""The public register: what the site shows, assembled from stored evidence only."""

from datetime import date

from pydantic import AwareDatetime, BaseModel, ConfigDict

from observatoire.domain.annotation import Dimension, DimensionAnnotation
from observatoire.domain.models import Candidate, RawDocument, Source


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RegisterCandidate(_Frozen):
    candidate: Candidate
    sources: tuple[Source, ...]  # enabled sources: what we are listening to

    @property
    def monitored(self) -> bool:
        """False: *non suivi*, which is not *aucune position identifiée*."""
        return bool(self.sources)


class RegisterEntry(_Frozen):
    """One statement with its provenance, attached from the stored document."""

    annotation: DimensionAnnotation
    document: RawDocument
    source: Source


class Register(_Frozen):
    generated_at: AwareDatetime
    window_start: date | None
    dimensions: tuple[Dimension, ...]
    candidates: tuple[RegisterCandidate, ...]
    entries: tuple[RegisterEntry, ...]
    annotator_version: str | None  # None when nothing has been annotated yet
    # Configured people left out because they withdrew (config/candidates.yaml).
    withdrawn: tuple[Candidate, ...] = ()
