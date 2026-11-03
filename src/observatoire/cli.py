"""Composition root: the only module that instantiates concrete adapters and wires them.

Implemented: collect, import-legacy, segment, corpus, annotate, register, usage.
TODO: score, report and run-all, if the register ever publishes a score.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import date
from pathlib import Path

import httpx

from observatoire.adapters.extraction.trafilatura_extractor import TrafilaturaExtractor
from observatoire.adapters.llm.fake_llm_client import FakeLLMClient
from observatoire.adapters.llm.llm_annotator import LLMAnnotator
from observatoire.adapters.llm.mistral_client import MistralClient
from observatoire.adapters.llm.prompt_template import PromptTemplate
from observatoire.adapters.llm.recorded_llm_client import (
    BatchRequestWriter,
    RecordedLLMClient,
    load_answers,
)
from observatoire.adapters.reporting.corpus_html_renderer import CorpusHtmlRenderer
from observatoire.adapters.reporting.register_data_script import RegisterDataScript
from observatoire.adapters.reporting.static_site import write_site
from observatoire.adapters.sources.assemblee_nationale_reader import AssembleeNationaleReader
from observatoire.adapters.sources.html_page_reader import HtmlPageReader
from observatoire.adapters.sources.http_client import PoliteHttpClient, robots_fetcher
from observatoire.adapters.sources.legacy_pipeline_reader import LEGACY_KINDS, LegacyPipelineReader
from observatoire.adapters.sources.pdf_reader import PdfReader
from observatoire.adapters.sources.rss_reader import RssReader
from observatoire.adapters.storage.sqlite_repository import SqliteRepository
from observatoire.adapters.system_clock import SystemClock
from observatoire.application.annotate_documents import AnnotateDocuments
from observatoire.application.build_register import BuildRegister
from observatoire.application.collect_daily import CollectDaily
from observatoire.application.inspect_corpus import InspectCorpus
from observatoire.application.segment_documents import SegmentDocuments
from observatoire.config.registry import CrawlerSettings, Registry, load_registry
from observatoire.config.settings import Settings
from observatoire.domain.annotation import AnnotationReport
from observatoire.domain.errors import ConfigurationError
from observatoire.domain.models import CollectionReport, SegmentationReport, Source
from observatoire.domain.ports import Clock, LLMClient, SourceReader
from observatoire.observability.logging import configure_logging
from observatoire.observability.usage_tracker import UsageRecordingClient
from observatoire.services.ai_relevance import TermRelevanceFilter
from observatoire.services.annotation_gates import AnnotationGates
from observatoire.services.candidate_matcher import AliasMatcher
from observatoire.services.robots_policy import RobotsPolicy
from observatoire.services.segmentation import ParagraphSegmenter

Handler = Callable[[argparse.Namespace, Settings, Registry], int]
PROMPT = "classify_dimension.v1"
LLM_CHOICES = ("fake", "mistral", "recorded", "batch")


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
    collect.add_argument(
        "--since",
        type=date.fromisoformat,
        help="AAAA-MM-JJ ; jamais avant le début de la fenêtre de collecte (config/sources.yaml)",
    )
    collect.add_argument("--source-id", action="append", dest="source_ids", help="répétable")
    collect.set_defaults(handler=_collect)
    legacy = commands.add_parser(
        "import-legacy", help="importe la base de la version précédente (branche daily)"
    )
    legacy.add_argument("--database", type=Path, default=Path("data/raw/legacy-daily.db"))
    legacy.set_defaults(handler=_import_legacy)
    segment = commands.add_parser("segment", help="découpe les documents collectés en passages")
    segment.add_argument(
        "--rebuild",
        action="store_true",
        help="tout redécouper, même si les règles n'ont pas changé",
    )
    segment.set_defaults(handler=_segment)
    corpus = commands.add_parser("corpus", help="écrit la vue HTML du corpus brut")
    corpus.add_argument("--out", type=Path, default=Path("data/reports/corpus.html"))
    corpus.add_argument(
        "--fragment",
        action="store_true",
        help="sans <html>/<head>/<body>, pour un hôte qui les ajoute",
    )
    corpus.set_defaults(handler=_corpus)
    _add_annotate(commands)
    register = commands.add_parser("register", help="construit le site du registre public")
    register.add_argument("--out", type=Path, default=Path("data/site"))
    register.add_argument("--template", type=Path, default=Path("web/registre"))
    register.set_defaults(handler=_register)
    usage = commands.add_parser("usage", help="tokens consommés par étape et par modèle")
    usage.set_defaults(handler=_usage)
    return parser


def _add_annotate(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    annotate = commands.add_parser(
        "annotate", help="repère et classe les déclarations sur l'IA, passage par passage"
    )
    annotate.add_argument(
        "--llm",
        choices=LLM_CHOICES,
        help="fake | mistral | recorded (rejoue --responses) | batch (écrit --batch-out) ;"
        " défaut : LLM_PROVIDER",
    )
    annotate.add_argument("--responses", type=Path, help="réponses enregistrées (JSONL)")
    annotate.add_argument(
        "--batch-out", type=Path, default=Path("data/llm/requests.jsonl"), help="requêtes (JSONL)"
    )
    annotate.add_argument("--limit", type=int, help="nombre maximal de passages envoyés")
    annotate.set_defaults(handler=_annotate)


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
        since = effective_since(args.since, registry.collection.since)
        report = use_case.run(sources, run_id=_run_id("collect", clock), since=since)
    _print_report(report)
    return 0


def _import_legacy(args: argparse.Namespace, settings: Settings, registry: Registry) -> int:
    clock = SystemClock()
    reader = LegacyPipelineReader(args.database)
    readers: dict[str, SourceReader] = {kind: reader for kind in LEGACY_KINDS}
    with closing(SqliteRepository(settings.database_path)) as repository:
        use_case = CollectDaily(readers, repository, repository, clock)
        # Every configured source, disabled ones included: `enabled` governs live runs.
        report = use_case.run(
            registry.sources,
            run_id=_run_id("import-legacy", clock),
            since=registry.collection.since,
        )
    _print_report(report)
    return 0


def _segment(args: argparse.Namespace, settings: Settings, registry: Registry) -> int:
    segmenter = ParagraphSegmenter(registry.segmentation)
    matcher = AliasMatcher(registry.candidates)
    with closing(SqliteRepository(settings.database_path)) as repository:
        use_case = SegmentDocuments(repository, repository, segmenter, matcher)
        report = use_case.run(
            registry.sources, rebuild=args.rebuild, since=registry.collection.since
        )
    _print_segmentation(report)
    return 0


def _corpus(args: argparse.Namespace, settings: Settings, registry: Registry) -> int:
    clock = SystemClock()
    matcher = AliasMatcher(registry.candidates)
    with closing(SqliteRepository(settings.database_path)) as repository:
        use_case = InspectCorpus(repository, repository, matcher, clock, segments=repository)
        overview = use_case.build(
            registry.candidates, registry.sources, since=registry.collection.since
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    renderer = CorpusHtmlRenderer(standalone=not args.fragment)
    args.out.write_text(renderer.render(overview), encoding="utf-8")
    print(f"Vue du corpus écrite dans {args.out}")
    return 0


def _annotate(args: argparse.Namespace, settings: Settings, registry: Registry) -> int:
    clock = SystemClock()
    taxonomy = registry.taxonomy
    with (
        httpx.Client(timeout=registry.crawler.timeout_seconds) as http,
        closing(SqliteRepository(settings.database_path)) as repository,
    ):
        client = _llm_client(args, settings, http)
        if client is None:
            return 2
        if not isinstance(client, BatchRequestWriter):
            client = UsageRecordingClient(client, repository, clock, "annotate")
        annotator = LLMAnnotator(
            client, PromptTemplate(PROMPT, taxonomy.dimensions), taxonomy.dimension_ids
        )
        use_case = AnnotateDocuments(
            corpus=repository,
            segments=repository,
            store=repository,
            annotator=annotator,
            relevance=TermRelevanceFilter(taxonomy.relevance),
            reviewer=AnnotationGates(taxonomy.dimension_ids, taxonomy.gates),
            clock=clock,
        )
        report = use_case.run(
            registry.candidates,
            registry.sources,
            since=registry.collection.since,
            limit=args.limit,
        )
    _print_annotation(report)
    if isinstance(client, BatchRequestWriter):
        args.batch_out.parent.mkdir(parents=True, exist_ok=True)
        lines = client.lines()
        args.batch_out.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        print(f"{len(lines)} requête(s) écrite(s) dans {args.batch_out}")
    return 0


def _llm_client(
    args: argparse.Namespace, settings: Settings, http: httpx.Client
) -> LLMClient | None:
    choice = args.llm or settings.llm_provider
    if choice == "recorded":
        if args.responses is None or not args.responses.is_file():
            print("--llm recorded demande --responses <fichier JSONL>", file=sys.stderr)
            return None
        return RecordedLLMClient(load_answers(args.responses))
    if choice == "fake":
        return FakeLLMClient()
    if not settings.mistral_model:
        print("MISTRAL_MODEL n'est pas défini (.env)", file=sys.stderr)
        return None
    if choice == "batch":
        return BatchRequestWriter(settings.mistral_model)
    if settings.mistral_api_key is None:
        print("MISTRAL_API_KEY n'est pas défini (.env)", file=sys.stderr)
        return None
    key = settings.mistral_api_key.get_secret_value()
    return MistralClient(http, api_key=key, model=settings.mistral_model)


def _register(args: argparse.Namespace, settings: Settings, registry: Registry) -> int:
    if not (args.template / "index.html").is_file():
        print(f"Gabarit du site introuvable : {args.template}/index.html", file=sys.stderr)
        return 2
    with closing(SqliteRepository(settings.database_path)) as repository:
        use_case = BuildRegister(
            corpus=repository, segments=repository, annotations=repository, clock=SystemClock()
        )
        register = use_case.build(
            registry.candidates,
            registry.sources,
            registry.taxonomy.dimensions,
            since=registry.collection.since,
        )
    page = write_site(args.template, args.out, RegisterDataScript().render(register))
    tracked = sum(1 for c in register.candidates if c.monitored)
    print(
        f"Registre : {len(register.entries)} déclaration(s), {len(register.candidates)}"
        f" candidat(s) dont {tracked} suivi(s) ; annotateur {register.annotator_version}"
    )
    if register.withdrawn:
        print(f"  Hors registre (retrait) : {', '.join(c.name for c in register.withdrawn)}")
    print(f"Site écrit dans {page}")
    return 0


def _usage(args: argparse.Namespace, settings: Settings, registry: Registry) -> int:
    with closing(SqliteRepository(settings.database_path)) as repository:
        totals = repository.usage_totals()
    if not totals:
        print("Aucun appel enregistré.")
    for step, model, calls, tokens_in, tokens_out in totals:
        print(
            f"  {step:10} {model:40} {calls:5} appels  {tokens_in:9} entrée  {tokens_out:9} sortie"
        )
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


def effective_since(requested: date | None, window_start: date) -> date:
    """`--since` can narrow the collection window, never widen it."""
    if requested is not None and requested < window_start:
        print(f"--since {requested} précède la fenêtre de collecte : {window_start} s'applique")
    return max(requested or window_start, window_start)


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
        if outcome.out_of_window:
            counts += f", {outcome.out_of_window} hors fenêtre"
        print(f"  {status:6} {outcome.source_id:42} {counts}")
        if outcome.error:
            print(f"         {outcome.error}")


def _print_segmentation(report: SegmentationReport) -> None:
    changed = [o for o in report.outcomes if o.resegmented]
    segments = sum(o.segments for o in changed)
    version = report.segmenter_version
    print(f"Segmenteur {version} : {len(changed)} source(s) découpée(s), {segments} segments")
    for outcome in report.outcomes:
        if not outcome.resegmented:
            print(f"  {outcome.source_id:42} inchangée")
            continue
        counts = f"{outcome.documents} documents, {outcome.segments} segments"
        print(
            f"  {outcome.source_id:42} {counts}, {outcome.empty_documents} sans contenu exploitable"
        )
        reasons = ", ".join(f"{reason.value} {n}" for reason, n in sorted(outcome.excluded.items()))
        if reasons:
            print(f"  {'':42} exclus : {reasons}")
    if report.unconfigured_documents:
        print(f"  {report.unconfigured_documents} document(s) d'une source non configurée, ignorés")
    if report.out_of_window_documents:
        print(f"  {report.out_of_window_documents} document(s) publiés avant la fenêtre, ignorés")


def _print_annotation(report: AnnotationReport) -> None:
    print(f"Annotateur {report.annotator_version}")
    print(
        f"  {report.segments_read} passages lus, {report.not_relevant} écartés par le filtre IA,"
        f" {report.already_annotated} déjà annotés"
    )
    print(
        f"  {report.annotated} annotés ({report.empty} sans déclaration),"
        f" {report.statements} déclaration(s) retenue(s), {report.failed} sans réponse,"
        f" {report.pending} en attente"
    )
    reasons = ", ".join(f"{reason.value} {n}" for reason, n in sorted(report.rejected.items()))
    if reasons:
        print(f"  propositions rejetées : {reasons}")
