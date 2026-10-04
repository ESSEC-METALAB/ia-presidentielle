"""SegmentDocuments, with the real segmenter and an in-memory store."""

from observatoire.application.segment_documents import SegmentDocuments
from observatoire.domain.models import ExclusionReason
from observatoire.services.candidate_matcher import AliasMatcher
from observatoire.services.segmentation import ParagraphSegmenter, SegmentationSettings
from support import InMemoryStore, candidate, document, source

SETTINGS = SegmentationSettings(
    min_chars=20,
    max_chars=400,
    repeated_line_max_chars=120,
    repeated_in_document_min=3,
    repeated_in_document_min_words=2,
    repeated_in_source_min_documents=3,
)
FEED = source()
MATCHER = AliasMatcher([candidate(), candidate("dominique-temoin", "Dominique Témoin")])


def _use_case(store: InMemoryStore, settings: SegmentationSettings = SETTINGS) -> SegmentDocuments:
    return SegmentDocuments(store, store, ParagraphSegmenter(settings), MATCHER)


def test_segments_record_which_candidates_they_name() -> None:
    store = InMemoryStore([document("Dominique Témoin répond à Camille Exemple sur le numérique.")])

    _use_case(store).run([FEED])

    (segmentation,) = store.segmentations.values()
    names = {m.candidate_id for m in segmentation.segments[0].mentions}
    assert names == {"camille-exemple", "dominique-temoin"}


def test_a_source_already_segmented_by_this_version_is_left_alone() -> None:
    store = InMemoryStore([document("Un texte fictif assez long pour former un segment.")])
    _use_case(store).run([FEED])

    report = _use_case(store).run([FEED])

    assert report.outcomes[0].resegmented is False
    assert store.replace_calls == 1


def test_a_new_document_resegments_its_whole_source() -> None:
    store = InMemoryStore([document("Un texte fictif assez long pour former un segment.")])
    _use_case(store).run([FEED])
    store.save(document("Un second texte fictif, lui aussi assez long."))

    report = _use_case(store).run([FEED])

    assert (report.outcomes[0].resegmented, report.outcomes[0].documents) == (True, 2)


def test_changed_settings_resegment_everything() -> None:
    store = InMemoryStore([document("Un texte fictif assez long pour former un segment.")])
    _use_case(store).run([FEED])

    report = _use_case(store, SETTINGS.model_copy(update={"min_chars": 30})).run([FEED])

    assert report.outcomes[0].resegmented is True


def test_the_report_counts_empty_documents_and_exclusions_by_reason() -> None:
    store = InMemoryStore(
        [document("Bravo !"), document("Un texte fictif assez long pour un segment.")]
    )

    report = _use_case(store).run([FEED])

    outcome = report.outcomes[0]
    assert (outcome.documents, outcome.empty_documents, outcome.segments) == (2, 1, 1)
    assert outcome.excluded == {ExclusionReason.TOO_SHORT: 1}


def test_documents_of_unconfigured_sources_are_counted_not_segmented() -> None:
    store = InMemoryStore([document("Orphelin fictif mais assez long.", source_id="retired")])

    report = _use_case(store).run([FEED])

    assert (report.outcomes, report.unconfigured_documents) == ((), 1)
