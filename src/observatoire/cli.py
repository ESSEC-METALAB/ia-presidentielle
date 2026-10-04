"""Composition root: the only module that instantiates concrete adapters and wires them.

Implemented: collect, import-legacy, corpus. TODO(step 5): annotate, score, report,
run-all and usage, with the analysis use cases.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import date
from pathlib import Path

import httpx

from observatoire.adapters.extraction.trafilatura_extractor import TrafilaturaExtractor
from observatoire.adapters.reporting.corpus_html_renderer import CorpusHtmlRenderer
from observatoire.adapters.sources.assemblee_nationale_reader import AssembleeNationaleReader
from observatoire.adapters.sources.html_page_reader import HtmlPageReader
from observatoire.adapters.sources.http_client import PoliteHttpClient, robots_fetcher
from observatoire.adapters.sources.legacy_pipeline_reader import LEGACY_KINDS, LegacyPipelineReader
from observatoire.adapters.sources.pdf_reader import PdfReader
from observatoire.adapters.sources.rss_reader import RssReader
from observatoire.adapters.storage.sqlite_repository import SqliteRepository
from observatoire.adapters.system_clock import SystemClock
from observatoire.application.collect_daily import CollectDaily
from observatoire.application.inspect_corpus import InspectCorpus
from observatoire.config.registry import CrawlerSettings, Registry, load_registry
from observatoire.config.settings import Settings
from observatoire.domain.errors import ConfigurationError
from observatoire.domain.models import CollectionReport, Source
from observatoire.domain.ports import Clock, SourceReader
from observatoire.observability.logging import configure_logging
from observatoire.services.candidate_matcher import AliasMatcher
from observatoire.services.robots_policy import RobotsPolicy

Handler = Callable[[argparse.Namespace, Settings, Registry], int]


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point declared in pyproject.toml."""
    args = _parser().parse_args(argv)
    settings = Settings()
    configure_logging(settings.log_level)
    try:
        registry = load_registry(settings.config_dir)
    except ConfigurationError as error:
        print(f"Configuration invalide : {error}", file=sys.stderr)
        return 2
    handler: Handler = args.handler
    return handler(args, settings, registry)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="observatoire", description="Observatoire IA 2027 : collecte et corpus brut."
    )
    commands = parser.add_subparsers(required=True, metavar="commande")
    collect = commands.add_parser("collect", help="collecte les sources actives (réseau requis)")
    collect.add_argument("--since", type=date.fromisoformat, help="AAAA-MM-JJ")
    collect.add_argument("--source-id", action="append", dest="source_ids", help="répétable")
    collect.set_defaults(handler=_collect)
    legacy = commands.add_parser(
        "import-legacy", help="importe la base de la version précédente (branche daily)"
    )
    legacy.add_argument("--database", type=Path, default=Path("data/raw/legacy-daily.db"))
    legacy.set_defaults(handler=_import_legacy)
    corpus = commands.add_parser("corpus", help="écrit la vue HTML du corpus brut")
    corpus.add_argument("--out", type=Path, default=Path("data/reports/corpus.html"))
    corpus.add_argument(
        "--fragment",
        action="store_true",
        help="sans <html>/<head>/<body>, pour un hôte qui les ajoute",
    )
    corpus.set_defaults(handler=_corpus)
    return parser


def _collect(args: argparse.Namespace, settings: Settings, registry: Registry) -> int:
    sources = _selected(registry.sources, args.source_ids)
    if sources is None:
        print(f"Source inconnue ou désactivée parmi : {args.source_ids}", file=sys.stderr)
        return 2
    clock = SystemClock()
    crawler = registry.crawler
    headers = {"User-Agent": crawler.user_agent}
    with (
        httpx.Client(headers=headers, timeout=crawler.timeout_seconds) as client,
        closing(SqliteRepository(settings.database_path)) as repository,
    ):
        readers = _live_readers(client, crawler, clock)
        use_case = CollectDaily(readers, repository, repository, clock)
        report = use_case.run(sources, run_id=_run_id("collect", clock), since=args.since)
    _print_report(report)
    return 0


def _import_legacy(args: argparse.Namespace, settings: Settings, registry: Registry) -> int:
    clock = SystemClock()
    reader = LegacyPipelineReader(args.database)
    readers: dict[str, SourceReader] = {kind: reader for kind in LEGACY_KINDS}
    with closing(SqliteRepository(settings.database_path)) as repository:
        use_case = CollectDaily(readers, repository, repository, clock)
        # Every configured source, disabled ones included: `enabled` governs live runs.
        report = use_case.run(registry.sources, run_id=_run_id("import-legacy", clock))
    _print_report(report)
    return 0


def _corpus(args: argparse.Namespace, settings: Settings, registry: Registry) -> int:
    clock = SystemClock()
    with closing(SqliteRepository(settings.database_path)) as repository:
        use_case = InspectCorpus(repository, repository, AliasMatcher(registry.candidates), clock)
        overview = use_case.build(registry.candidates, registry.sources)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    renderer = CorpusHtmlRenderer(standalone=not args.fragment)
    args.out.write_text(renderer.render(overview), encoding="utf-8")
    print(f"Vue du corpus écrite dans {args.out}")
    return 0


def _live_readers(
    client: httpx.Client, crawler: CrawlerSettings, clock: Clock
) -> dict[str, SourceReader]:
    policy = RobotsPolicy(crawler.user_agent, crawler.min_delay_seconds, robots_fetcher(client))
    http = PoliteHttpClient(client, policy, crawler.max_redirects)
    extractor = TrafilaturaExtractor(crawler.min_text_chars)
    return {
        "rss": RssReader(http, extractor, clock),
        "page": HtmlPageReader(http, extractor, clock),
        "pdf": PdfReader(http, clock),
        "assemblee_nationale": AssembleeNationaleReader(http, clock),
    }


def _selected(sources: Sequence[Source], ids: list[str] | None) -> list[Source] | None:
    enabled = [source for source in sources if source.enabled]
    if not ids:
        return enabled
    chosen = [source for source in enabled if source.id in ids]
    return chosen if len(chosen) == len(set(ids)) else None


def _run_id(prefix: str, clock: Clock) -> str:
    return f"{prefix}-{clock.now():%Y%m%dT%H%M%SZ}"


def _print_report(report: CollectionReport) -> None:
    failed = len(report.failed_sources)
    print(
        f"{report.run_id} : {report.new_documents} nouveaux documents, {failed} source(s) en échec"
    )
    for outcome in report.outcomes:
        status = "ok" if outcome.status == "ok" else "ÉCHEC"
        counts = f"{outcome.fetched} lus, {outcome.new} nouveaux, {outcome.duplicates} doublons"
        print(f"  {status:6} {outcome.source_id:42} {counts}")
        if outcome.error:
            print(f"         {outcome.error}")
