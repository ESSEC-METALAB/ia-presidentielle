"""The framing step: opportunity or threat, on fictional statements, with a scripted framer."""

from datetime import UTC, datetime

from observatoire.application.frame_statements import (
    EVIDENCE_NOT_IN_QUOTE,
    FrameStatements,
)
from observatoire.domain.annotation import (
    DimensionAnnotation,
    Framing,
    FramingDraft,
    StatementFraming,
    framing_key,
)
from observatoire.domain.errors import AnnotationUnavailableError
from observatoire.domain.register import RegisterEntry
from support import FrozenClock, document, source


class _Store:
    def __init__(self) -> None:
        self.saved: list[StatementFraming] = []

    def framed_keys(self, framer_version: str) -> set[str]:
        return {f.key for f in self.saved if f.framer_version == framer_version}

    def save_framing(self, framing: StatementFraming) -> None:
        self.saved.append(framing)


class _Framer:
    """Answers from a script keyed by quote; records what it was asked."""

    def __init__(self, answers: dict[str, FramingDraft | Exception], version: str = "f1") -> None:
        self._answers = answers
        self.version = version
        self.asked: list[tuple[str, str, str]] = []

    def frame(self, entry: RegisterEntry, speaker: str, axis_label: str) -> FramingDraft:
        self.asked.append((entry.annotation.quote, speaker, axis_label))
        answer = self._answers.get(entry.annotation.quote, FramingDraft(framing=Framing.NONE))
        if isinstance(answer, Exception):
            raise answer
        return answer


def _entry(quote: str, index: int = 0) -> RegisterEntry:
    statement = DimensionAnnotation(
        segment_id="abc-000",
        index=index,
        dimension="emploi",
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


def _run(framer: _Framer, store: _Store, *entries: RegisterEntry) -> None:
    FrameStatements(framer, store, FrozenClock(), workers=2).run(
        entries, {"camille-exemple": "Camille Exemple"}, {"emploi": "Jobs"}
    )


def test_a_framing_stands_on_words_of_the_quote() -> None:
    quote = "L'IA va supprimer des millions d'emplois."
    store = _Store()
    framer = _Framer(
        {
            quote: FramingDraft(
                framing=Framing.THREAT, evidence="supprimer des millions d\u2019emplois"
            )
        }
    )

    _run(framer, store, _entry(quote))

    (saved,) = store.saved
    assert (saved.framing, saved.rejected) == (Framing.THREAT, None)
    assert saved.key == framing_key("abc-000", quote)
    assert framer.asked == [(quote, "Camille Exemple", "Jobs")]


def test_evidence_not_in_the_quote_leaves_the_statement_unframed() -> None:
    quote = "Nous créerons un cloud souverain."
    store = _Store()
    framer = _Framer({quote: FramingDraft(framing=Framing.OPPORTUNITY, evidence="une chance")})

    _run(framer, store, _entry(quote))

    (saved,) = store.saved
    assert (saved.framing, saved.rejected) == (Framing.NONE, EVIDENCE_NOT_IN_QUOTE)


def test_a_statement_is_framed_once_per_framer_version() -> None:
    store = _Store()
    entry = _entry("L'IA est une chance.")

    _run(_Framer({}), store, entry)
    again = _Framer({})
    _run(again, store, entry)
    newer = _Framer({}, version="f2")
    _run(newer, store, entry)

    assert again.asked == []
    assert len(newer.asked) == 1


def test_no_answer_is_tried_again_next_time() -> None:
    quote = "L'IA est une chance."
    store = _Store()

    _run(_Framer({quote: AnnotationUnavailableError("timeout")}), store, _entry(quote))

    assert store.saved == []


def test_the_register_shows_each_statements_latest_framing() -> None:
    from observatoire.application.build_register import _framed

    entry = _entry("L'IA est une chance.")
    key = framing_key("abc-000", "L'IA est une chance.")
    older = StatementFraming(
        key=key,
        framer_version="f1",
        framed_at=datetime(2026, 11, 1, tzinfo=UTC),
        framing=Framing.NONE,
    )
    newer = older.model_copy(
        update={
            "framer_version": "f2",
            "framed_at": datetime(2026, 11, 2, tzinfo=UTC),
            "framing": Framing.OPPORTUNITY,
        }
    )

    (shown,) = _framed((entry,), [newer, older])
    (unframed,) = _framed((entry,), [])

    assert shown.framing == Framing.OPPORTUNITY
    assert unframed.framing is None
