"""The site is hand-rolled, so the guarantees a framework would provide have
to be asserted here — above all hreflang, which a Search Engine Land study
found 31% of international sites get wrong."""
import re
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest

from observatoire.i18n import LOCALES, PATHS, person_path
from observatoire.render import AXES, BASE_URL, Person, build_grid, render
from observatoire.schema import Claim, Tier

PEOPLE = [Person("bruno-retailleau", "Bruno Retailleau", "LR"),
          Person("jean-luc-melenchon", "Jean-Luc Mélenchon", "LFI"),
          Person("marine-le-pen", "Marine Le Pen", "RN")]


def claim(person="bruno-retailleau", axis="souverainete", **over):
    base = dict(
        axis=axis, claim_type="discours", date=date(2026, 7, 7),
        quote_fr="l’IA sera la souveraineté même",
        quote_gloss_en="AI will be sovereignty itself",
        position_fr="Place l'IA au rang d'enjeu de souveraineté.",
        position_en="Frames AI as a sovereignty question.",
        contexte_fr="Analogie avec le nucléaire.", contexte_en="A nuclear analogy.",
        person=person, party="LR", tier=Tier.OWN_WORDS,
        source_url="https://republicains.fr/a", archive_url="https://web.archive.org/web/20260918144520/https://a.test/1",
        last_verified=date(2026, 9, 18))
    return Claim(**{**base, **over})


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    render([claim(), claim(person="jean-luc-melenchon", axis="regulation",
                           source_url="https://lafranceinsoumise.fr/b")],
           PEOPLE, out, built_on=date(2026, 9, 18))
    return out


def html(site, path):
    return (site / path.strip("/") / "index.html").read_text(encoding="utf-8")


# --- hreflang: the rule most sites break ----------------------------------

@pytest.mark.parametrize("page", list(PATHS))
def test_every_page_declares_a_self_referencing_hreflang(site, page):
    for locale in LOCALES:
        doc = html(site, PATHS[page][locale])
        expected = f'hreflang="{locale}" href="{BASE_URL}{PATHS[page][locale]}"'
        assert expected in doc


@pytest.mark.parametrize("page", list(PATHS))
def test_hreflang_is_bidirectional(site, page):
    """fr must point at en and en back at fr, or the whole set is ignored."""
    for locale in LOCALES:
        doc = html(site, PATHS[page][locale])
        for other in LOCALES:
            assert f'hreflang="{other}" href="{BASE_URL}{PATHS[page][other]}"' in doc


@pytest.mark.parametrize("page", list(PATHS))
def test_x_default_is_present_and_points_at_french(site, page):
    doc = html(site, PATHS[page]["en"])
    assert f'hreflang="x-default" href="{BASE_URL}{PATHS[page]["fr"]}"' in doc


def test_canonical_points_at_the_page_itself(site):
    """An hreflang set is ignored if it points at non-canonical URLs."""
    for page, paths in PATHS.items():
        for locale in LOCALES:
            doc = html(site, paths[locale])
            assert f'<link rel="canonical" href="{BASE_URL}{paths[locale]}">' in doc


def test_every_advertised_alternate_actually_exists(site):
    doc = html(site, PATHS["fil"]["en"])
    for href in re.findall(r'hreflang="[a-z-]+" href="([^"]+)"', doc):
        local = href.replace(BASE_URL, "")
        assert (site / local.strip("/") / "index.html").exists(), local


def test_person_pages_are_linked_across_locales(site):
    doc = html(site, person_path("en", "bruno-retailleau"))
    assert f'hreflang="fr" href="{BASE_URL}{person_path("fr", "bruno-retailleau")}"' in doc


# --- structural pluralism -------------------------------------------------

def test_grid_has_a_cell_for_every_person_on_every_axis():
    grid = build_grid([claim()], PEOPLE)
    assert set(grid) == {p.slug for p in PEOPLE}
    for slug in grid:
        assert set(grid[slug]) == set(AXES)


def test_absence_is_rendered_not_hidden(site):
    doc = html(site, PATHS["grille"]["en"])
    # 3 people x 6 axes = 18 cells, 2 filled
    assert doc.count("No position identified") == 16


def test_a_person_with_no_claims_still_appears(site):
    assert "Marine Le Pen" in html(site, PATHS["grille"]["fr"])


# --- accessibility --------------------------------------------------------

def test_grid_is_a_real_table_not_css_divs(site):
    doc = html(site, PATHS["grille"]["fr"])
    assert "<caption>" in doc
    assert doc.count('<th scope="col">') == len(AXES) + 1
    assert doc.count('<th scope="row">') == len(PEOPLE)


def test_scrollable_region_is_reachable_by_keyboard(site):
    doc = html(site, PATHS["grille"]["fr"])
    region = re.search(r'<div class="scroller"[^>]*>', doc).group(0)
    assert 'tabindex="0"' in region and 'role="region"' in region and "aria-label=" in region


def test_french_quotes_are_marked_as_french_on_english_pages(site):
    doc = html(site, PATHS["fil"]["en"])
    assert doc.count("<blockquote") == doc.count('<blockquote lang="fr"')


def test_page_language_is_declared(site):
    assert '<html lang="en">' in html(site, PATHS["fil"]["en"])
    assert '<html lang="fr">' in html(site, PATHS["fil"]["fr"])


def test_translation_gloss_shows_only_where_it_helps(site):
    assert 'class="gloss"' in html(site, PATHS["fil"]["en"])
    assert 'class="gloss"' not in html(site, PATHS["fil"]["fr"])


def test_home_hero_links_to_the_grid_and_feed_with_local_artwork(site):
    for locale in LOCALES:
        doc = html(site, PATHS["fil"][locale])
        assert '<body class="home">' in doc
        assert len(re.findall(r"<h1\b", doc)) == 1
        assert re.search(r'<h1\b[^>]*\bid="hero-title"', doc)
        cta = re.search(r'<a\b[^>]*class="hero-cta"[^>]*>', doc).group(0)
        assert f'href="{PATHS["grille"][locale]}"' in cta
        assert 'href="#positions"' in doc and 'id="positions"' in doc
        art = re.search(r'<img\b[^>]*class="hero-art"[^>]*>', doc).group(0)
        src = re.search(r'src="([^"]+)"', art).group(1)
        assert re.fullmatch(r"/assets/hero-creation\.[0-9a-f]{10}\.webp", src)
        assert (site / src.lstrip("/")).read_bytes() == Path("assets/hero-creation.webp").read_bytes()
        person = html(site, person_path(locale, PEOPLE[0].slug))
        assert '<body class="home">' not in person and 'class="hero-art"' not in person


# --- feeds, sitemap, assets -----------------------------------------------

def test_sitemap_lists_every_page_with_alternates(site):
    root = ET.fromstring((site / "sitemap.xml").read_text(encoding="utf-8"))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9",
          "x": "http://www.w3.org/1999/xhtml"}
    urls = root.findall("s:url", ns)
    assert len(urls) == (len(PATHS) + len(PEOPLE)) * len(LOCALES)
    for u in urls:
        langs = {l.get("hreflang") for l in u.findall("x:link", ns)}
        assert langs == {"fr", "en", "x-default"}


def test_each_locale_has_a_valid_rss_feed(site):
    for locale in LOCALES:
        root = ET.fromstring((site / locale / "rss.xml").read_bytes())
        items = root.findall(".//item")
        assert len(items) == 2
        assert root.find(".//language").text == locale


def test_stylesheet_is_content_hashed_and_referenced(site):
    css = list((site / "assets").glob("style.*.css"))
    assert len(css) == 1
    assert re.fullmatch(r"style\.[0-9a-f]{10}\.css", css[0].name)
    assert f'/assets/{css[0].name}' in html(site, PATHS["fil"]["fr"])


def test_root_redirects_to_the_default_locale(site):
    doc = (site / "index.html").read_text(encoding="utf-8")
    assert 'url=/fr/' in doc and 'rel="canonical"' in doc


def test_robots_points_at_the_sitemap(site):
    assert f"Sitemap: {BASE_URL}/sitemap.xml" in (site / "robots.txt").read_text()


# --- review findings: three things the earlier suite did not catch ---------

UNWATCHED = PEOPLE + [Person("marine-le-pen", "Marine Le Pen", "RN", monitored=False)]


@pytest.fixture(scope="module")
def site2(tmp_path_factory):
    out = tmp_path_factory.mktemp("site2")
    render([claim(), claim(person="jean-luc-melenchon", axis="regulation",
                           source_url="https://lafranceinsoumise.fr/b"),
            claim(person="bruno-retailleau", axis="financement", date=None,
                  source_url="https://republicains.fr/undated")],
           UNWATCHED, out, built_on=date(2026, 9, 18))
    return out


def test_an_unmonitored_candidate_is_not_shown_as_having_no_policy(site2):
    """The most serious review finding. A candidate we never looked at must not
    render identically to one we looked at and found nothing for."""
    doc = html(site2, PATHS["grille"]["fr"])
    assert doc.count("Non suivi") == len(AXES)          # all six of her cells
    assert "Marine Le Pen" in doc


def test_the_two_empty_states_are_visually_distinct(site2):
    doc = html(site2, PATHS["grille"]["en"])
    assert "Not monitored" in doc and "No position identified" in doc
    assert 'class="unmonitored"' in doc and 'class="empty"' in doc


def test_the_grid_states_its_own_coverage(site2):
    doc = html(site2, PATHS["grille"]["fr"])
    assert "Couverture" in doc and "3/4" in doc
    assert "seulement de notre couverture" in doc


def test_a_claim_with_no_date_says_so_rather_than_inventing_one(site2):
    doc = html(site2, PATHS["fil"]["fr"])
    assert "date non précisée" in doc
    assert "1970-01-01" not in doc and "2026-01-01" not in doc


def test_an_unconfirmed_tier_is_marked_as_a_default(site2):
    doc = html(site2, PATHS["fil"]["fr"])
    assert "niveau par défaut, non confirmé" in doc
