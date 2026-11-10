"""The public register: what the site shows, assembled from stored evidence only."""

from datetime import date

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from observatoire.domain.annotation import Dimension, DimensionAnnotation
from observatoire.domain.models import Candidate, RawDocument, Source


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RegisterCandidate(_Frozen):
    candidate: Candidate
    sources: tuple[Source, ...]  # enabled sources: what we are listening to
    # Disabled sources whose stored texts are still on the register: no longer read,
    # but what they gave is shown, so they are listed too.
    stopped: tuple[Source, ...] = ()

    @property
    def monitored(self) -> bool:
        """False: *non suivi*, which is not *aucune position identifiée*."""
        return bool(self.sources)


class RegisterEntry(_Frozen):
    """One statement with its provenance, attached from the stored document."""

    annotation: DimensionAnnotation
    document: RawDocument
    source: Source
    annotator_version: str
    # From a cross-verified edition (config/register.yaml), not only the automatic gates.
    verified: bool = False


class Register(_Frozen):
    generated_at: AwareDatetime
    window_start: date | None
    dimensions: tuple[Dimension, ...]
    candidates: tuple[RegisterCandidate, ...]
    entries: tuple[RegisterEntry, ...]
    # Annotators whose work is shown, verified editions first; empty before any annotation.
    annotators: tuple[str, ...] = ()
    # Current AI passages nobody has annotated yet, per candidate id: until they are, an
    # empty cell for that candidate means "en attente", not "aucune position identifiée".
    pending: dict[str, int] = Field(default_factory=dict)
    # Configured people left off the register (config/candidates.yaml, `shown`).
    left_out: tuple[Candidate, ...] = ()
    # Texts read in the window, per source id: what a source gave us, statements or not.
    documents: dict[str, int] = Field(default_factory=dict)
