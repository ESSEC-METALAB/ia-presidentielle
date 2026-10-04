"""CollectDaily, with fake readers and an in-memory store."""

from collections.abc import Iterable
from datetime import date, timedelta

from observatoire.application.collect_daily import CollectDaily
from observatoire.domain.errors import SourceUnavailableError
from observatoire.domain.models import CollectionReport, RawDocument, Source
from observatoire.domain.ports import SourceReader
from support import FrozenClock, InMemoryStore, document, source


class FakeReader:
    def __init__(self, documents: Iterable[RawDocument]) -> None:
        self._documents = list(documents)

    def fetch(self, source: Source, since: date | None) -> list[RawDocument]:
        return self._documents


class FailingReader:
    def fetch(self, source: Source, since: date | None) -> list[RawDocument]:
        raise SourceUnavailableError(source.url, "HTTP 503")


def _collect(
    readers: dict[str, SourceReader], store: InMemoryStore, *sources: Source
) -> CollectionReport:
    use_case = CollectDaily(readers, store, store, FrozenClock(step=timedelta(milliseconds=250)))
    return use_case.run(list(sources), run_id="run-1")


def test_new_documents_are_stored_and_known_ones_counted_as_duplicates() -> None:
    known = document("Déjà vu.")
    store = InMemoryStore([known])
    reader = FakeReader([known, document("Nouveau.")])

    report = _collect({"rss": reader}, store, source())

    (outcome,) = report.outcomes
    assert (outcome.status, outcome.fetched, outcome.new, outcome.duplicates) == ("ok", 2, 1, 1)
    assert len(store.documents) == 2


def test_a_failing_source_is_recorded_and_the_run_carries_on() -> None:
    store = InMemoryStore()
    readers: dict[str, SourceReader] = {
        "rss": FailingReader(),
        "page": FakeReader([document("Texte.")]),
    }

    report = _collect(readers, store, source("a"), source("b", kind="page"))

    assert [o.status for o in report.outcomes] == ["failed", "ok"]
    assert "HTTP 503" in (report.outcomes[0].error or "")
    assert len(store.documents) == 1


def test_a_kind_without_reader_is_a_failure_not_a_crash() -> None:
    report = _collect({}, InMemoryStore(), source(kind="youtube"))

    assert report.outcomes[0].error == "no reader registered for kind 'youtube'"


def test_every_source_outcome_is_logged_with_its_duration() -> None:
    store = InMemoryStore()

    _collect({"rss": FakeReader([])}, store, source("a"), source("b"))

    assert [(o.source_id, o.duration_ms) for o in store.outcomes] == [("a", 250), ("b", 250)]
