"""AnnotateDocuments with an in-memory store and a scripted annotator. Fictional texts."""

from datetime import date

from observatoire.application.annotate_documents import AnnotateDocuments
from observatoire.domain.annotation import (
    AnnotationContext,
    AnnotationReport,
    RejectionReason,
    StatementDraft,
)
from observatoire.domain.errors import AnnotationUnavailableError, MalformedAnnotationError
from observatoire.domain.models import DocumentSegmentation, RawDocument, Segment
from observatoire.services.ai_relevance import RelevanceSettings, TermRelevanceFilter
from observatoire.services.annotation_gates import AnnotationGates, GateSettings
from support import FrozenClock, InMemoryStore, candidate, document, draft, source

AI = "Nous créerons une autorité de contrôle de l'IA."
OTHER = "Nous baisserons les impôts locaux."
RELEVANCE = TermRelevanceFilter(RelevanceSettings(strong_patterns=(r"\bIA\b",)))
GATES = AnnotationGates(["regulation"], GateSettings(quote_max_words=20))


class ScriptedAnnotator:
    """Answers from a script keyed by passage text; records what it was asked."""

    def __init__(
        self, answers: dict[str, list[StatementDraft] | Exception], version: str = "v1"
    ) -> None:
        self._answers = answers
        self._version = version
        self.asked: list[tuple[str, AnnotationContext]] = []

    @property
    def version(self) -> str:
        return self._version

    def annotate(self, segment: Segment, context: AnnotationContext) -> list[StatementDraft]:
        self.asked.append((segment.text, context))
        answer = self._answers.get(segment.text, [])
        if isinstance(answer, Exception):
            raise answer
        return answer


def _segmented(store: InMemoryStore, doc: RawDocument, *texts: str) -> None:
    segments = tuple(
        Segment(document_hash=doc.content_hash, index=i, text=t, spans=((0, len(t)),))
        for i, t in enumerate(texts)
    )
    store.save(doc)
    store.replace(
        [
            DocumentSegmentation(
                document_hash=doc.content_hash,
                segmenter_version="s1",
                segments=segments,
                excluded=(),
            )
        ]
    )


def _run(
    store: InMemoryStore,
    annotator: ScriptedAnnotator,
    *,
    since: date | None = None,
    limit: int | None = None,
    rebuild: bool = False,
    covered_by: tuple[str, ...] = (),
    shown: bool | None = None,
) -> AnnotationReport:
    use_case = AnnotateDocuments(
        corpus=store,
        segments=store,
        store=store,
        annotator=annotator,
        relevance=RELEVANCE,
        reviewer=GATES,
        clock=FrozenClock(),
    )
    return use_case.run(
        [candidate().model_copy(update={"shown": shown})],
        [source()],
        since=since,
        limit=limit,
        rebuild=rebuild,
        covered_by=covered_by,
    )


def test_only_passages_that_pass_the_prefilter_reach_the_annotator() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI + " " + OTHER), AI, OTHER)
    annotator = ScriptedAnnotator({AI: [draft("une autorité de contrôle de l'IA")]})

    report = _run(store, annotator)

    assert [text for text, _ in annotator.asked] == [AI]
    assert report.not_relevant == 1
    assert report.statements == 1


def test_the_annotator_is_told_who_speaks_and_where_from_configuration() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)
    annotator = ScriptedAnnotator({})

    _run(store, annotator)

    (_, told), *_ = annotator.asked
    assert (told.speaker, told.source_label) == ("Camille Exemple", "Parti Exemple — fil RSS")
    assert told.published_on == date(2026, 9, 15)


def test_an_empty_answer_is_stored_and_never_asked_again() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)
    annotator = ScriptedAnnotator({})

    first = _run(store, annotator)
    second = _run(store, annotator)

    assert first.empty == 1
    assert second.already_annotated == 1
    assert len(annotator.asked) == 1
    (stored,) = store.annotations.values()
    assert stored.is_empty


def test_a_new_annotator_version_annotates_again() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)
    _run(store, ScriptedAnnotator({}, version="v1"))

    report = _run(store, ScriptedAnnotator({}, version="v2"))

    assert report.annotated == 1


def test_a_passage_whose_text_changed_is_annotated_again() -> None:
    store = InMemoryStore()
    doc = document(AI)
    _segmented(store, doc, AI)
    annotator = ScriptedAnnotator({})
    _run(store, annotator)
    _segmented(store, doc, AI + " Et la formation.")

    _run(store, annotator)

    assert len(annotator.asked) == 2


def test_a_limit_leaves_the_rest_pending_for_the_next_run() -> None:
    store = InMemoryStore()
    texts = [f"Mesure {n} sur l'IA." for n in range(3)]
    _segmented(store, document(" ".join(texts)), *texts)

    report = _run(store, ScriptedAnnotator({}), limit=2)

    assert (report.annotated, report.pending) == (2, 1)


def test_no_answer_now_is_a_failure_and_nothing_is_stored() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)
    annotator = ScriptedAnnotator({AI: AnnotationUnavailableError("quota")})

    report = _run(store, annotator)

    assert report.failed == 1
    assert store.annotations == {}


def test_a_malformed_answer_is_a_failure_too() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)

    report = _run(store, ScriptedAnnotator({AI: MalformedAnnotationError("bad json")}))

    assert (report.failed, report.annotated) == (1, 0)


def test_rejected_proposals_are_stored_and_counted() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)
    annotator = ScriptedAnnotator({AI: [draft("une phrase inventée")]})

    report = _run(store, annotator)

    assert report.rejected == {RejectionReason.QUOTE_NOT_IN_PASSAGE: 1}
    (stored,) = store.annotations.values()
    assert stored.annotations == ()
    assert len(stored.rejected) == 1


def test_documents_outside_the_window_or_unconfigured_are_not_read() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI, published_on=date(2026, 5, 1)), AI)
    stray = "Une autre source parle de l'IA."
    _segmented(store, document(stray, source_id="ailleurs/rss/x"), stray)

    report = _run(store, ScriptedAnnotator({}), since=date(2026, 7, 1))

    assert report.segments_read == 0


def test_the_text_of_someone_off_the_register_is_never_sent() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)
    annotator = ScriptedAnnotator({})

    report = _run(store, annotator, shown=False)

    assert annotator.asked == []
    assert report.segments_read == 0


def test_a_rebuild_annotates_again_what_was_already_annotated() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)
    annotator = ScriptedAnnotator({})
    _run(store, annotator)

    report = _run(store, annotator, rebuild=True)

    assert (report.annotated, report.already_annotated) == (1, 0)


def test_a_passage_a_verified_edition_covers_is_not_sent_again() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)
    _run(store, ScriptedAnnotator({}, version="edition"))
    daily = ScriptedAnnotator({}, version="daily")

    report = _run(store, daily, covered_by=("edition",))

    assert (report.already_annotated, daily.asked) == (1, [])


def test_a_passage_changed_since_the_verified_edition_is_annotated() -> None:
    store = InMemoryStore()
    doc = document(AI)
    _segmented(store, doc, AI)
    _run(store, ScriptedAnnotator({}, version="edition"))
    _segmented(store, doc, AI + " Et la formation.")

    report = _run(store, ScriptedAnnotator({}, version="daily"), covered_by=("edition",))

    assert report.annotated == 1


def test_replaying_a_verified_edition_with_a_rebuild_annotates_it_again() -> None:
    store = InMemoryStore()
    _segmented(store, document(AI), AI)
    edition = ScriptedAnnotator({}, version="edition")
    _run(store, edition)

    report = _run(store, edition, rebuild=True, covered_by=("edition",))

    assert report.annotated == 1
