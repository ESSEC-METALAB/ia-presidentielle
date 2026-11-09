"""The register site template (web/registre/index.html), checked without a browser.

The prototype's runtime catches a script error and shows a red notice instead of failing:
a broken quote in a translation once blanked every page while every other test passed.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from observatoire.config.registry import load_registry

TEMPLATE = Path(__file__).resolve().parents[2] / "web" / "registre" / "index.html"
HTML = TEMPLATE.read_text(encoding="utf-8")
CONFIG = TEMPLATE.parents[2] / "config"
SCRIPT = re.search(r'<script type="text/x-dc"[^>]*>(.*?)</script>', HTML, re.DOTALL)
# Addresses the page may contain without loading them: XML namespaces.
NOT_FETCHED = re.compile(r"http://www\.w3\.org/")


def test_the_component_script_is_found() -> None:
    assert SCRIPT is not None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_component_script_parses() -> None:
    assert SCRIPT is not None
    code = SCRIPT.group(1).replace("class Component extends DCLogic", "class Component")
    check = subprocess.run(
        ["node", "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"],
        input=code,
        capture_output=True,
        text=True,
        check=False,
    )

    assert check.returncode == 0, check.stderr


def test_the_page_loads_nothing_from_the_internet() -> None:
    addresses = re.findall(r"https?://[^\s\"'<>)]+", HTML)

    fetched = [a for a in addresses if not NOT_FETCHED.match(a)]

    assert fetched == []


def test_every_interface_string_exists_in_french_and_english() -> None:
    assert SCRIPT is not None
    i18n = SCRIPT.group(1).split("const SLUGS", 1)[0]
    french, english = i18n.split("\n  en: {", 1)
    used = set(re.findall(r"\{\{\s*t\.([A-Za-z]+)", HTML)) | set(
        # Only in renderVals, where `t` is the translation table (elsewhere it is a DOM node).
        re.findall(r"\bt\.([A-Za-z]+)\b", SCRIPT.group(1).split("renderVals()", 1)[1])
    )

    missing = {
        key: [lang for lang, block in (("fr", french), ("en", english)) if f"{key}:" not in block]
        for key in used
    }

    assert {k: v for k, v in missing.items() if v} == {}


def test_the_runtime_is_never_switched_to_bundled_mode() -> None:
    """window.__resources makes the runtime skip re-reading the page's template; the
    browser's parse of the barometer's <table> then loses its row loop (measured)."""
    assert "__resources" not in HTML.replace("Never define window.__resources here", "")


def test_every_axis_of_the_taxonomy_has_an_icon_and_a_colour() -> None:
    icons = re.search(r"^  axis: \{(.*)\},$", HTML, re.MULTILINE)
    hues = re.search(r"^const AX_HUE = \{(.*)\};$", HTML, re.MULTILINE)
    assert icons
    assert hues

    for axis in load_registry(CONFIG).taxonomy.dimension_ids:
        key = rf'(^|[ {{,])"?{re.escape(axis)}"?:'
        assert re.search(key, icons.group(1)), axis
        assert re.search(key, hues.group(1)), axis
