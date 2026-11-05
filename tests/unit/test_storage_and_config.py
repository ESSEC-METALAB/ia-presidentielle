"""SQLite storage and config loading."""

import shutil
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from observatoire.adapters.storage.sqlite_repository import SqliteRepository
from observatoire.cli import _live_readers, effective_since
from observatoire.config.registry import CrawlerSettings, load_registry
from observatoire.domain.annotation import SegmentAnnotation, UsageRecord
from observatoire.domain.errors import ConfigurationError
from observatoire.domain.models import (
    Candidacy,
    CandidacyStatus,
    CandidateMention,
    DocumentSegmentation,
    ExcludedPassage,
    ExclusionReason,
    Segment,
    SourceOutcome,
)
from observatoire.services.ai_relevance import TermRelevanceFilter
from support import T0, FrozenClock, document

CONFIG = Path(__file__).resolve().parents[2] / "config"


def test_a_document_round_trips_through_sqlite_unchanged(tmp_path: Path) -> None:
    original = document("Texte fictif avec accents : éàç.", published_on=None)
    repository = SqliteRepository(tmp_path / "corpus.db")

    repository.save(original)
    repository.save(original)

    assert repository.exists(original.content_hash)
    assert repository.list_documents() == [original]


def test_the_latest_outcome_per_source_wins(tmp_path: Path) -> None:
    repository = SqliteRepository(tmp_path / "corpus.db")
    for hours in (0, 24):
        repository.record(SourceOutcome(
            run_id=f"run-{hours}", source_id="s", started_at=T0 + timedelta(hours=hours),
            duration_ms=5, status="ok", fetched=1, new=1, duplicates=0,
        ))  # fmt: skip

    assert repository.latest_by_source()["s"].run_id == "run-24"


def _segmentation(text: str, version: str) -> DocumentSegmentation:
    owner = document(text)
    return DocumentSegmentation(
        document_hash=owner.content_hash,
        segmenter_version=version,
        segments=(
            Segment(
                document_hash=owner.content_hash,
                index=0,
                text=text[:20],
                spans=((0, 20),),
                mentions=(CandidateMention(candidate_id="camille-exemple", count=1),),
            ),
        ),
        excluded=(ExcludedPassage(span=(21, 30), reason=ExclusionReason.TOO_SHORT),),
    )


def test_a_segmentation_round_trips_and_replacing_it_leaves_no_stale_rows(tmp_path: Path) -> None:
    repository = SqliteRepository(tmp_path / "corpus.db")
    text = "Camille Exemple parle. Un ajout fictif."

    repository.replace([_segmentation(text, "v1")])
    newer = _segmentation(text, "v2")
    repository.replace([newer])

    assert repository.list_segmentations() == [newer]
    assert repository.segmented_versions() == {newer.document_hash: "v2"}


def test_an_older_database_gains_the_out_of_window_column(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE source_runs (run_id TEXT NOT NULL, source_id TEXT NOT NULL,"
            " started_at TEXT NOT NULL, duration_ms INTEGER NOT NULL, status TEXT NOT NULL,"
            " fetched INTEGER NOT NULL, new INTEGER NOT NULL, duplicates INTEGER NOT NULL,"
            " error TEXT, PRIMARY KEY (run_id, source_id))"
        )
        connection.execute(
            "INSERT INTO source_runs VALUES ('old', 's', '2026-10-04T06:00:00+00:00', 1, 'ok',"
            " 3, 3, 0, NULL)"
        )

    repository = SqliteRepository(path)

    assert repository.latest_by_source()["s"].out_of_window == 0


def test_the_shipped_configuration_is_valid() -> None:
    registry = load_registry(CONFIG)

    assert {s.candidate_id for s in registry.sources} <= {c.id for c in registry.candidates}
    assert registry.collection.since == date(2026, 7, 1)


def test_since_can_narrow_the_window_but_never_widen_it() -> None:
    window = date(2026, 7, 1)

    assert effective_since(None, window) == window
    assert effective_since(date(2026, 1, 1), window) == window
    assert effective_since(date(2026, 9, 1), window) == date(2026, 9, 1)


def test_every_enabled_source_kind_has_a_live_reader() -> None:
    registry = load_registry(CONFIG)
    crawler = CrawlerSettings(
        user_agent="Test/1.0 (+https://example.test)",
        min_delay_seconds=0,
        timeout_seconds=1,
        min_text_chars=1,
        max_redirects=1,
    )

    readers = _live_readers(httpx.Client(), crawler, FrozenClock(), CONFIG)

    assert {s.kind for s in registry.sources if s.enabled} <= readers.keys()


def test_every_configured_transcript_is_in_the_repository() -> None:
    transcripts = [s for s in load_registry(CONFIG).sources if s.kind == "transcript"]

    assert transcripts
    for source in transcripts:
        assert (CONFIG / source.options["file"]).read_text(encoding="utf-8").strip()


def _write_config(directory: Path, sources: str) -> Path:
    (directory / "candidates.yaml").write_text(
        "candidates:\n  - {id: camille-exemple, name: Camille Exemple, party: PE}\n",
        encoding="utf-8",
    )
    (directory / "sources.yaml").write_text(
        "collection: {since: 2026-07-01}\n"
        "crawler: {user_agent: 'Test/1.0 (+https://example.test)', min_delay_seconds: 1,\n"
        "          timeout_seconds: 5, min_text_chars: 10, max_redirects: 2}\n" + sources,
        encoding="utf-8",
    )
    shutil.copy(CONFIG / "segmentation.yaml", directory)
    return directory


def test_a_source_for_an_unknown_candidate_is_rejected(tmp_path: Path) -> None:
    config = _write_config(tmp_path, (
        "sources:\n  - {id: s, candidate_id: inconnu, kind: rss, url: 'https://x.test',"
        " trust_level: 2, label: X}\n"
    ))  # fmt: skip

    with pytest.raises(ConfigurationError, match="unknown candidate"):
        load_registry(config)


def test_duplicate_source_ids_are_rejected(tmp_path: Path) -> None:
    entry = (
        "  - {id: s, candidate_id: camille-exemple, kind: rss, url: 'https://x.test',"
        " trust_level: 2, label: X}\n"
    )
    config = _write_config(tmp_path, "sources:\n" + entry + entry)

    with pytest.raises(ConfigurationError, match="duplicate source"):
        load_registry(config)


def test_every_shipped_candidate_carries_a_sourced_candidacy() -> None:
    registry = load_registry(CONFIG)

    for candidate in registry.candidates:
        assert candidate.candidacy is not None, candidate.id
        assert all(url.startswith("https://") for url in candidate.candidacy.sources)


def test_a_candidacy_without_any_source_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Candidacy(status=CandidacyStatus.DECLARED, checked_on=date(2026, 10, 14), sources=())


def test_an_archive_capture_round_trips_and_a_fake_one_is_refused(tmp_path: Path) -> None:
    capture = "https://web.archive.org/web/20260918144520/https://parti-exemple.test/a"
    archived = document("Texte archivé.").model_copy(update={"archive_url": capture})
    repository = SqliteRepository(tmp_path / "corpus.db")

    repository.save(archived)

    assert repository.list_documents()[0].archive_url == capture
    with pytest.raises(ValidationError):
        document("x").model_validate(
            document("x").model_dump() | {"archive_url": "https://web.archive.org/web/2026/x"}
        )


def test_an_older_database_gains_the_archive_column(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE documents (content_hash TEXT PRIMARY KEY, source_id TEXT NOT NULL,"
            " candidate_id TEXT NOT NULL, url TEXT NOT NULL, title TEXT, text TEXT NOT NULL,"
            " published_on TEXT, fetched_at TEXT NOT NULL, trust_level INTEGER NOT NULL)"
        )

    SqliteRepository(path).save(document("Texte."))

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
    assert "archive_url" in columns


def test_annotations_round_trip_and_are_found_by_version(tmp_path: Path) -> None:
    repository = SqliteRepository(tmp_path / "corpus.db")
    annotation = SegmentAnnotation(
        segment_id="abc-000",
        segment_hash="h1",
        annotator_version="v1",
        annotated_at=T0,
        annotations=(),
    )

    repository.save_annotation(annotation)
    repository.save_annotation(annotation)

    assert repository.list_annotations() == [annotation]
    assert repository.annotated_segments("v1") == {"abc-000": "h1"}
    assert repository.annotated_segments("v2") == {}


def test_usage_is_added_up_per_step_and_model(tmp_path: Path) -> None:
    repository = SqliteRepository(tmp_path / "corpus.db")
    for tokens in (10, 30):
        repository.record_usage(
            UsageRecord(
                step="annotate", model="m", input_tokens=tokens, output_tokens=1, recorded_at=T0
            )
        )

    assert repository.usage_totals() == [("annotate", "m", 2, 40, 2)]


def test_the_taxonomy_loads_with_unique_dimensions_and_a_working_prefilter() -> None:
    taxonomy = load_registry(CONFIG).taxonomy

    assert len(taxonomy.dimension_ids) == len(set(taxonomy.dimension_ids)) == 9
    assert TermRelevanceFilter(taxonomy.relevance).is_relevant("Former à l'IA dès le lycée.")


def test_a_candidate_is_sorted_by_surname_and_withdrawn_people_are_not_running() -> None:
    people = {c.id: c for c in load_registry(CONFIG).candidates}

    assert (people["marine-le-pen"].given_name, people["marine-le-pen"].surname) == (
        "Marine",
        "Le Pen",
    )
    assert people["jean-luc-melenchon"].surname == "Mélenchon"
    assert not people["jordan-bardella"].is_running
    assert people["bruno-retailleau"].is_running
