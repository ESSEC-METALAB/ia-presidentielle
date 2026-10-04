"""View model of the raw-corpus page: everything the template prints, computed here.

Pure functions of a CorpusOverview, so the page is testable without a browser and
the template stays a loop over ready-made values.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

from observatoire.adapters.reporting.segmentation_view import (
    DocumentSegments,
    SegmentationSummary,
    document_segments,
    summarize,
)
from observatoire.domain.models import (
    CandidateCorpus,
    CorpusOverview,
    DocumentView,
    RawDocument,
    SourceCorpus,
    TrustLevel,
)

_MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
           "nov.", "déc.")  # fmt: skip
_KIND_LABELS = {
    "rss": "Fil RSS",
    "page": "Page",
    "pdf": "PDF",
    "assemblee_nationale": "Compte rendu AN",
    "sitemap": "Archives du site",
}
_LEVEL_LABELS = {1: "paroles propres", 2: "parti", 3: "presse", 4: "tiers"}
_STATUS_LABELS = {
    "ok": "Collectée",
    "failed": "Échec",
    "disabled": "Désactivée",
    "never": "Jamais collectée",
}
_EXCERPT_CHARS = 280

# Chart geometry, in SVG user units.
_LABEL_WIDTH = 150
_SLOT = 22
_BAR = 12
_ROW = 56
_BAR_MAX = 40
_AXIS = 26
_GAP = 2
_RADIUS = 4
_MIN_SEGMENT = 3
_TICK_EVERY = 4
_RIGHT_MARGIN = 32  # room for the last month label, centred on the last column


@dataclass(frozen=True)
class SourceRow:
    label: str
    kind_label: str
    level: int
    level_label: str
    url: str | None
    status: str
    status_label: str
    run_label: str
    fetched: int
    new: int
    duplicates: int
    error: str | None
    documents: int
    characters: str


@dataclass(frozen=True)
class CandidateRow:
    name: str
    party: str
    monitored: bool
    documents: int
    characters: str
    own_words: int
    period: str
    sources: tuple[SourceRow, ...]
    failed: int


@dataclass(frozen=True)
class BarPart:
    path: str
    level_class: str


@dataclass(frozen=True)
class Bar:
    hit_x: int
    hit_y: int
    parts: tuple[BarPart, ...]
    tip: str


@dataclass(frozen=True)
class ChartRow:
    name: str
    monitored: bool
    label_y: int
    baseline: int
    bars: tuple[Bar, ...]


@dataclass(frozen=True)
class Tick:
    x: int
    label: str


@dataclass(frozen=True)
class Chart:
    width: int
    plot_right: int
    height: int
    label_width: int
    slot: int
    row: int
    axis_y: int
    y_max: int
    rows: tuple[ChartRow, ...]
    ticks: tuple[Tick, ...]
    table_header: tuple[str, ...]
    table_rows: tuple[tuple[str, ...], ...]
    first_month: str
    last_month: str
    before_window: int
    undated: int
    other_levels_label: str


@dataclass(frozen=True)
class DocumentItem:
    candidate_id: str
    candidate_name: str
    source_label: str
    kind: str
    kind_label: str
    level: int
    level_label: str
    title: str
    url: str | None
    published: str
    fetched: str
    characters: str
    mentions: str  # "yes", "no", or "na" for level-1 sources, where it is not informative
    mentions_label: str
    excerpt: str
    paragraphs: tuple[str, ...]
    segmentation: DocumentSegments


@dataclass(frozen=True)
class CorpusPage:
    generated: str
    documents_total: str
    characters_total: str
    monitored: int
    candidates_total: int
    sources_total: int
    sources_failed: int
    sources_never: int
    unconfigured_documents: int
    candidates: tuple[CandidateRow, ...]
    chart: Chart
    documents: tuple[DocumentItem, ...]
    candidate_options: tuple[tuple[str, str], ...]
    kind_options: tuple[tuple[str, str], ...]
    segmentation: SegmentationSummary


def build_page(overview: CorpusOverview, chart_months: int) -> CorpusPage:
    rows = tuple(_candidate_row(corpus) for corpus in overview.candidates)
    sources = [s for row in rows for s in row.sources]
    documents = _documents(overview)
    return CorpusPage(
        generated=format_datetime(overview.generated_at),
        documents_total=format_count(len(documents)),
        characters_total=format_count(sum(len(d.text) for d in _all_documents(overview))),
        monitored=sum(1 for row in rows if row.monitored),
        candidates_total=len(rows),
        sources_total=len(sources),
        sources_failed=sum(1 for s in sources if s.status == "failed"),
        sources_never=sum(1 for s in sources if s.status == "never"),
        unconfigured_documents=overview.unconfigured_documents,
        candidates=rows,
        chart=build_chart(overview, chart_months),
        documents=documents,
        candidate_options=tuple((c.candidate.id, c.candidate.name) for c in overview.candidates),
        kind_options=tuple(sorted({(d.kind, d.kind_label) for d in documents})),
        segmentation=summarize(overview),
    )


# --- formatting -------------------------------------------------------------------------


def format_count(value: int) -> str:
    """French grouping with a narrow no-break space: 710 513."""
    return f"{value:,}".replace(",", "\u202f")


def format_day(day: date | None) -> str:
    return "date non précisée" if day is None else f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def format_month(year: int, month: int) -> str:
    return f"{_MONTHS[month - 1]} {year}"


def format_datetime(moment: datetime) -> str:
    return f"{format_day(moment.date())}, {moment:%H:%M} UTC"


def safe_href(url: str) -> str | None:
    """Only http(s) links reach an href; anything else is shown as text."""
    return url if urlsplit(url).scheme in {"http", "https"} else None


# --- candidates and sources -------------------------------------------------------------


def _candidate_row(corpus: CandidateCorpus) -> CandidateRow:
    views = [v for s in corpus.sources for v in s.documents]
    dates = sorted(d for v in views if (d := v.document.published_on) is not None)
    sources = tuple(_source_row(s) for s in corpus.sources)
    return CandidateRow(
        name=corpus.candidate.name,
        party=corpus.candidate.party,
        monitored=corpus.monitored,
        documents=len(views),
        characters=format_count(sum(len(v.document.text) for v in views)),
        own_words=sum(1 for v in views if v.document.trust_level == TrustLevel.OWN_WORDS),
        period=f"{format_day(dates[0])} \u2013 {format_day(dates[-1])}" if dates else "\u2014",
        sources=sources,
        failed=sum(1 for s in sources if s.status == "failed"),
    )


def _source_row(corpus: SourceCorpus) -> SourceRow:
    source, outcome = corpus.source, corpus.last_outcome
    status = "disabled" if not source.enabled and outcome is None else _status(corpus)
    return SourceRow(
        label=source.label,
        kind_label=_KIND_LABELS.get(source.kind, source.kind),
        level=int(source.trust_level),
        level_label=_LEVEL_LABELS[int(source.trust_level)],
        url=safe_href(source.url),
        status=status,
        status_label=_STATUS_LABELS[status],
        run_label=_run_label(corpus),
        fetched=outcome.fetched if outcome else 0,
        new=outcome.new if outcome else 0,
        duplicates=outcome.duplicates if outcome else 0,
        error=outcome.error if outcome else None,
        documents=len(corpus.documents),
        characters=format_count(sum(len(v.document.text) for v in corpus.documents)),
    )


def _status(corpus: SourceCorpus) -> str:
    return "never" if corpus.last_outcome is None else corpus.last_outcome.status


def _run_label(corpus: SourceCorpus) -> str:
    outcome = corpus.last_outcome
    if outcome is None:
        return "aucun passage enregistré"
    origin = (
        "import de la version précédente" if outcome.run_id.startswith("import") else "collecte"
    )
    return f"{origin}, {format_datetime(outcome.started_at)}"


# --- documents --------------------------------------------------------------------------


def _all_documents(overview: CorpusOverview) -> list[RawDocument]:
    return [v.document for c in overview.candidates for s in c.sources for v in s.documents]


def _documents(overview: CorpusOverview) -> tuple[DocumentItem, ...]:
    items = [
        (view, corpus, source)
        for corpus in overview.candidates
        for source in corpus.sources
        for view in source.documents
    ]
    items.sort(key=lambda item: item[0].document.fetched_at, reverse=True)
    items.sort(key=lambda item: item[0].document.published_on or date.min, reverse=True)
    items.sort(key=lambda item: item[0].document.published_on is None)
    names = {c.candidate.id: c.candidate.name for c in overview.candidates}
    return tuple(_document_item(view, corpus, source, names) for view, corpus, source in items)


def _document_item(
    view: DocumentView, corpus: CandidateCorpus, source: SourceCorpus, names: dict[str, str]
) -> DocumentItem:
    document = view.document
    level = int(document.trust_level)
    mentions, mentions_label = _mentions(view, corpus.candidate.name, level)
    return DocumentItem(
        candidate_id=corpus.candidate.id,
        candidate_name=corpus.candidate.name,
        source_label=source.source.label,
        kind=source.source.kind,
        kind_label=_KIND_LABELS.get(source.source.kind, source.source.kind),
        level=level,
        level_label=_LEVEL_LABELS[level],
        title=document.title or "Sans titre",
        url=safe_href(document.url),
        published=format_day(document.published_on),
        fetched=format_datetime(document.fetched_at),
        characters=format_count(len(document.text)),
        mentions=mentions,
        mentions_label=mentions_label,
        excerpt=_excerpt(document.text),
        paragraphs=tuple(line.strip() for line in document.text.splitlines() if line.strip()),
        segmentation=document_segments(view, names),
    )


def _mentions(view: DocumentView, name: str, level: int) -> tuple[str, str]:
    """Only informative where attribution is a default: a party feed carries the whole party."""
    if level == int(TrustLevel.OWN_WORDS):
        return "na", ""
    count = view.mentions_of_candidate
    if count == 0:
        return "no", f"ne cite pas {name}"
    return "yes", f"cite {name} {count} fois"


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= _EXCERPT_CHARS:
        return flat
    return flat[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"


# --- chart ------------------------------------------------------------------------------


def _month_window(end: date, months: int) -> list[tuple[int, int]]:
    index = end.year * 12 + end.month - 1
    return [divmod(i, 12) for i in range(index - months + 1, index + 1)]


def build_chart(overview: CorpusOverview, months: int) -> Chart:
    window = [
        (year, month + 1) for year, month in _month_window(overview.generated_at.date(), months)
    ]
    counts = _monthly_counts(overview, set(window))
    y_max = max((own + other for c in counts.values() for own, other in c.values()), default=0)
    rows = tuple(
        _chart_row(
            corpus, index, window, counts=counts.get(corpus.candidate.id, {}), y_max=max(y_max, 1)
        )
        for index, corpus in enumerate(overview.candidates)
    )
    monitored = [c for c in overview.candidates if c.monitored]
    every = _all_documents(overview)
    levels = {int(d.trust_level) for d in every if d.trust_level != TrustLevel.OWN_WORDS}
    return Chart(
        width=_LABEL_WIDTH + len(window) * _SLOT + _RIGHT_MARGIN,
        plot_right=_LABEL_WIDTH + len(window) * _SLOT,
        height=len(rows) * _ROW + _AXIS,
        label_width=_LABEL_WIDTH,
        slot=_SLOT,
        row=_ROW,
        axis_y=len(rows) * _ROW + 16,
        y_max=y_max,
        rows=rows,
        ticks=_ticks(window),
        table_header=("Mois", *(c.candidate.name for c in monitored)),
        table_rows=_table_rows(window, monitored, counts),
        first_month=format_month(*window[0]),
        last_month=format_month(*window[-1]),
        before_window=sum(
            1 for d in every if d.published_on and d.published_on < date(*window[0], 1)
        ),
        undated=sum(1 for d in every if d.published_on is None),
        other_levels_label=_other_levels_label(levels),
    )


def _monthly_counts(
    overview: CorpusOverview, window: set[tuple[int, int]]
) -> dict[str, dict[tuple[int, int], tuple[int, int]]]:
    """candidate id -> (year, month) -> (level-1 documents, other documents)."""
    own: Counter[tuple[str, int, int]] = Counter()
    other: Counter[tuple[str, int, int]] = Counter()
    for corpus in overview.candidates:
        for view in (v for s in corpus.sources for v in s.documents):
            day = view.document.published_on
            if day is None or (day.year, day.month) not in window:
                continue
            is_own = view.document.trust_level == TrustLevel.OWN_WORDS
            (own if is_own else other)[(corpus.candidate.id, day.year, day.month)] += 1
    result: dict[str, dict[tuple[int, int], tuple[int, int]]] = {}
    for cid, year, month in own.keys() | other.keys():
        result.setdefault(cid, {})[(year, month)] = (
            own[(cid, year, month)],
            other[(cid, year, month)],
        )
    return result


def _chart_row(
    corpus: CandidateCorpus,
    index: int,
    window: list[tuple[int, int]],
    *,
    counts: dict[tuple[int, int], tuple[int, int]],
    y_max: int,
) -> ChartRow:
    baseline = index * _ROW + _ROW - 6
    bars = tuple(
        _bar(
            (i, index),
            baseline,
            counts[month],
            y_max=y_max,
            label=f"{corpus.candidate.name} · {format_month(*month)}",
        )
        for i, month in enumerate(window)
        if month in counts
    )
    return ChartRow(
        name=corpus.candidate.name,
        monitored=corpus.monitored,
        label_y=baseline - 8,
        baseline=baseline,
        bars=bars,
    )


def _bar(
    position: tuple[int, int], baseline: int, counts: tuple[int, int], *, y_max: int, label: str
) -> Bar:
    slot, row = position
    own, other = counts
    x = _LABEL_WIDTH + slot * _SLOT + (_SLOT - _BAR) // 2
    own_h = _height(own, y_max)
    other_h = _height(other, y_max)
    parts: list[BarPart] = []
    if own_h:
        parts.append(BarPart(_rect_path(x, baseline - own_h, own_h, rounded=not other_h), "lvl-1"))
    if other_h:
        top = baseline - own_h - (_GAP if own_h else 0) - other_h
        parts.append(BarPart(_rect_path(x, top, other_h, rounded=True), "lvl-2"))
    total = own + other
    tip = (
        f"{label} : {total} document{'s' if total > 1 else ''} ({own} de niveau 1, {other} autres)"
    )
    return Bar(hit_x=_LABEL_WIDTH + slot * _SLOT, hit_y=row * _ROW, parts=tuple(parts), tip=tip)


def _height(count: int, y_max: int) -> int:
    return 0 if count == 0 else max(_MIN_SEGMENT, round(count * _BAR_MAX / y_max))


def _rect_path(x: int, y: int, height: int, *, rounded: bool) -> str:
    """A bar segment; the data end (top) is rounded, the baseline end square."""
    right, bottom = x + _BAR, y + height
    if not rounded:
        return f"M{x},{y}H{right}V{bottom}H{x}Z"
    r = min(_RADIUS, height, _BAR // 2)
    return (
        f"M{x},{bottom}V{y + r}Q{x},{y} {x + r},{y}H{right - r}"
        f"Q{right},{y} {right},{y + r}V{bottom}Z"
    )


def _ticks(window: list[tuple[int, int]]) -> tuple[Tick, ...]:
    last = len(window) - 1
    return tuple(
        Tick(x=_LABEL_WIDTH + i * _SLOT + _SLOT // 2, label=format_month(*month))
        for i, month in enumerate(window)
        if (last - i) % _TICK_EVERY == 0
    )


def _table_rows(
    window: list[tuple[int, int]],
    monitored: list[CandidateCorpus],
    counts: dict[str, dict[tuple[int, int], tuple[int, int]]],
) -> tuple[tuple[str, ...], ...]:
    rows = []
    for month in reversed(window):
        cells = (sum(counts.get(c.candidate.id, {}).get(month, (0, 0))) for c in monitored)
        rows.append((format_month(*month), *(str(n) for n in cells)))
    return tuple(rows)


def _other_levels_label(levels: set[int]) -> str:
    if not levels or levels == {2}:
        return "Niveau 2 · parti"
    names = ", ".join(_LEVEL_LABELS[level] for level in sorted(levels))
    return f"Niveaux {min(levels)} à {max(levels)} · {names}"
