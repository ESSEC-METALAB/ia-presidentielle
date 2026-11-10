"""Says, for each statement on the register, whether it presents AI as an opportunity,
a threat, both, or neither (the "Opportunité / Menace" column of the barometer).

The framer proposes; code decides. A framing other than *none* must rest on words of
the quote itself, found by code; otherwise it is stored as *none*, with the reason. Each
statement is framed once per framer version. Calls run a few at a time: the model takes
tens of seconds per answer, and the answers are written one by one as they come.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

import structlog
from pydantic import BaseModel, ConfigDict

from observatoire.domain.annotation import Framing, FramingDraft, StatementFraming, framing_key
from observatoire.domain.errors import AnnotationUnavailableError, MalformedAnnotationError
from observatoire.domain.ports import Clock, Framer, FramingStore
from observatoire.domain.register import RegisterEntry

_log = structlog.get_logger(__name__)
EVIDENCE_NOT_IN_QUOTE = "evidence_not_in_quote"


class FramingReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    framer_version: str
    statements: int  # on the register
    already_framed: int
    framed: Mapping[Framing, int]
    rejected: int  # evidence not found in the quote: stored as none
    failed: int  # no usable answer; tried again on the next run
    pending: int  # left for a later run by --limit


class FrameStatements:
    def __init__(self, framer: Framer, store: FramingStore, clock: Clock, workers: int = 4) -> None:
        self._framer = framer
        self._store = store
        self._clock = clock
        self._workers = workers

    def run(
        self,
        entries: Sequence[RegisterEntry],
        speakers: Mapping[str, str],
        axes: Mapping[str, str],
        *,
        limit: int | None = None,
    ) -> FramingReport:
        """`speakers`: candidate id -> name; `axes`: dimension id -> label."""
        done = self._store.framed_keys(self._framer.version)
        keyed = {framing_key(e.annotation.segment_id, e.annotation.quote): e for e in entries}
        todo = {key: entry for key, entry in keyed.items() if key not in done}
        chosen = list(todo.items())[: limit if limit is not None else None]
        framed: Counter[Framing] = Counter()
        rejected = failed = 0
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {
                pool.submit(
                    self._framer.frame,
                    entry,
                    speakers.get(entry.document.candidate_id, entry.document.candidate_id),
                    axes.get(entry.annotation.dimension, entry.annotation.dimension),
                ): (key, entry)
                for key, entry in chosen
            }
            for future in as_completed(futures):
                key, entry = futures[future]
                try:
                    draft = future.result()
                except (AnnotationUnavailableError, MalformedAnnotationError) as error:
                    failed += 1
                    _log.warning("framing_failed", key=key, error=str(error))
                    continue
                framing = self._reviewed(key, draft, entry.annotation.quote)
                self._store.save_framing(framing)
                framed[framing.framing] += 1
                rejected += framing.rejected is not None
        return FramingReport(
            framer_version=self._framer.version,
            statements=len(keyed),
            already_framed=len(keyed) - len(todo),
            framed=dict(framed),
            rejected=rejected,
            failed=failed,
            pending=len(todo) - len(chosen),
        )

    def _reviewed(self, key: str, draft: FramingDraft, quote: str) -> StatementFraming:
        kept, reason = draft.framing, None
        if draft.framing != Framing.NONE and not _found(draft.evidence, quote):
            kept, reason = Framing.NONE, EVIDENCE_NOT_IN_QUOTE
        return StatementFraming(
            key=key,
            framer_version=self._framer.version,
            framed_at=self._clock.now(),
            framing=kept,
            evidence=draft.evidence if kept != Framing.NONE or reason else "",
            rejected=reason,
        )


def _normal(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u2019", "'").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip().casefold()


def _found(evidence: str, quote: str) -> bool:
    words = _normal(evidence)
    return bool(words) and words in _normal(quote)
