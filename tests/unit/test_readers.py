"""Source readers, on frozen fixtures served by a mock transport. No network."""

import io
import json
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest

from observatoire.adapters.extraction.trafilatura_extractor import TrafilaturaExtractor
from observatoire.adapters.sources.assemblee_nationale_reader import AssembleeNationaleReader
from observatoire.adapters.sources.html_page_reader import HtmlPageReader
from observatoire.adapters.sources.http_client import PoliteHttpClient, robots_fetcher
from observatoire.adapters.sources.legacy_pipeline_reader import LegacyPipelineReader
from observatoire.adapters.sources.pdf_reader import PdfReader
from observatoire.adapters.sources.rss_reader import RssReader
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import Source, TrustLevel
from observatoire.services.robots_policy import RobotsPolicy
from support import FIXTURES, T0, FrozenClock, minimal_pdf, source

SITE = "https://parti-exemple.test"
ARCHIVE = "https://open-data.test/syseron.xml.zip"


def _fixture(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


def _http(routes: dict[str, bytes | str], requests: list[str] | None = None) -> PoliteHttpClient:
    def handle(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(str(request.url))
        body = routes.get(str(request.url))
        return httpx.Response(404) if body is None else httpx.Response(200, content=body)

    raw = httpx.Client(transport=httpx.MockTransport(handle))
    return PoliteHttpClient(
        raw, RobotsPolicy("Test/1.0", 0.0, robots_fetcher(raw)), max_redirects=3
    )


EXTRACTOR = TrafilaturaExtractor(min_chars=400)


# --- extraction ---------------------------------------------------------------------------


def test_extraction_keeps_the_article_and_the_date_the_page_states() -> None:
    extracted = EXTRACTOR.extract(_fixture("html/article_dated.html"), f"{SITE}/a")

    assert extracted is not None
    assert extracted.published_on == date(2026, 9, 15)
    assert "calendrier en trois étapes" in extracted.text
    assert "mentions légales" not in extracted.text


def test_extraction_never_invents_a_date_for_an_undated_page() -> None:
    extracted = EXTRACTOR.extract(_fixture("html/article_undated.html"), f"{SITE}/b")

    assert extracted is not None
    assert extracted.published_on is None


def test_a_teaser_shorter_than_the_threshold_is_not_a_text() -> None:
    assert EXTRACTOR.extract(_fixture("html/teaser.html"), f"{SITE}/c") is None


# --- RSS ----------------------------------------------------------------------------------


def _rss_reader() -> RssReader:
    routes: dict[str, bytes | str] = {
        f"{SITE}/feed/": _fixture("rss/feed.xml"),
        f"{SITE}/discours-numerique": _fixture("html/article_dated.html"),
        f"{SITE}/breve": _fixture("html/teaser.html"),
        f"{SITE}/ancien": _fixture("html/article_undated.html"),
    }
    return RssReader(_http(routes), EXTRACTOR, FrozenClock())


def test_rss_reads_each_item_page_with_its_provenance() -> None:
    documents = list(_rss_reader().fetch(source(), since=None))

    first = documents[0]
    assert first.url == f"{SITE}/discours-numerique"
    assert first.published_on == date(2026, 9, 15)
    assert first.fetched_at == T0
    assert first.trust_level == TrustLevel.PARTY
    assert first.candidate_id == "camille-exemple"


def test_rss_skips_teasers_and_unreachable_items_without_failing_the_feed() -> None:
    documents = list(_rss_reader().fetch(source(), since=None))

    assert [d.url for d in documents] == [f"{SITE}/discours-numerique", f"{SITE}/ancien"]


def test_rss_skips_items_published_before_since() -> None:
    documents = list(_rss_reader().fetch(source(), since=date(2026, 9, 1)))

    assert [d.url for d in documents] == [f"{SITE}/discours-numerique"]


def test_rss_falls_back_to_the_feed_date_when_the_page_has_none() -> None:
    documents = list(_rss_reader().fetch(source(), since=None))

    assert documents[1].published_on == date(2025, 1, 1)


def test_an_unparseable_feed_fails_the_source() -> None:
    reader = RssReader(_http({f"{SITE}/feed/": "pas un flux"}), EXTRACTOR, FrozenClock())

    with pytest.raises(SourceUnavailableError, match="unparseable"):
        list(reader.fetch(source(), since=None))


# --- standing page and PDF ----------------------------------------------------------------


def test_a_standing_page_becomes_one_document_titled_by_its_label() -> None:
    page = source(kind="page", trust_level=TrustLevel.OWN_WORDS)
    reader = HtmlPageReader(
        _http({page.url: _fixture("html/article_undated.html")}), EXTRACTOR, FrozenClock()
    )

    (document,) = reader.fetch(page, since=None)

    assert document.title == page.label
    assert document.published_on is None


def test_a_page_without_text_fails_the_source() -> None:
    page = source(kind="page")
    reader = HtmlPageReader(
        _http({page.url: _fixture("html/teaser.html")}), EXTRACTOR, FrozenClock()
    )

    with pytest.raises(SourceUnavailableError, match="no extractable text"):
        reader.fetch(page, since=None)


def test_a_pdf_yields_its_text_layer_and_the_configured_date() -> None:
    pdf = source(kind="pdf", options={"published_on": "2026-07-07"})
    reader = PdfReader(
        _http({pdf.url: minimal_pdf("Programme fictif pour le numerique")}), FrozenClock()
    )

    (document,) = reader.fetch(pdf, since=None)

    assert "Programme fictif pour le numerique" in document.text
    assert document.published_on == date(2026, 7, 7)


def test_a_file_that_is_not_a_pdf_fails_the_source() -> None:
    pdf = source(kind="pdf")
    reader = PdfReader(_http({pdf.url: b"<html>not a pdf</html>"}), FrozenClock())

    with pytest.raises(SourceUnavailableError, match="PDF"):
        reader.fetch(pdf, since=None)


# --- Assemblée nationale -----------------------------------------------------------------

_NS = "http://schemas.assemblee-nationale.fr/referentiel"


def _seance(uid: str, day: str, paragraphs: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f'<paragraphe id_acteur="{actor}" roledebat="{role}"><texte>{text}</texte></paragraphe>'
        for actor, role, text in paragraphs
    )
    return (
        f'<compteRendu xmlns="{_NS}"><uid>{uid}</uid><metadonnees>'
        f"<dateSeance>{day}150000000</dateSeance><dateSeanceJour>jour fictif</dateSeanceJour>"
        f"</metadonnees><contenu>{body}</contenu></compteRendu>"
    )


def _archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


ARCHIVE_BYTES = _archive(
    {
        "s1.xml": _seance("CRS1", "20260915", [
            ("PA1", "orateur", "Premier propos fictif."),
            ("PA2", "president", "La parole est à Camille Exemple."),
        ]),
        "s2.xml": _seance("CRS2", "20250110", [
            ("PA1", "orateur", "Second propos fictif."),
            ("PA1", "orateur", "Suite du second propos."),
        ]),
        "s3.xml": "<compteRendu><non-ferme>",
    }
)  # fmt: skip


def _an_source(actor: str) -> Source:
    return source(
        f"x/an/{actor}",
        kind="assemblee_nationale",
        trust_level=TrustLevel.OWN_WORDS,
        options={"acteur": actor, "legislature": "17"},
    ).model_copy(update={"url": ARCHIVE})


def _an_reader(requests: list[str] | None = None) -> AssembleeNationaleReader:
    return AssembleeNationaleReader(_http({ARCHIVE: ARCHIVE_BYTES}, requests), FrozenClock())


def test_one_document_per_seance_where_the_actor_spoke() -> None:
    documents = list(_an_reader().fetch(_an_source("PA1"), since=None))

    assert [d.published_on for d in documents] == [date(2026, 9, 15), date(2025, 1, 10)]
    assert (
        documents[0].url == "https://www.assemblee-nationale.fr/dyn/17/comptes-rendus/seance/CRS1"
    )
    assert documents[1].text == "Second propos fictif.\n\nSuite du second propos."


def test_chairing_the_sitting_is_not_speaking() -> None:
    documents = list(_an_reader().fetch(_an_source("PA2"), since=None))

    assert documents == []


def test_the_archive_is_downloaded_once_for_every_configured_person() -> None:
    requests: list[str] = []
    reader = _an_reader(requests)

    list(reader.fetch(_an_source("PA1"), since=None))
    list(reader.fetch(_an_source("PA2"), since=None))

    assert requests.count(ARCHIVE) == 1


def test_seances_before_since_are_skipped() -> None:
    documents = list(_an_reader().fetch(_an_source("PA1"), since=date(2026, 1, 1)))

    assert len(documents) == 1


# --- previous version's database ---------------------------------------------------------


def _legacy_db(path: Path, rows: list[tuple[str, dict[str, object]]]) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE documents (url_hash TEXT PRIMARY KEY, person TEXT NOT NULL, "
            "source_id TEXT NOT NULL, fetched_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        for index, (person, payload) in enumerate(rows):
            connection.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?)",
                (str(index), person, "legacy", "2026-09-18T12:59:24+00:00", json.dumps(payload)),
            )
    return path


def test_legacy_documents_keep_their_url_date_and_original_fetch_time(tmp_path: Path) -> None:
    database = _legacy_db(tmp_path / "legacy.db", [
        ("camille-exemple", {
            "kind": "rss", "url": f"{SITE}/a", "title": "A", "text": "Texte A",
            "date": "2026-09-01",
        }),
        ("camille-exemple", {"kind": "an", "url": f"{SITE}/b", "text": "Texte B"}),
        ("dominique-temoin", {"kind": "rss", "url": f"{SITE}/c", "text": "Texte C"}),
    ])  # fmt: skip

    (document,) = LegacyPipelineReader(database).fetch(source(), since=None)

    assert (document.url, document.title, document.published_on) == (
        f"{SITE}/a",
        "A",
        date(2026, 9, 1),
    )
    assert document.fetched_at.isoformat() == "2026-09-18T12:59:24+00:00"


def test_a_missing_legacy_database_fails_the_source(tmp_path: Path) -> None:
    reader = LegacyPipelineReader(tmp_path / "absent.db")

    with pytest.raises(SourceUnavailableError, match="not found"):
        reader.fetch(source(), since=None)


def test_a_kind_the_previous_version_never_had_yields_nothing(tmp_path: Path) -> None:
    reader = LegacyPipelineReader(_legacy_db(tmp_path / "legacy.db", []))

    assert reader.fetch(source(kind="youtube"), since=None) == []
