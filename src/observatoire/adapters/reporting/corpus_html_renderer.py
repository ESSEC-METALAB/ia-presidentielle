"""CorpusRenderer producing one self-contained static HTML page (Jinja2, autoescaped)."""

from jinja2 import Environment, PackageLoader

from observatoire.adapters.reporting.corpus_page import build_page
from observatoire.domain.models import CorpusOverview


class CorpusHtmlRenderer:
    """`standalone=False` drops the <html>/<head>/<body> wrapper, for hosts that add their own."""

    def __init__(self, *, chart_months: int = 24, standalone: bool = True) -> None:
        environment = Environment(
            loader=PackageLoader("observatoire.adapters.reporting", "templates"),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._template = environment.get_template("corpus.html.j2")
        self._chart_months = chart_months
        self._standalone = standalone

    def render(self, overview: CorpusOverview) -> str:
        page = build_page(overview, self._chart_months)
        return self._template.render(page=page, standalone=self._standalone)
