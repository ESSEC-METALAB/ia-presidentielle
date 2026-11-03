"""End to end through the CLI: import a previous-version database, then render the corpus.

Fictional roster and texts; no network.
"""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from observatoire.cli import main

CANDIDATES = """
candidates:
  - {id: camille-exemple, name: Camille Exemple, party: Parti Exemple, aliases: [Camille Exemple]}
  - {id: dominique-temoin, name: Dominique Témoin, party: Parti Témoin}
"""
REPOSITORY = Path(__file__).resolve().parents[2]
SOURCES = """
collection: {since: 2026-07-01}
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
    shutil.copy(REPOSITORY / "config" / "segmentation.yaml", config)
    shutil.copy(REPOSITORY / "config" / "taxonomy.yaml", config)
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


AI_TEXT = (
    "Camille Exemple propose une autorité de contrôle de l'IA dotée de vrais pouvoirs"
    " d'enquête sur les systèmes à haut risque."
)
STATEMENT = {
    "dimension": "regulation",
    "quote": "une autorité de contrôle de l'IA dotée de vrais pouvoirs d'enquête",
    "summary_fr": "Propose une autorité de contrôle dotée de pouvoirs d'enquête.",
    "summary_en": "Proposes an oversight authority with investigative powers.",
    "context_fr": "Systèmes d'IA à haut risque.",
    "context_en": "High-risk AI systems.",
    "gloss_en": "an AI oversight authority with real investigative powers",
}


def _legacy_with(path: Path, text: str) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE documents (url_hash TEXT PRIMARY KEY, person TEXT, source_id TEXT,"
            " fetched_at TEXT, payload TEXT)"
        )
        payload = {"kind": "rss", "url": "https://parti-exemple.test/ia", "text": text,
                   "title": "Notre plan", "date": "2026-09-20"}  # fmt: skip
        connection.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?)",
            ("0", "camille-exemple", "x", "2026-09-21T08:00:00+00:00", json.dumps(payload)),
        )
    return path


def test_a_batch_answered_offline_is_replayed_into_the_register_site(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MISTRAL_MODEL", "model-test")
    template = workspace / "template"
    template.mkdir()
    (template / "index.html").write_text("<script src='./data.js'></script>", encoding="utf-8")
    requests, answers = workspace / "requests.jsonl", workspace / "answers.jsonl"
    assert (
        main(["import-legacy", "--database", str(_legacy_with(workspace / "l.db", AI_TEXT))]) == 0
    )
    assert main(["segment"]) == 0

    assert main(["annotate", "--llm", "batch", "--batch-out", str(requests)]) == 0
    (request,) = [json.loads(line) for line in requests.read_text(encoding="utf-8").splitlines()]
    answer = {"statements": [STATEMENT]}
    answers.write_text(
        json.dumps(
            {"custom_id": request["custom_id"], "model": "draft", "content": json.dumps(answer)}
        )
        + "\n",
        encoding="utf-8",
    )
    assert main(["annotate", "--llm", "recorded", "--responses", str(answers)]) == 0
    assert main(["annotate", "--llm", "recorded", "--responses", str(answers)]) == 0
    assert main(["register", "--out", str(workspace / "site"), "--template", str(template)]) == 0
    assert main(["usage"]) == 0

    out = capsys.readouterr().out
    assert "1 requête(s) écrite(s)" in out
    assert "1 déclaration(s) retenue(s)" in out
    assert "1 déjà annotés" in out  # the second replay sends nothing
    assert "annotate   draft" in out
    data = (workspace / "site" / "data.js").read_text(encoding="utf-8")
    assert STATEMENT["quote"] in data
    assert '"tracked": true' in data


def test_annotate_without_what_it_needs_stops_before_any_work(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MISTRAL_MODEL", raising=False)

    assert main(["annotate", "--llm", "recorded"]) == 2
    assert main(["annotate", "--llm", "mistral"]) == 2
    monkeypatch.setenv("MISTRAL_MODEL", "model-test")
    assert main(["annotate", "--llm", "mistral"]) == 2  # no key


def test_the_fake_annotator_runs_offline_and_finds_nothing(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(["import-legacy", "--database", str(_legacy_with(workspace / "l.db", AI_TEXT))]) == 0
    )
    assert main(["segment"]) == 0

    assert main(["annotate", "--llm", "fake"]) == 0

    assert "0 déclaration(s) retenue(s)" in capsys.readouterr().out


def test_register_without_its_site_template_stops_cleanly(workspace: Path) -> None:
    assert main(["register", "--out", str(workspace / "site")]) == 2
