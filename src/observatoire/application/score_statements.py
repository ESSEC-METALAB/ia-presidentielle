"""Scores each statement on the register on the scales of config/scoring.yaml.

The scorer proposes; code decides. A score is kept only when its evidence (words of the
quote) is found in the quote; otherwise it is dropped and the scale is named in
`dropped`. Each statement is scored once per scorer version, several calls at a time.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

import structlog
from pydantic import BaseModel, ConfigDict

from observatoire.application.frame_statements import evidence_in_quote
from observatoire.domain.annotation import framing_key
from observatoire.domain.errors import AnnotationUnavailableError, MalformedAnnotationError
from observatoire.domain.ports import Clock, Scorer, ScoreStore
from observatoire.domain.register import RegisterEntry
from observatoire.domain.scoring import ScaleScore, ScoreDraft, StatementScore

_log = structlog.get_logger(__name__)


class ScoringReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    scorer_version: str
    statements: int
    already_scored: int
    scored: int
    kept: Mapping[str, int]  # scale -> scores kept
    dropped: Mapping[str, int]  # scale -> scores dropped (evidence not in the quote)
    failed: int
    pending: int


class ScoreStatements:
    def __init__(
        self,
        scorer: Scorer,
        store: ScoreStore,
        clock: Clock,
        *,
        scales: Sequence[str],
        workers: int = 24,
    ) -> None:
        self._scorer = scorer
        self._store = store
        self._clock = clock
        self._scales = tuple(scales)
        self._workers = workers

    def run(
        self,
        entries: Sequence[RegisterEntry],
        speakers: Mapping[str, str],
        axes: Mapping[str, str],
        *,
        limit: int | None = None,
    ) -> ScoringReport:
        done = self._store.scored_keys(self._scorer.version)
        keyed = {framing_key(e.annotation.segment_id, e.annotation.quote): e for e in entries}
        todo = {key: entry for key, entry in keyed.items() if key not in done}
        chosen = list(todo.items())[: limit if limit is not None else None]
        kept: Counter[str] = Counter()
        dropped: Counter[str] = Counter()
        scored = failed = 0
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {
                pool.submit(
                    self._scorer.score,
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
                    _log.warning("scoring_failed", key=key, error=str(error))
                    continue
                result = self._reviewed(key, draft, entry.annotation.quote)
                self._store.save_score(result)
                scored += 1
                kept.update(s.scale for s in result.scores)
                dropped.update(result.dropped)
        return ScoringReport(
            scorer_version=self._scorer.version,
            statements=len(keyed),
            already_scored=len(keyed) - len(todo),
            scored=scored,
            kept=dict(kept),
            dropped=dict(dropped),
            failed=failed,
            pending=len(todo) - len(chosen),
        )

    def _reviewed(self, key: str, draft: ScoreDraft, quote: str) -> StatementScore:
        scores: list[ScaleScore] = []
        dropped: list[str] = []
        seen: set[str] = set()
        for proposal in draft.scores:
            if proposal.scale not in self._scales or proposal.scale in seen:
                continue
            seen.add(proposal.scale)
            if proposal.score is None:
                continue
            if not evidence_in_quote(proposal.evidence, quote):
                dropped.append(proposal.scale)
                continue
            scores.append(
                ScaleScore(
                    scale=proposal.scale,
                    score=proposal.score,
                    reason_fr=proposal.reason_fr,
                    reason_en=proposal.reason_en,
                    evidence=proposal.evidence,
                )
            )
        return StatementScore(
            key=key,
            scorer_version=self._scorer.version,
            scored_at=self._clock.now(),
            scores=tuple(scores),
            dropped=tuple(dropped),
        )
