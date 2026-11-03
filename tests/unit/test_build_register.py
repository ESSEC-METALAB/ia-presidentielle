"""BuildRegister: provenance joined from stored documents, withdrawn people and press left out."""

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
        annotations=(statement,),
    )
    store.save_annotation(annotation)
    return annotation


def _build(store: InMemoryStore, people: list[Candidate], sources: list[Source]) -> Register:
    use_case = BuildRegister(corpus=store, segments=store, annotations=store, clock=FrozenClock())
    return use_case.build(people, sources, DIMENSIONS, since=date(2026, 7, 1))


def test_a_statement_carries_the_stored_documents_provenance() -> None:
    store = InMemoryStore()
    doc = document(TEXT)
    _annotated(store, doc)

    register = _build(store, [candidate()], [FEED])

    (entry,) = register.entries
    assert entry.document.url == doc.url
    assert entry.source.id == FEED.id
    assert register.annotator_version == "v1"


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


def test_the_most_recent_annotator_is_the_one_shown() -> None:
    store = InMemoryStore()
    doc = document(TEXT)
    _annotated(store, doc, version="old", at=datetime(2026, 10, 1, tzinfo=UTC))
    _annotated(store, doc, version="new", at=datetime(2026, 11, 2, tzinfo=UTC))

    register = _build(store, [candidate()], [FEED])

    assert register.annotator_version == "new"
    assert len(register.entries) == 1


def test_nothing_annotated_yet_is_an_empty_register_not_an_error() -> None:
    register = _build(InMemoryStore(), [candidate()], [FEED])

    assert register.annotator_version is None


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
