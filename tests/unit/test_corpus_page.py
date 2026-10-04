"""The raw-corpus page: view model and rendered HTML."""

from datetime import date

from observatoire.adapters.reporting.corpus_html_renderer import CorpusHtmlRenderer
from observatoire.adapters.reporting.corpus_page import build_chart, format_count, safe_href
from observatoire.application.inspect_corpus import InspectCorpus
from observatoire.domain.models import CorpusOverview, RawDocument, TrustLevel
from observatoire.services.candidate_matcher import AliasMatcher
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
