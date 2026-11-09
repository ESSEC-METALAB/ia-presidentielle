"""Use case: what may need an editor today. Candidates and topics are proposed, never added.

- Candidates: an outside list of declarations is compared with config/candidates.yaml.
- Topics: subjects that are not axes are counted in the AI passages of the corpus.
- Passages: AI passages the current annotator found nothing in, and those still pending.
"""

import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date

import structlog

from observatoire.domain.annotation import published_annotations
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import Candidate, RawDocument, Segment, Source, in_window
from observatoire.domain.ports import (
    AnnotationReader,
    Clock,
    CorpusReader,
    RelevanceFilter,
    RosterSource,
    SegmentReader,
)
from observatoire.domain.watch import (
    CandidateLead,
    LeadKind,
    PassageExample,
    RosterEntry,
    TopicSignal,
    WatchedTopic,
    WatchReport,
)
from observatoire.services.dedup import content_hash

_log = structlog.get_logger(__name__)
_EXCERPT_CHARS = 160
_EXAMPLES = 3


@dataclass(frozen=True)
class _Passage:
    segment: Segment
    document: RawDocument


def _key(name: str) -> str:
    """Accents, case and punctuation aside: "Édouard Philippe" == "edouard philippe"."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z ]", " ", plain.casefold()).split())


def _excerpt(passage: _Passage, start: int = 0) -> PassageExample:
    text = passage.segment.text
    begin = max(0, start - _EXCERPT_CHARS // 4)
    snippet = text[begin : begin + _EXCERPT_CHARS].strip()
    return PassageExample(
        candidate_id=passage.document.candidate_id,
        url=passage.document.url,
        excerpt=("…" if begin else "")
        + snippet
        + ("…" if begin + _EXCERPT_CHARS < len(text) else ""),
    )


class WatchChanges:
    def __init__(
        self,
        *,
        roster: RosterSource,
        corpus: CorpusReader,
        segments: SegmentReader,
        annotations: AnnotationReader,
        relevance: RelevanceFilter,
        clock: Clock,
    ) -> None:
        self._roster = roster
        self._corpus = corpus
        self._segments = segments
        self._annotations = annotations
        self._relevance = relevance
        self._clock = clock

    def run(
        self,
        candidates: Sequence[Candidate],
        sources: Sequence[Source],
        topics: Sequence[WatchedTopic],
        *,
        threshold: int,
        min_candidates: int = 1,
        since: date | None = None,
        verified: Sequence[str] = (),
    ) -> WatchReport:
        """Topics and passages count running candidates only, as the register shows them."""
        leads, roster_error = self._candidate_leads(candidates)
        running = {c.id for c in candidates if c.on_register}
        passages = [
            p
            for p in self._passages(running, sources, since)
            if self._relevance.is_relevant(p.segment.text)
        ]
        pending, empty = self._annotation_state(passages, verified)
        return WatchReport(
            generated_at=self._clock.now(),
            roster_label=self._roster.label,
            roster_error=roster_error,
            candidate_leads=leads,
            topic_signals=tuple(_signal(topic, passages) for topic in topics),
            topic_threshold=threshold,
            topic_min_candidates=min_candidates,
            ai_passages=len(passages),
            pending_passages=pending,
            empty_passages=empty,
        )

    def _candidate_leads(
        self, candidates: Sequence[Candidate]
    ) -> tuple[tuple[CandidateLead, ...], str | None]:
        try:
            entries = self._roster.fetch()
        except SourceUnavailableError as error:
            _log.warning("roster_unavailable", error=str(error))
            return (), str(error)
        return tuple(_leads(candidates, entries)), None

    def _passages(
        self, people: set[str], sources: Sequence[Source], since: date | None
    ) -> Iterator[_Passage]:
        configured = {s.id for s in sources if s.candidate_id in people}
        documents = {
            d.content_hash: d
            for d in self._corpus.list_documents()
            if d.source_id in configured and in_window(d.published_on, since)
        }
        for segmentation in sorted(
            self._segments.list_segmentations(), key=lambda s: s.document_hash
        ):
            document = documents.get(segmentation.document_hash)
            if document is not None:
                yield from (_Passage(segment, document) for segment in segmentation.segments)

    def _annotation_state(
        self, passages: Sequence[_Passage], verified: Sequence[str]
    ) -> tuple[int, tuple[PassageExample, ...]]:
        """Pending and empty against what the register shows (`published_annotations`)."""
        hashes = {p.segment.id: content_hash(p.segment.text) for p in passages}
        shown = published_annotations(self._annotations.list_annotations(), hashes, verified)
        pending, empty = 0, []
        for passage in passages:
            annotation = shown.get(passage.segment.id)
            if annotation is None:
                pending += 1
            elif annotation.is_empty:
                empty.append(_excerpt(passage))
        return pending, tuple(empty)


def _leads(
    candidates: Sequence[Candidate], entries: Sequence[RosterEntry]
) -> Iterator[CandidateLead]:
    ours = {_key(name): c for c in candidates for name in (c.name, *c.aliases)}
    for entry in entries:
        listed = ours.get(_key(entry.name))
        if entry.withdrawn_on is None and entry.declared_on is not None and listed is None:
            yield CandidateLead(
                kind=LeadKind.DECLARED_NOT_LISTED,
                name=entry.name,
                party=entry.party,
                on=entry.declared_on,
            )
        elif entry.withdrawn_on is not None and listed is not None and listed.is_running:
            yield CandidateLead(
                kind=LeadKind.WITHDRAWN_BUT_LISTED,
                name=entry.name,
                party=entry.party,
                on=entry.withdrawn_on,
            )
        elif _declared_again(entry, listed):
            yield CandidateLead(
                kind=LeadKind.DECLARED_BUT_WITHDRAWN_HERE,
                name=entry.name,
                party=entry.party,
                on=entry.declared_on,
            )


def _declared_again(entry: RosterEntry, listed: Candidate | None) -> bool:
    """Withdrawn in our roster, declared (later) and not withdrawn in the outside list."""
    if listed is None or listed.is_running or entry.declared_on is None or entry.withdrawn_on:
        return False
    ours = listed.candidacy.since if listed.candidacy else None
    return ours is None or entry.declared_on > ours


def _signal(topic: WatchedTopic, passages: Sequence[_Passage]) -> TopicSignal:
    pattern = re.compile("|".join(f"(?:{p})" for p in topic.patterns), re.IGNORECASE)
    hits = [(p, m.start()) for p in passages if (m := pattern.search(p.segment.text))]
    examples: dict[tuple[str, str], PassageExample] = {}
    for passage, start in hits:
        example = _excerpt(passage, start)
        examples.setdefault((example.url, example.excerpt), example)
    return TopicSignal(
        topic=topic,
        passages=len(hits),
        candidates=tuple(sorted({p.document.candidate_id for p, _ in hits})),
        examples=tuple(examples.values())[:_EXAMPLES],
    )
