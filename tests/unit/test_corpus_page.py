"""The raw-corpus page: view model and rendered HTML."""

from datetime import date

from observatoire.adapters.reporting.corpus_html_renderer import CorpusHtmlRenderer
from observatoire.adapters.reporting.corpus_page import build_chart, format_count, safe_href
from observatoire.application.inspect_corpus import InspectCorpus
from observatoire.application.segment_documents import SegmentDocuments
from observatoire.domain.models import CorpusOverview, RawDocument, TrustLevel
from observatoire.services.candidate_matcher import AliasMatcher
from observatoire.services.segmentation import ParagraphSegmenter, SegmentationSettings
from support import T0, FrozenClock, InMemoryStore, candidate, document, source

CAMILLE = candidate()
DOMINIQUE = candidate("dominique-temoin", "Dominique Témoin")


def _overview(*documents_: RawDocument) -> CorpusOverview:
    store = InMemoryStore(documents_)
    use_case = InspectCorpus(store, store, AliasMatcher([CAMILLE, DOMINIQUE]), FrozenClock())
    return use_case.build([CAMILLE, DOMINIQUE], [source()])


def test_collected_text_is_escaped_never_executed() -> None:
    html = CorpusHtmlRenderer().render(_overview(document("<script>alert('x')</script> fin.")))

    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html


def test_an_undated_document_says_so() -> None:
    html = CorpusHtmlRenderer().render(_overview(document("Sans date.", published_on=None)))

    assert "date non précisée" in html


def test_a_person_without_sources_is_shown_as_not_monitored() -> None:
    html = CorpusHtmlRenderer().render(_overview())

    assert "Non suivi" in html
    assert "Dominique Témoin" in html


def test_a_fragment_has_no_document_wrapper_and_a_page_has_one() -> None:
    overview = _overview()

    assert "<html" not in CorpusHtmlRenderer(standalone=False).render(overview)
    assert CorpusHtmlRenderer().render(overview).lstrip().startswith("<!doctype html>")


def test_only_web_links_reach_an_href() -> None:
    assert safe_href("https://example.test/a") == "https://example.test/a"
    assert safe_href("javascript:alert(1)") is None


def test_counts_use_french_digit_grouping() -> None:
    assert format_count(710513) == "710\u202f513"


def test_the_chart_scale_is_shared_and_out_of_window_documents_are_reported() -> None:
    overview = _overview(
        document("Septembre 1.", published_on=date(2026, 9, 1)),
        document("Septembre 2.", published_on=date(2026, 9, 2), trust_level=TrustLevel.OWN_WORDS),
        document("Trop ancien.", published_on=date(2020, 1, 1)),
        document("Sans date.", published_on=None),
    )

    chart = build_chart(overview, months=12)

    assert (chart.y_max, chart.before_window, chart.undated) == (2, 1, 1)
    assert chart.last_month == "oct. 2026"
    assert overview.generated_at == T0


def _segmented_overview(*documents_: RawDocument) -> CorpusOverview:
    store = InMemoryStore(documents_)
    settings = SegmentationSettings(
        min_chars=40,
        max_chars=400,
        repeated_line_max_chars=120,
        repeated_in_document_min=3,
        repeated_in_document_min_words=2,
        repeated_in_source_min_documents=3,
    )
    matcher = AliasMatcher([CAMILLE, DOMINIQUE])
    SegmentDocuments(store, store, ParagraphSegmenter(settings), matcher).run([source()])
    use_case = InspectCorpus(store, store, matcher, FrozenClock(), segments=store)
    return use_case.build([CAMILLE, DOMINIQUE], [source()])


def test_each_document_shows_its_segments_and_what_was_set_aside() -> None:
    text = "Camille Exemple répond à Dominique Témoin sur le plan numérique.\nBravo !"

    html = CorpusHtmlRenderer().render(_segmented_overview(document(text)))

    assert "1 segment<" in html
    assert "cite aussi Dominique Témoin" in html
    assert "Passage trop court pour porter une position" in html


def test_a_document_with_nothing_usable_says_so() -> None:
    html = CorpusHtmlRenderer().render(_segmented_overview(document("Merci !")))

    assert "aucun passage exploitable" in html
    assert 'data-segmentation="empty"' in html


def test_an_unsegmented_corpus_tells_how_to_segment_it() -> None:
    html = CorpusHtmlRenderer().render(_overview(document("Pas encore découpé.")))

    assert "observatoire segment" in html
    assert 'data-segmentation="pending"' in html
