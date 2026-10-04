"""SQLite storage and config loading."""

import shutil
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from observatoire.adapters.storage.sqlite_repository import SqliteRepository
from observatoire.cli import _live_readers
from observatoire.config.registry import CrawlerSettings, load_registry
from observatoire.domain.errors import ConfigurationError
from observatoire.domain.models import (
    CandidateMention,
    DocumentSegmentation,
    ExcludedPassage,
    ExclusionReason,
    Segment,
    SourceOutcome,
)
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


def test_the_shipped_configuration_is_valid() -> None:
    registry = load_registry(CONFIG)

    assert {s.candidate_id for s in registry.sources} <= {c.id for c in registry.candidates}


def test_every_enabled_source_kind_has_a_live_reader() -> None:
    registry = load_registry(CONFIG)
    crawler = CrawlerSettings(
        user_agent="Test/1.0 (+https://example.test)",
        min_delay_seconds=0,
        timeout_seconds=1,
        min_text_chars=1,
        max_redirects=1,
    )

    readers = _live_readers(httpx.Client(), crawler, FrozenClock())

    assert {s.kind for s in registry.sources if s.enabled} <= readers.keys()


def _write_config(directory: Path, sources: str) -> Path:
    (directory / "candidates.yaml").write_text(
        "candidates:\n  - {id: camille-exemple, name: Camille Exemple, party: PE}\n",
        encoding="utf-8",
    )
    (directory / "sources.yaml").write_text(
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
