# Observatoire IA 2027 — POC. `make` alone lists the targets.
#
# Every tool runs through `uv run`, so versions come from uv.lock, not from whatever is on
# PATH. Without uv: `make install-pip`, activate .venv, then pass `RUN=` to any target,
# e.g. `make check RUN=`.

.DEFAULT_GOAL := help
UV ?= uv
RUN ?= $(UV) run --extra dev
DATA_DIRS := data/raw data/processed data/reports

.PHONY: help install install-pip format lint typecheck test check demo clean

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Create .venv and install the package and dev tools (uv)
	$(UV) sync --extra dev
	mkdir -p $(DATA_DIRS)

install-pip: ## Fallback without uv: venv + editable pip install
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	mkdir -p $(DATA_DIRS)

format: ## Rewrite sources with ruff format and ruff check --fix
	$(RUN) ruff format src tests
	$(RUN) ruff check --fix src tests

lint: ## ruff format --check and ruff check
	$(RUN) ruff format --check src tests
	$(RUN) ruff check src tests

typecheck: ## mypy --strict on sources and tests
	$(RUN) mypy src tests

test: ## pytest with the coverage floor (80 % on domain/ and application/)
	$(RUN) pytest --cov --cov-report=term-missing

check: lint typecheck test ## Everything that must pass before a task is done

demo: ## Full offline pipeline on fixtures, no network, no API key (works from step 6)
	mkdir -p $(DATA_DIRS)
	$(RUN) observatoire run-all --offline

clean: ## Remove caches and build output (never data/)
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist
