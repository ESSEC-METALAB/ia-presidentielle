"""Architecture fitness tests: every module imports, and dependencies point inwards.

The layer rules are CLAUDE.md §2 and §3 (D). They are checked on the source, so a
violation fails `make check` before any behaviour depends on it.
"""

import ast
import importlib
import pkgutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import observatoire

PACKAGE_ROOT = Path(observatoire.__file__).parent
DOMAIN_THIRD_PARTY_ALLOWED = frozenset({"pydantic"})
IO_STDLIB_MODULES = frozenset(
    {"ftplib", "http", "smtplib", "socket", "sqlite3", "ssl", "subprocess", "urllib"}
)
APPLICATION_FORBIDDEN_PREFIXES = ("observatoire.adapters", "observatoire.cli")


def _module_names() -> list[str]:
    prefix = f"{observatoire.__name__}."
    return sorted(info.name for info in pkgutil.walk_packages(observatoire.__path__, prefix))


def _layer_files(layer: str) -> list[Path]:
    return sorted((PACKAGE_ROOT / layer).rglob("*.py"))


def _package_of(path: Path) -> str:
    return ".".join(("observatoire", *path.parent.relative_to(PACKAGE_ROOT).parts))


def _absolute_module(node: ast.ImportFrom, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    parts = package.split(".")
    base = parts[: len(parts) - node.level + 1]
    return ".".join([*base, node.module] if node.module else base)


def _imported_modules(source: str, package: str) -> Iterator[str]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _absolute_module(node, package)
            yield from (f"{module}.{alias.name}" for alias in node.names)


def _imports_of(path: Path) -> list[str]:
    return list(_imported_modules(path.read_text(encoding="utf-8"), _package_of(path)))


def _is_allowed_in_domain(module: str) -> bool:
    top_level = module.partition(".")[0]
    if top_level == "observatoire":
        return module == "observatoire.domain" or module.startswith("observatoire.domain.")
    if top_level in IO_STDLIB_MODULES:
        return False
    return top_level in sys.stdlib_module_names or top_level in DOMAIN_THIRD_PARTY_ALLOWED


def _relative_id(path: Path) -> str:
    return str(path.relative_to(PACKAGE_ROOT))


@pytest.mark.parametrize("module_name", _module_names())
def test_every_module_imports(module_name: str) -> None:
    module = importlib.import_module(module_name)

    assert module.__name__ == module_name


def test_import_scan_resolves_plain_relative_and_from_imports() -> None:
    source = "import sqlite3\nfrom ..adapters import storage\nfrom pydantic import BaseModel\n"

    modules = set(_imported_modules(source, package="observatoire.application"))

    assert modules == {"sqlite3", "observatoire.adapters.storage", "pydantic.BaseModel"}


@pytest.mark.parametrize(
    ("module", "allowed"),
    [
        ("datetime", True),
        ("pydantic.BaseModel", True),
        ("observatoire.domain.models", True),
        ("sqlite3", False),
        ("httpx", False),
        ("observatoire.adapters.storage", False),
        ("observatoire.domainx", False),
    ],
)
def test_domain_rule_admits_stdlib_and_pydantic_only(module: str, allowed: bool) -> None:
    assert _is_allowed_in_domain(module) is allowed


@pytest.mark.parametrize("path", _layer_files("domain"), ids=_relative_id)
def test_domain_depends_on_nothing_outside_itself(path: Path) -> None:
    violations = [module for module in _imports_of(path) if not _is_allowed_in_domain(module)]

    assert violations == []


@pytest.mark.parametrize("path", _layer_files("application"), ids=_relative_id)
def test_application_never_imports_adapters_or_the_composition_root(path: Path) -> None:
    imports = _imports_of(path)

    violations = [module for module in imports if module.startswith(APPLICATION_FORBIDDEN_PREFIXES)]

    assert violations == []
