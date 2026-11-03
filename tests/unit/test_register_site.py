"""The register's data script and site writer, on a fictional register."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from observatoire.adapters.reporting.register_data_script import RegisterDataScript
from observatoire.adapters.reporting.static_site import write_site
from observatoire.domain.annotation import Dimension, DimensionAnnotation
from observatoire.domain.models import Candidate, TrustLevel
from observatoire.domain.register import Register, RegisterCandidate, RegisterEntry
from support import document, source

CAPTURE = "https://web.archive.org/web/20260918144520/https://parti-exemple.test/1"
STATEMENT = DimensionAnnotation(
    segment_id="abc-000",
    index=0,
    dimension="regulation",
    quote="une autorité de contrôle",
    quote_span=(0, 24),
    summary_fr="Propose une autorité.",
    summary_en="Proposes an authority.",
    context_fr="Texte fictif.",
    context_en="Fictional text.",
    gloss_en="an oversight authority",
)


def _register() -> Register:
    person = Candidate(
        id="camille-de-exemple",
        name="Camille de Exemple",
        family_name="de Exemple",
        party="Parti Exemple",
        party_short="PE",
    )
    hall = source("camille-de-exemple/an/PA1", kind="assemblee_nationale")
    hall = hall.model_copy(update={"trust_confirmed": True, "trust_level": TrustLevel.OWN_WORDS})
    archived = document("Texte fictif.", trust_level=TrustLevel.OWN_WORDS).model_copy(
        update={"archive_url": CAPTURE}
    )
    return Register(
        generated_at=datetime(2026, 11, 3, 18, 0, tzinfo=UTC),
        window_start=date(2026, 7, 1),
        dimensions=(
            Dimension(
                id="regulation",
                label_fr="Régulation",
                label_en="Regulation",
                definition_fr="Règles,\n  interdictions.",
                definition_en="Rules.",
            ),
        ),
        candidates=(RegisterCandidate(candidate=person, sources=(hall,)),),
        entries=(
            RegisterEntry(
                annotation=STATEMENT,
                document=archived,
                source=hall,
                annotator_version="edition",
                verified=True,
            ),
            RegisterEntry(
                annotation=STATEMENT.model_copy(update={"index": 1}),
                document=document("Autre texte.", published_on=None),
                source=source(),
                annotator_version="daily",
            ),
        ),
        annotators=("edition", "daily"),
        pending={"camille-de-exemple": 2},
    )


def _data(script: str) -> Any:  # parsed JSON, read by the assertions
    prefix = "window.IA2027_DATA = "
    body = script[script.index(prefix) + len(prefix) :].rstrip().removesuffix(";")
    return json.loads(body)


def test_the_script_follows_the_site_prototypes_shape() -> None:
    data = _data(RegisterDataScript().render(_register()))

    assert set(data) >= {"generated", "axes", "candidates", "claims", "corrections"}
    assert (data["annotators"], data["pending"]) == (["edition", "daily"], 2)
    assert data["generated"] == "2026-11-03"
    assert data["axes"] == [
        {
            "id": "regulation",
            "fr": "Régulation",
            "en": "Regulation",
            "descFr": "Règles, interdictions.",
            "descEn": "Rules.",
        }
    ]


def test_a_candidate_is_listed_by_surname_with_what_we_listen_to() -> None:
    (person,) = _data(RegisterDataScript().render(_register()))["candidates"]

    assert (person["first"], person["last"], person["partyShort"]) == (
        "Camille",
        "de Exemple",
        "PE",
    )
    assert person["tracked"] is True
    assert person["pending"] == 2
    assert person["sources"][0]["url"].startswith("https://")


def test_a_statement_carries_its_source_archive_and_confirmed_level() -> None:
    first, second = _data(RegisterDataScript().render(_register()))["claims"]

    assert (first["kind"], first["tier"], first["tierConfirmed"]) == ("seance", 1, True)
    assert (first["archiveUrl"], first["archiveDate"]) == (CAPTURE, "2026-09-18")
    assert first["quote"] == "une autorité de contrôle"
    assert first["sourceLabel"].startswith("parti-exemple.test — ")
    assert (second["date"], second["archiveUrl"], second["kind"]) == (None, None, "article")
    assert (first["verified"], second["verified"]) == (True, False)


def test_the_site_is_the_template_plus_the_generated_data(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    (template / "index.html").write_text("<script src='./data.js'></script>", encoding="utf-8")
    (template / "data.js").write_text("// placeholder", encoding="utf-8")

    page = write_site(template, tmp_path / "site", "window.IA2027_DATA = {};\n")

    assert page.read_text(encoding="utf-8").startswith("<script")
    assert (page.parent / "data.js").read_text(encoding="utf-8") == "window.IA2027_DATA = {};\n"
