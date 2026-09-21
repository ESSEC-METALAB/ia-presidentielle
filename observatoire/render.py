"""Build the static site.

Hand-rolled rather than framework-driven, which means four things a framework
would give free have to be got right here: locale routing, hreflang, the
sitemap, and the feeds. Each is generated from the single ``PATHS`` table in
``i18n.py`` so they cannot drift apart — and ``tests/test_render.py`` asserts
the hreflang set is self-referencing, bidirectional and carries ``x-default``,
which is the rule most international sites get wrong.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from feedgen.feed import FeedGenerator
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .i18n import (
    AXIS_LABELS, DEFAULT, LOCALES, PATHS, TIER_LABELS, axis_label, person_path, t,
)
from .schema import Axis, Claim

AXES = [a.value for a in Axis]
BASE_URL = "https://ia2027.metalab.essec.edu"


@dataclass(frozen=True)
class Person:
    slug: str
    name: str
    party: str
    monitored: bool = True
    """False when no source is configured. A candidate we have never looked at
    must not render identically to one we have looked at and found nothing for.
    The first is a fact about our coverage, the second about them."""


def _env(templates: Path) -> Environment:
    env = Environment(loader=FileSystemLoader(templates),
                      autoescape=select_autoescape(["html", "xml", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["hostname"] = lambda u: urlparse(u).netloc or u
    return env


def alternates_for(page_key: str, slug: str | None = None) -> dict[str, str]:
    """Every locale's URL for one logical page. hreflang is generated from this,
    so a page can never advertise an alternate that does not exist."""
    if slug is not None:
        return {loc: person_path(loc, slug) for loc in LOCALES}
    return {loc: PATHS[page_key][loc] for loc in LOCALES}


def build_grid(claims: list[Claim], people: list[Person]) -> dict[str, dict[str, Claim | None]]:
    """person × axis, **fully populated**.

    Every cell exists for every person on every axis. An empty cell renders as
    *aucune position identifiée* — absence is data and must be shown. A missing
    cell would be a rendering bug, and asymmetric coverage by an institution
    could be read as an in-kind campaign benefit under art. L. 52-8.
    """
    grid: dict[str, dict[str, Claim | None]] = {
        p.slug: {axis: None for axis in AXES} for p in people
    }
    for c in sorted(claims, key=lambda c: str(c.date)):
        if c.person in grid:
            grid[c.person][str(c.axis)] = c  # most recent wins
    return grid


def _feed(locale: str, claims: list[Claim], people: dict[str, Person]) -> bytes:
    fg = FeedGenerator()
    fg.id(f"{BASE_URL}/{locale}/")
    fg.title(t("site", locale))
    fg.link(href=f"{BASE_URL}{PATHS['fil'][locale]}", rel="alternate")
    fg.description(t("tagline", locale))
    fg.language(locale)
    for c in claims[:50]:
        fe = fg.add_entry()
        fe.id(f"{BASE_URL}{PATHS['fil'][locale]}#{c.id}")
        who = people[c.person].name if c.person in people else c.person
        fe.title(f"{who} — {axis_label(str(c.axis), locale)}")
        fe.link(href=c.citation_url())
        body = c.position_fr if locale == "fr" else c.position_en
        fe.description(f"« {c.quote_fr} » — {body}")
    return fg.rss_str(pretty=True)


def _sitemap(pages: list[tuple[str, dict[str, str]]]) -> str:
    """Sitemap carrying xhtml:link alternates — the same data as hreflang."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
           '        xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for path, alts in pages:
        out.append("  <url>")
        out.append(f"    <loc>{escape(BASE_URL + path)}</loc>")
        for loc, href in alts.items():
            out.append(f'    <xhtml:link rel="alternate" hreflang="{loc}" '
                       f'href="{escape(BASE_URL + href)}"/>')
        out.append(f'    <xhtml:link rel="alternate" hreflang="x-default" '
                   f'href="{escape(BASE_URL + alts[DEFAULT])}"/>')
        out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out)


def render(claims: list[Claim], people: list[Person], out: Path,
           templates: Path = Path("templates"), assets: Path = Path("assets"),
           built_on: date | None = None) -> dict:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # Content-hashed stylesheet: the whole asset pipeline this site needs.
    css = (assets / "style.css").read_bytes()
    css_name = f"style.{hashlib.sha256(css).hexdigest()[:10]}.css"
    (out / "assets").mkdir()
    (out / "assets" / css_name).write_bytes(css)

    env = _env(templates)
    by_slug = {p.slug: p for p in people}
    ordered = sorted(claims, key=lambda c: (str(c.date), c.id), reverse=True)
    grid = build_grid(claims, people)
    built_on = built_on or date.today()
    written: list[tuple[str, dict[str, str]]] = []

    def write(path: str, html: str) -> None:
        target = out / path.strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")

    def ctx(locale: str, page_key: str, page_title: str, alts: dict[str, str], **extra) -> dict:
        other = "en" if locale == "fr" else "fr"
        return dict(
            locale=locale, other_locale=other, default_locale=DEFAULT,
            page_key=page_key, page_title=page_title,
            alternates=alts, self_path=alts[locale],
            base_url=BASE_URL, css_name=css_name, built_on=built_on.isoformat(),
            paths=PATHS, people=by_slug, axes=AXES,
            t=lambda k: t(k, locale),
            axis_label=axis_label, person_path=person_path,
            tier_label=lambda tier, loc: TIER_LABELS[tier][loc],
            navitems=[(k, t(f"nav_{n}", locale)) for k, n in
                      [("fil", "fil"), ("grille", "grille"), ("methodo", "methodo"),
                       ("corrections", "corr"), ("legal", "legal")]],
            **extra)

    static_bodies = _static_bodies()

    for locale in LOCALES:
        # le fil
        alts = alternates_for("fil")
        write(alts[locale], env.get_template("fil.html.j2").render(
            **ctx(locale, "fil", t("fil_title", locale), alts, claims=ordered)))
        written.append((alts[locale], alts))

        # la grille
        alts = alternates_for("grille")
        write(alts[locale], env.get_template("grille.html.j2").render(
            **ctx(locale, "grille", t("grid_title", locale), alts,
                  grid=grid, people_list=people, wide=True,
                  monitored_n=sum(1 for p in people if p.monitored))))
        written.append((alts[locale], alts))

        # static pages
        for key, title_key in [("methodo", "nav_methodo"), ("corrections", "nav_corr"),
                               ("legal", "nav_legal")]:
            alts = alternates_for(key)
            write(alts[locale], env.get_template("page.html.j2").render(
                **ctx(locale, key, t(title_key, locale), alts,
                      body=static_bodies[key][locale])))
            written.append((alts[locale], alts))

        # per person
        for person in people:
            alts = alternates_for("person", slug=person.slug)
            write(alts[locale], env.get_template("personne.html.j2").render(
                **ctx(locale, "fil", person.name, alts, person=person,
                      claims=[c for c in ordered if c.person == person.slug])))
            written.append((alts[locale], alts))

        (out / locale).mkdir(parents=True, exist_ok=True)
        (out / locale / "rss.xml").write_bytes(_feed(locale, ordered, by_slug))

    (out / "index.html").write_text(
        env.get_template("index_redirect.html.j2").render(
            default_locale=DEFAULT, base_url=BASE_URL, site=t("site", DEFAULT)),
        encoding="utf-8")
    (out / "sitemap.xml").write_text(_sitemap(written), encoding="utf-8")
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")

    return {"pages": len(written), "claims": len(claims), "people": len(people),
            "css": css_name, "locales": list(LOCALES)}


def _static_bodies() -> dict[str, dict[str, str]]:
    """Placeholder prose for the three standing pages. The real text is a
    pre-launch deliverable requiring legal review, not something to invent
    here — but the pages must exist so the routing, hreflang and sitemap are
    exercised and testable."""
    todo_fr = "<p><em>À rédiger avant publication — relecture juridique requise.</em></p>"
    todo_en = "<p><em>To be written before launch — pending legal review.</em></p>"
    return {
        "methodo": {"fr": todo_fr, "en": todo_en},
        "corrections": {
            "fr": f"<p>{t('no_corrections','fr')}</p>",
            "en": f"<p>{t('no_corrections','en')}</p>"},
        "legal": {"fr": todo_fr, "en": todo_en},
    }


if __name__ == "__main__":
    import argparse
    import yaml

    from .store import Store

    ap = argparse.ArgumentParser(description="Render the static site.")
    ap.add_argument("--db", default="data/observatoire.db")
    ap.add_argument("--sources", default="sources.yaml")
    ap.add_argument("--out", default="site")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.sources).read_text(encoding="utf-8"))
    people = [Person(p["slug"], p["name"], p.get("party", ""),
                     monitored=bool(p.get("sources")))
              for p in cfg["people"]]
    store = Store(args.db)
    stats = render(store.claims(), people, Path(args.out))
    store.close()
    print(" · ".join(f"{k} {v}" for k, v in stats.items()))
