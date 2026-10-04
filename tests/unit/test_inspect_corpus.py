"""InspectCorpus, with an in-memory store."""

from datetime import date, timedelta
from typing import Literal

from observatoire.application.inspect_corpus import InspectCorpus
from observatoire.domain.models import SourceOutcome
from observatoire.services.candidate_matcher import AliasMatcher
from support import T0, FrozenClock, InMemoryStore, candidate, document, source

CAMILLE = candidate()
DOMINIQUE = candidate("dominique-temoin", "Dominique Témoin")
FEED = source()


def _inspect(store: InMemoryStore) -> InspectCorpus:
    return InspectCorpus(store, store, AliasMatcher([CAMILLE, DOMINIQUE]), FrozenClock())


def test_every_configured_person_gets_a_row_even_without_sources() -> None:
    overview = _inspect(InMemoryStore()).build([CAMILLE, DOMINIQUE], [FEED])

    assert [(c.candidate.id, c.monitored) for c in overview.candidates] == [
        ("camille-exemple", True),
        ("dominique-temoin", False),
    ]


def test_documents_are_newest_first_with_undated_ones_last() -> None:
    store = InMemoryStore([
        document("Ancien.", published_on=date(2025, 1, 1)),
        document("Sans date.", published_on=None),
        document("Récent.", published_on=date(2026, 9, 1)),
    ])  # fmt: skip

    overview = _inspect(store).build([CAMILLE], [FEED])

    texts = [v.document.text for v in overview.candidates[0].sources[0].documents]
    assert texts == ["Récent.", "Ancien.", "Sans date."]


def test_mentions_count_only_the_documents_own_candidate() -> None:
    store = InMemoryStore([document("Camille Exemple et Dominique Témoin. Camille Exemple.")])

    overview = _inspect(store).build([CAMILLE], [FEED])

    assert overview.candidates[0].sources[0].documents[0].mentions_of_candidate == 2


def test_documents_of_a_source_no_longer_configured_are_counted_not_dropped() -> None:
    store = InMemoryStore([document("Orphelin.", source_id="retired/source")])

    overview = _inspect(store).build([CAMILLE], [FEED])

    assert overview.unconfigured_documents == 1


def _outcome(hours: int, status: Literal["ok", "failed"]) -> SourceOutcome:
    return SourceOutcome(
        run_id=f"run-{hours}",
        source_id=FEED.id,
        started_at=T0 + timedelta(hours=hours),
        duration_ms=0,
        status=status,
        fetched=0,
        new=0,
        duplicates=0,
    )


def test_the_latest_run_of_each_source_is_attached() -> None:
    store = InMemoryStore()
    store.record(_outcome(0, "failed"))
    store.record(_outcome(24, "ok"))

    overview = _inspect(store).build([CAMILLE], [FEED])

    outcome = overview.candidates[0].sources[0].last_outcome
    assert outcome is not None
    assert outcome.run_id == "run-24"
