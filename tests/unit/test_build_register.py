"""BuildRegister: provenance from stored documents; which annotation each passage shows."""

from datetime import UTC, date, datetime

import pytest

from observatoire.application.build_register import BuildRegister
from observatoire.domain.annotation import Dimension, DimensionAnnotation, SegmentAnnotation
from observatoire.domain.models import (
    Candidacy,
    CandidacyStatus,
    Candidate,
    DocumentSegmentation,
    RawDocument,
    Segment,
    Source,
    TrustLevel,
)
from observatoire.domain.register import Register
from observatoire.services.ai_relevance import RelevanceSettings, TermRelevanceFilter
from observatoire.services.dedup import content_hash
from support import FrozenClock, InMemoryStore, candidate, document, source

DIMENSIONS = (
    Dimension(
        id="regulation",
        label_fr="Régulation",
        label_en="Regulation",
        definition_fr="Règles.",
        definition_en="Rules.",
    ),
)
TEXT = "Nous créerons une autorité de contrôle de l'IA."
FEED = source()
RELEVANCE = TermRelevanceFilter(RelevanceSettings(strong_patterns=(r"\bIA\b",)))


def _withdrawn() -> Candidate:
    return Candidate(
        id="dominique-temoin",
        name="Dominique Témoin",
        party="Parti Témoin",
        candidacy=Candidacy(
            status=CandidacyStatus.WITHDRAWN,
            checked_on=date(2026, 10, 14),
            sources=("https://example.test/retrait",),
        ),
    )


def _annotated(
    store: InMemoryStore,
    doc: RawDocument,
    *,
    version: str = "v1",
    at: datetime = datetime(2026, 11, 1, tzinfo=UTC),
    hashed: str | None = None,
    statements: int = 1,
) -> SegmentAnnotation:
    passage = Segment(document_hash=doc.content_hash, index=0, text=TEXT, spans=((0, len(TEXT)),))
    store.save(doc)
    store.replace(
        [
            DocumentSegmentation(
                document_hash=doc.content_hash,
                segmenter_version="s1",
                segments=(passage,),
                excluded=(),
            )
        ]
    )
    statement = DimensionAnnotation(
        segment_id=passage.id,
        index=0,
        dimension="regulation",
        quote="une autorité de contrôle",
        quote_span=(14, 38),
        summary_fr="Propose une autorité.",
        summary_en="Proposes an authority.",
        context_fr="Texte fictif.",
        context_en="Fictional text.",
        gloss_en="an oversight authority",
    )
    annotation = SegmentAnnotation(
        segment_id=passage.id,
        segment_hash=hashed or content_hash(TEXT),
        annotator_version=version,
        annotated_at=at,
        annotations=(statement,) * statements,
    )
    store.save_annotation(annotation)
    return annotation


def _build(
    store: InMemoryStore,
    people: list[Candidate],
    sources: list[Source],
    verified: tuple[str, ...] = (),
) -> Register:
    use_case = BuildRegister(
        corpus=store, segments=store, annotations=store, relevance=RELEVANCE, clock=FrozenClock()
    )
    return use_case.build(people, sources, DIMENSIONS, since=date(2026, 7, 1), verified=verified)


def test_a_statement_carries_the_stored_documents_provenance() -> None:
    store = InMemoryStore()
    doc = document(TEXT)
    _annotated(store, doc)

    register = _build(store, [candidate()], [FEED])

    (entry,) = register.entries
    assert entry.document.url == doc.url
    assert entry.source.id == FEED.id
    assert register.annotators == ("v1",)
    assert entry.annotator_version == "v1"
    assert not entry.verified


def test_withdrawn_people_are_listed_apart_and_never_shown() -> None:
    store = InMemoryStore()
    _annotated(store, document(TEXT, source_id="x/rss/y", candidate_id="dominique-temoin"))
    theirs = source("x/rss/y", candidate_id="dominique-temoin")

    register = _build(store, [candidate(), _withdrawn()], [FEED, theirs])

    assert [c.candidate.id for c in register.candidates] == ["camille-exemple"]
    assert [c.id for c in register.withdrawn] == ["dominique-temoin"]
    assert register.entries == ()


def test_a_person_without_an_enabled_source_is_not_monitored() -> None:
    register = _build(InMemoryStore(), [candidate(), candidate("x-y", "X Y")], [FEED])

    monitored = {c.candidate.id: c.monitored for c in register.candidates}
    assert monitored == {"camille-exemple": True, "x-y": False}


def test_press_never_becomes_a_statement() -> None:
    store = InMemoryStore()
    _annotated(store, document(TEXT, trust_level=TrustLevel.PRESS))
    press = source(trust_level=TrustLevel.PRESS)

    register = _build(store, [candidate()], [press])

    assert register.entries == ()


def test_an_annotation_of_an_older_passage_text_is_not_shown() -> None:
    store = InMemoryStore()
    _annotated(store, document(TEXT), hashed=content_hash("Un ancien découpage."))

    register = _build(store, [candidate()], [FEED])

    assert register.entries == ()


def test_on_equal_coverage_the_more_recent_automatic_annotator_is_shown() -> None:
    store = InMemoryStore()
    doc = document(TEXT)
    _annotated(store, doc, version="old", at=datetime(2026, 10, 1, tzinfo=UTC))
    _annotated(store, doc, version="new", at=datetime(2026, 11, 2, tzinfo=UTC))

    register = _build(store, [candidate()], [FEED])

    assert register.annotators == ("new",)
    assert len(register.entries) == 1


def test_nothing_annotated_yet_is_an_empty_register_not_an_error() -> None:
    register = _build(InMemoryStore(), [candidate()], [FEED])

    assert register.annotators == ()
    assert register.pending == {}


@pytest.mark.parametrize("archived_first", [True, False])
def test_a_rewritten_page_does_not_count_an_unchanged_sentence_twice(archived_first: bool) -> None:
    store = InMemoryStore()
    page = "https://parti-exemple.test/page"
    capture = f"https://web.archive.org/web/20260918144520/{page}"
    plain = document("Version 1. " + TEXT).model_copy(update={"url": page})
    archived = document("Version 2. " + TEXT).model_copy(
        update={"url": page, "archive_url": capture}
    )
    for doc in (archived, plain) if archived_first else (plain, archived):
        _annotated(store, doc)

    register = _build(store, [candidate()], [FEED])

    (entry,) = register.entries
    assert entry.document.archive_url == capture


def test_a_newer_annotator_that_has_not_caught_up_does_not_replace_the_register() -> None:
    store = InMemoryStore()
    first, second = document("Premier. " + TEXT), document("Second. " + TEXT)
    _annotated(store, first, version="complete", at=datetime(2026, 10, 1, tzinfo=UTC))
    _annotated(store, second, version="complete", at=datetime(2026, 10, 1, tzinfo=UTC))
    _annotated(store, first, version="partial", at=datetime(2026, 11, 2, tzinfo=UTC))

    register = _build(store, [candidate()], [FEED])

    assert register.annotators == ("complete",)


def test_rows_of_passages_that_no_longer_exist_do_not_count_as_coverage() -> None:
    store = InMemoryStore()
    for gone in ("aaaa-000", "aaaa-001", "aaaa-002"):  # an older segmentation's passages
        store.save_annotation(
            SegmentAnnotation(
                segment_id=gone,
                segment_hash=content_hash(gone),
                annotator_version="old",
                annotated_at=datetime(2026, 12, 1, tzinfo=UTC),
                annotations=(),
            )
        )
    _annotated(store, document(TEXT), version="new", at=datetime(2026, 10, 1, tzinfo=UTC))

    register = _build(store, [candidate()], [FEED])

    assert register.annotators == ("new",)
    assert len(register.entries) == 1


def test_a_verified_edition_outranks_a_newer_automatic_run_on_the_same_passage() -> None:
    store = InMemoryStore()
    doc = document(TEXT)
    _annotated(store, doc, version="edition", at=datetime(2026, 11, 3, tzinfo=UTC))
    _annotated(store, doc, version="daily", at=datetime(2026, 11, 4, tzinfo=UTC), statements=0)

    register = _build(store, [candidate()], [FEED], verified=("edition",))

    (entry,) = register.entries
    assert (entry.annotator_version, entry.verified) == ("edition", True)
    assert register.annotators == ("edition",)


def test_the_automatic_annotator_fills_what_the_verified_edition_does_not_cover() -> None:
    store = InMemoryStore()
    old, new = document("Ancien. " + TEXT), document("Nouveau. " + TEXT)
    _annotated(store, old, version="edition")
    _annotated(store, new, version="daily")

    register = _build(store, [candidate()], [FEED], verified=("edition",))

    assert sorted((e.annotator_version, e.verified) for e in register.entries) == [
        ("daily", False),
        ("edition", True),
    ]
    assert register.annotators == ("edition", "daily")


def test_an_ai_passage_nobody_annotated_is_pending_for_its_candidate() -> None:
    store = InMemoryStore()
    doc = document(TEXT)
    _annotated(store, doc)
    fresh = document("Une autre mesure sur l'IA, collectée ce matin.")
    store.save(fresh)
    store.replace(
        [
            DocumentSegmentation(
                document_hash=fresh.content_hash,
                segmenter_version="s1",
                segments=(
                    Segment(
                        document_hash=fresh.content_hash,
                        index=0,
                        text=fresh.text,
                        spans=((0, len(fresh.text)),),
                    ),
                    Segment(
                        document_hash=fresh.content_hash,
                        index=1,
                        text="Rien sur le sujet.",
                        spans=((0, 5),),
                    ),
                ),
                excluded=(),
            )
        ]
    )

    register = _build(store, [candidate()], [FEED])

    assert register.pending == {"camille-exemple": 1}


def test_texts_read_are_counted_per_source_statements_or_not() -> None:
    store = InMemoryStore()
    _annotated(store, document(TEXT))
    store.save(document("Un autre texte, sans rien sur le sujet."))
    store.save(document("Hors fenêtre.", published_on=date(2026, 6, 1)))

    register = _build(store, [candidate()], [FEED])

    assert register.documents == {FEED.id: 2}


def test_texts_of_a_withdrawn_person_or_the_press_are_not_counted() -> None:
    store = InMemoryStore()
    store.save(document("Presse.", source_id="press", trust_level=TrustLevel.PRESS))
    store.save(document("Retrait.", source_id="x/rss/y", candidate_id="dominique-temoin"))
    sources = [
        source("press", trust_level=TrustLevel.PRESS),
        source("x/rss/y", candidate_id="dominique-temoin"),
    ]

    register = _build(store, [candidate(), _withdrawn()], sources)

    assert register.documents == {}
