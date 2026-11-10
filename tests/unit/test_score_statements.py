"""The scoring step, on fictional statements, with a scripted scorer."""

from datetime import UTC, datetime
from pathlib import Path

from observatoire.adapters.llm.llm_scorer import LLMScorer
from observatoire.application.build_register import _scored
from observatoire.application.score_statements import ScoreStatements
from observatoire.config.registry import load_registry
from observatoire.domain.annotation import DimensionAnnotation, framing_key
from observatoire.domain.errors import AnnotationUnavailableError
from observatoire.domain.register import RegisterEntry
from observatoire.domain.scoring import ScaleDraft, ScaleScore, ScoreDraft, StatementScore
from support import FrozenClock, document, source

CONFIG = Path(__file__).resolve().parents[2] / "config"
QUOTE = "Nous investirons 10 milliards d'euros dans l'IA d'ici 2030."


class _Store:
    def __init__(self) -> None:
        self.saved: list[StatementScore] = []

    def scored_keys(self, scorer_version: str) -> set[str]:
        return {s.key for s in self.saved if s.scorer_version == scorer_version}

    def save_score(self, score: StatementScore) -> None:
        self.saved.append(score)


class _Scorer:
    def __init__(self, answer: ScoreDraft | Exception, version: str = "s1") -> None:
        self._answer = answer
        self.version = version
        self.asked = 0

    def score(self, entry: RegisterEntry, speaker: str, axis: str) -> ScoreDraft:
        self.asked += 1
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _entry(quote: str = QUOTE) -> RegisterEntry:
    statement = DimensionAnnotation(
        segment_id="abc-000",
        index=0,
        dimension="financement",
        quote=quote,
        quote_span=(0, len(quote)),
        summary_fr="Résumé.",
        summary_en="Summary.",
        context_fr="Contexte.",
        context_en="Context.",
        gloss_en="Gloss.",
    )
    return RegisterEntry(
        annotation=statement, document=document(quote), source=source(), annotator_version="v1"
    )


def _run(scorer: _Scorer, store: _Store) -> None:
    ScoreStatements(
        scorer, store, FrozenClock(), scales=("orientation", "concreteness"), workers=2
    ).run([_entry()], {}, {})


def _draft(scale: str, score: int | None, evidence: str) -> ScaleDraft:
    return ScaleDraft(
        scale=scale, score=score, reason_fr="Propose.", reason_en="Proposes.", evidence=evidence
    )


def test_a_score_is_kept_with_its_reason_when_its_evidence_is_in_the_quote() -> None:
    store = _Store()
    answer = ScoreDraft(
        scores=(
            _draft("orientation", 5, "investirons 10 milliards"),
            _draft("concreteness", 5, "d'ici 2030"),
        )
    )

    _run(_Scorer(answer), store)

    (saved,) = store.saved
    assert [(s.scale, s.score) for s in saved.scores] == [("orientation", 5), ("concreteness", 5)]
    assert saved.scores[0].reason_fr == "Propose."
    assert saved.key == framing_key("abc-000", QUOTE)


def test_a_score_whose_evidence_is_not_in_the_quote_is_dropped() -> None:
    store = _Store()
    answer = ScoreDraft(
        scores=(_draft("orientation", 1, "interdire l'IA"), _draft("concreteness", 4, "2030"))
    )

    _run(_Scorer(answer), store)

    (saved,) = store.saved
    assert [s.scale for s in saved.scores] == ["concreteness"]
    assert saved.dropped == ("orientation",)


def test_a_scale_that_does_not_apply_and_an_unknown_scale_are_left_empty() -> None:
    store = _Store()
    answer = ScoreDraft(scores=(_draft("orientation", None, ""), _draft("tonalite", 3, "IA")))

    _run(_Scorer(answer), store)

    assert store.saved[0].scores == ()


def test_scored_once_per_version_and_tried_again_after_no_answer() -> None:
    store = _Store()
    failing = _Scorer(AnnotationUnavailableError("timeout"))
    _run(failing, store)
    answering = _Scorer(ScoreDraft(scores=()))
    _run(answering, store)
    again = _Scorer(ScoreDraft(scores=()))
    _run(again, store)

    assert (failing.asked, answering.asked, again.asked) == (1, 1, 0)


def test_the_register_shows_the_latest_scores() -> None:
    key = framing_key("abc-000", QUOTE)
    old = StatementScore(
        key=key, scorer_version="s1", scored_at=datetime(2026, 11, 1, tzinfo=UTC), scores=()
    )
    new = old.model_copy(
        update={
            "scorer_version": "s2",
            "scored_at": datetime(2026, 11, 2, tzinfo=UTC),
            "scores": (
                ScaleScore(
                    scale="orientation", score=4, reason_fr="R", reason_en="R", evidence="IA"
                ),
            ),
        }
    )

    (shown,) = _scored((_entry(),), [new, old])

    assert [s.score for s in shown.scores] == [4]


def test_the_scales_of_the_configuration_are_written_into_the_prompt() -> None:
    class _Client:
        model = "m"

    scales = load_registry(CONFIG).scoring.scales
    scorer = LLMScorer(_Client(), scales)  # type: ignore[arg-type]

    assert {s.id for s in scales} == {"orientation", "concreteness"}
    assert all(set(s.anchors) <= set(load_registry(CONFIG).taxonomy.dimension_ids) for s in scales)
    assert "`emploi`" in scorer._system
    assert "{scales}" not in scorer._system
