"""End to end through the CLI: import a previous-version database, then render the corpus.

Fictional roster and texts; no network.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from observatoire.cli import main

CANDIDATES = """
candidates:
  - {id: camille-exemple, name: Camille Exemple, party: Parti Exemple, aliases: [Camille Exemple]}
  - {id: dominique-temoin, name: Dominique Témoin, party: Parti Témoin}
"""
SOURCES = """
crawler: {user_agent: "Test/1.0 (+https://example.test)", min_delay_seconds: 0,
          timeout_seconds: 5, min_text_chars: 10, max_redirects: 2}
sources:
  - {id: camille-exemple/rss/parti, candidate_id: camille-exemple, kind: rss,
     url: "https://parti-exemple.test/feed/", trust_level: 2, label: Parti Exemple — fil}
"""


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    (config / "candidates.yaml").write_text(CANDIDATES, encoding="utf-8")
    (config / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    monkeypatch.setenv("CONFIG_DIR", str(config))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "corpus.db"))
    monkeypatch.chdir(tmp_path)  # no stray .env from the repository
    return tmp_path


def _legacy(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE documents (url_hash TEXT PRIMARY KEY, person TEXT, source_id TEXT,"
            " fetched_at TEXT, payload TEXT)"
        )
        for index, text in enumerate(
            ["Camille Exemple parle du numérique.", "Communiqué du parti."]
        ):
            payload = {"kind": "rss", "url": f"https://parti-exemple.test/{index}", "text": text}
            connection.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?)",
                (
                    str(index),
                    "camille-exemple",
                    "x",
                    "2026-09-18T12:00:00+00:00",
                    json.dumps(payload),
                ),
            )
    return path


def test_import_then_render_the_raw_corpus(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = _legacy(workspace / "legacy.db")
    page = workspace / "corpus.html"

    assert main(["import-legacy", "--database", str(database)]) == 0
    assert main(["import-legacy", "--database", str(database)]) == 0
    assert main(["corpus", "--out", str(page)]) == 0

    out = capsys.readouterr().out
    assert "2 nouveaux documents" in out
    assert "0 nouveaux, 2 doublons" in out
    html = page.read_text(encoding="utf-8")
    assert "Camille Exemple parle du numérique." in html
    assert "cite Camille Exemple 1 fois" in html
    assert "ne cite pas Camille Exemple" in html
    assert "Non suivi" in html


def test_an_invalid_configuration_stops_before_any_work(workspace: Path) -> None:
    (workspace / "config" / "sources.yaml").write_text("sources: [", encoding="utf-8")

    assert main(["corpus", "--out", str(workspace / "x.html")]) == 2
