"""Single source of truth for the claim shape.

This module serves two masters and must keep them in step:

1. ``ExtractionResult.model_json_schema()`` is the JSON Schema handed to
   Claude as the structured-output contract.
2. ``Claim.model_validate()`` is the build-time gate before rendering.

Changing a field here changes both, which is the point.
"""

from __future__ import annotations

import hashlib
from datetime import date as Date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Courte citation (art. L122-5 3°a CPI) requires the quote be short and
# justified by the informational purpose. 40 words is the spec's ceiling and
# is enforced here rather than left to convention.
MAX_QUOTE_WORDS = 40


class Axis(StrEnum):
    """The six policy axes. Adding one is a config change plus a backfill."""

    REGULATION = "regulation"
    SOUVERAINETE = "souverainete"
    EMPLOI_FORMATION = "emploi-formation"
    SERVICES_PUBLICS = "services-publics"
    SURVEILLANCE_LIBERTES = "surveillance-libertes"
    FINANCEMENT = "financement"


class ClaimType(StrEnum):
    PROGRAMME = "programme"
    DISCOURS = "discours"
    VOTE = "vote"
    INTERVIEW = "interview"
    VIDEO = "video"
    POST = "post"


class Tier(StrEnum):
    """Whose words, not who hosts. A speech is tier 1 wherever it is published."""

    OWN_WORDS = "1"
    PARTY_OR_STAFF = "2"
    PRESS = "3"


class Status(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    CORRECTED = "corrected"
    RETRACTED = "retracted"


class ExtractedClaim(BaseModel):
    """What the model returns. Provenance fields are added by the pipeline,
    never by the model — it cannot be trusted to report where it read something.
    """

    # No use_enum_values: enum fields stay enums, matching Document. StrEnum
    # members compare and serialise as their value, so nothing downstream
    # needs to care — but `claim.tier` and `document.tier` are now the same
    # kind of thing, which they were not.
    model_config = ConfigDict(extra="forbid")

    axis: Axis = Field(description="Which of the six policy axes this position belongs to.")
    claim_type: ClaimType = Field(
        description="The kind of source this came from: a written programme, a speech, "
        "a recorded parliamentary vote, an interview, a video, or a social post."
    )
    date: Date | None = Field(
        description="Date the statement was made, in YYYY-MM-DD form, taken from "
        "the document itself. Return null if the document does not say. Never "
        "guess and never use today's date.",
    )
    quote_fr: str = Field(
        description=(
            f"The speaker's own words, copied EXACTLY from the source, in French, "
            f"at most {MAX_QUOTE_WORDS} words. Never paraphrase, correct, translate "
            f"or tidy this. It is checked character-for-character against the source "
            f"and the claim is rejected if it does not match."
        )
    )
    quote_gloss_en: str = Field(
        description="A plain English translation of quote_fr, shown beside the French "
        "on English pages. This is a reading aid, never a substitute for the quote."
    )
    position_fr: str = Field(
        description="One neutral French sentence stating what was committed to. "
        "Describe, never evaluate: no adjectives of judgement."
    )
    position_en: str = Field(description="The same neutral sentence in English.")
    contexte_fr: str = Field(
        description="One or two French sentences explaining what the position means "
        "in practice — e.g. naming the scheme, body or standard referred to. "
        "Explanatory, never evaluative."
    )
    contexte_en: str = Field(description="The same explanation in English.")

    @field_validator("quote_fr")
    @classmethod
    def _quote_is_short_and_present(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("quote_fr is empty; a claim without the speaker's words is not publishable")
        words = len(v.split())
        if words > MAX_QUOTE_WORDS:
            raise ValueError(
                f"quote_fr is {words} words; courte citation (L122-5 3°a) caps it at {MAX_QUOTE_WORDS}"
            )
        return v

    @field_validator("position_fr", "position_en", "contexte_fr", "contexte_en", "quote_gloss_en")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field is blank; every claim carries both languages")
        return v.strip()


class ExtractionResult(BaseModel):
    """The model's whole answer for one document.

    An empty ``claims`` list is the expected answer for most documents and is
    the primary control against invented policy positions.
    """

    model_config = ConfigDict(extra="forbid")

    claims: list[ExtractedClaim] = Field(
        default_factory=list,
        description="Every AI-policy position the named person states in this document. "
        "Return an empty list if the document contains none — that is a correct and "
        "common answer. Never infer a position that is not stated.",
    )


class Claim(ExtractedClaim):
    """A stored, renderable claim: what the model extracted plus provenance."""

    person: str = Field(description="Person slug, e.g. 'bruno-retailleau'.")
    party: str
    tier: Tier
    tier_confirmed: bool = Field(
        default=False,
        description="False means the tier is the source's declared default, not a "
        "judgement about this document. A party site publishes both its own "
        "communiqués (tier 2) and the candidate's own speeches (tier 1), and no "
        "per-source setting can tell them apart. Only the editor can, at review.",
    )
    source_url: str
    archive_url: str | None = Field(
        default=None, description="Wayback snapshot captured at ingest."
    )
    timestamp_s: int | None = Field(
        default=None, description="Seconds into the video; makes the citation a deep link."
    )
    last_verified: Date
    status: Status = Status.PENDING

    @property
    def id(self) -> str:
        """Stable across re-runs: the same quote from the same URL is the same claim."""
        return hashlib.sha256(f"{self.source_url}\n{self.quote_fr}".encode()).hexdigest()[:16]

    @model_validator(mode="after")
    def _timestamp_only_for_video(self) -> Claim:
        if self.timestamp_s is not None and self.claim_type != ClaimType.VIDEO:
            raise ValueError(
                f"timestamp_s set on a {self.claim_type} claim; it only means something for video"
            )
        if self.timestamp_s is not None and self.timestamp_s < 0:
            raise ValueError("timestamp_s cannot be negative")
        return self

    def citation_url(self) -> str:
        """The link a reader clicks to check the quote themselves."""
        if self.claim_type == ClaimType.VIDEO and self.timestamp_s is not None:
            sep = "&" if "?" in self.source_url else "?"
            return f"{self.source_url}{sep}t={self.timestamp_s}"
        return self.source_url


def _inline_refs(node: object, defs: dict) -> object:
    """Replace every ``$ref`` with the definition it points at.

    Pydantic emits ``{"$ref": ..., "description": ...}`` for enum-typed fields.
    Under draft-07 semantics a ``$ref``'s siblings are ignored, which would
    silently drop the field descriptions — and those descriptions are most of
    what steers the model. Inlining removes the ambiguity.
    """
    if isinstance(node, list):
        return [_inline_refs(n, defs) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target = defs[node["$ref"].rsplit("/", 1)[-1]]
        merged = {**_inline_refs(target, defs), **{k: v for k, v in node.items() if k != "$ref"}}
        return merged
    return {k: _inline_refs(v, defs) for k, v in node.items()}


# Strict structured-output modes accept a restricted keyword set. `format` in
# particular is rejected, and the rest are annotations the model does not need
# — dropping them also trims the schema the model has to read.
_UNSUPPORTED = frozenset({
    "format", "title", "default", "examples", "pattern",
    "minLength", "maxLength", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minItems", "maxItems", "uniqueItems",
})


def _collapse_nullable(node: dict) -> dict:
    """Rewrite ``anyOf: [{type: X}, {type: null}]`` as ``type: [X, "null"]``.

    Both express a required-but-nullable field. OpenAI's own strict-mode
    examples use the type-array form, while ``anyOf`` support is not documented
    either way, so we emit the form they show.
    """
    any_of = node.get("anyOf")
    if not (isinstance(any_of, list) and len(any_of) == 2):
        return node
    types = [m.get("type") for m in any_of if isinstance(m, dict)]
    if "null" not in types or len(types) != 2:
        return node
    other = next(t for t in types if t != "null")
    return {**{k: v for k, v in node.items() if k != "anyOf"}, "type": [other, "null"]}


def _strip(node: object) -> object:
    if isinstance(node, list):
        return [_strip(n) for n in node]
    if isinstance(node, dict):
        cleaned = {k: _strip(v) for k, v in node.items() if k not in _UNSUPPORTED}
        return _collapse_nullable(cleaned)
    return node


def llm_json_schema() -> dict:
    """The structured-output contract. Flat, no ``$ref``, no keywords a strict
    mode would reject. Provider-neutral: the same object drives OpenAI's
    ``strict: true`` and Claude's ``output_config.format``.
    """
    schema = ExtractionResult.model_json_schema()
    defs = schema.pop("$defs", {})
    return _strip(_inline_refs(schema, defs))  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Pipeline shapes. Not part of the model contract — these are what fetch.py
# produces and extract.py consumes.
# --------------------------------------------------------------------------


class Cue(BaseModel):
    """One line of transcript with the second it starts at."""

    t: int
    line: str


class Document(BaseModel):
    """Normalised fetch output. Every source type collapses to this shape, so
    nothing downstream needs to know where the text came from.

    Tier 1-2 only. Tier 3 becomes a :class:`Lead` instead.
    """

    model_config = ConfigDict(extra="forbid")

    person: str
    source_id: str
    kind: str
    tier: Tier
    url: str
    text: str
    title: str | None = None
    date: Date | None = None
    archive_url: str | None = None
    fingerprint: str | None = Field(
        default=None, description="trafilatura content hash, for near-duplicate detection"
    )
    cues: list[Cue] | None = Field(
        default=None, description="Video only. Needed to turn an extracted quote into a timestamp."
    )

    @property
    def url_hash(self) -> str:
        """Dedup key. Includes the content fingerprint when one is available,
        so a standing page that gets rewritten — a candidate's priorities page,
        a corrected article — is re-read rather than silently skipped forever.
        trafilatura fingerprints the extracted text, not the boilerplate, so
        this does not churn on ads or timestamps.
        """
        key = self.url if self.fingerprint is None else f"{self.url}\n{self.fingerprint}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


class Lead(BaseModel):
    """A tier-3 sighting: something was published, we could not or should not
    ingest its body. Surfaced to the editor as a question, never auto-published.
    """

    model_config = ConfigDict(extra="forbid")

    person: str
    source_id: str
    title: str
    url: str
    publisher: str | None = None
    date: Date | None = None
    reason: str = Field(
        default="tier-3",
        description="Why this is a lead and not a document: press, paywall, or multi-speaker video.",
    )

    @property
    def url_hash(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]
