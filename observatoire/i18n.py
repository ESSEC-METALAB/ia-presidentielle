"""Chrome strings and URL shapes for the two locales.

Roughly forty strings. A dictionary is the right size of tool for that; an
i18n library would be more configuration than content. The *claims* are
already bilingual fields on each record — only the furniture is translated
here.
"""

from __future__ import annotations

LOCALES = ("fr", "en")
DEFAULT = "fr"

# Logical page → path per locale. One place, so hreflang alternates and the
# sitemap are generated from the same source and cannot drift apart.
PATHS = {
    "fil":         {"fr": "/fr/",                  "en": "/en/"},
    "grille":      {"fr": "/fr/grille/",           "en": "/en/grid/"},
    "methodo":     {"fr": "/fr/methodologie/",     "en": "/en/methodology/"},
    "corrections": {"fr": "/fr/corrections/",      "en": "/en/corrections/"},
    "legal":       {"fr": "/fr/mentions-legales/", "en": "/en/legal/"},
}
PERSON_SEGMENT = {"fr": "personne", "en": "person"}


def person_path(locale: str, slug: str) -> str:
    return f"/{locale}/{PERSON_SEGMENT[locale]}/{slug}/"


AXIS_LABELS = {
    "regulation":            {"fr": "Régulation",                "en": "Regulation"},
    "souverainete":          {"fr": "Souveraineté & infra",      "en": "Sovereignty & infra"},
    "emploi-formation":      {"fr": "Emploi & formation",        "en": "Work & training"},
    "services-publics":      {"fr": "Services publics",          "en": "Public services"},
    "surveillance-libertes": {"fr": "Surveillance & libertés",   "en": "Surveillance & liberties"},
    "financement":           {"fr": "Financement",               "en": "Funding"},
}

TIER_LABELS = {
    "1": {"fr": "ses propres mots",   "en": "their own words"},
    "2": {"fr": "parti ou entourage", "en": "party or staff"},
    "3": {"fr": "presse",             "en": "press"},
}

UI = {
    "skip_content": {"fr": "Aller au contenu", "en": "Skip to content"},
    "home_label": {"fr": "Accueil", "en": "Home"},
    "hero_edition": {"fr": "France · Présidentielle 2027", "en": "France · Presidential election 2027"},
    "hero_line_one": {"fr": "L’IA avance.", "en": "AI is moving."},
    "hero_line_two": {"fr": "À nous de", "en": "The choice"},
    "hero_line_three": {"fr": "choisir.", "en": "is ours."},
    "hero_intro": {
        "fr": "Quelle place pour l’intelligence artificielle dans notre société ? Explorez les positions politiques pour éclairer votre choix en 2027.",
        "en": "What place should artificial intelligence have in our society? Explore political positions to inform your choice in 2027."},
    "hero_compare": {"fr": "Comparer les positions", "en": "Compare positions"},
    "hero_latest": {"fr": "Suivre le débat", "en": "Follow the debate"},
    "hero_principle": {"fr": "Des sources. Du contexte. À vous de juger.",
                       "en": "The sources. The context. Your judgement."},
    "hero_art_alt": {
        "fr": "Une main humaine en marbre et une main robotique se rejoignent presque, entre drapés bleu et rouge, en écho à La Création d’Adam.",
        "en": "A marble human hand and a robotic hand almost meet between blue and red drapery, echoing The Creation of Adam."},
    "hero_art_title": {"fr": "Le futur est entre nos mains.", "en": "The future is in our hands."},
    "hero_art_credit": {"fr": "Allégorie générée par IA · d’après Michel-Ange",
                        "en": "AI-generated allegory · after Michelangelo"},
    "hero_seal_top": {"fr": "Notre avenir", "en": "Our future"},
    "hero_seal_bottom": {"fr": "Un choix collectif", "en": "A collective choice"},
    "nav_positions": {"fr": "Les positions", "en": "The positions"},
    "nav_debate": {"fr": "Le débat", "en": "The debate"},
    "explore_label": {"fr": "Pour vous faire une idée", "en": "Make up your own mind"},
    "explore_compare": {"fr": "Qui propose quoi ?", "en": "Who proposes what?"},
    "explore_compare_text": {"fr": "Les positions, côte à côte, sur six enjeux de l’IA.",
                             "en": "Positions, side by side, on six AI policy issues."},
    "explore_feed": {"fr": "Que disent-ils ?", "en": "What are they saying?"},
    "explore_feed_text": {"fr": "Les déclarations, leurs sources et leur contexte.",
                          "en": "Statements, their sources and their context."},
    "explore_method": {"fr": "Comment observer ?", "en": "How do we observe?"},
    "explore_method_text": {"fr": "La méthode et les principes de l’observatoire.",
                            "en": "The observatory’s methodology and principles."},
    "latest_title": {"fr": "Les mots du débat.", "en": "In their own words."},
    "view_grid": {"fr": "Voir la grille", "en": "View the grid"},
    "site":         {"fr": "Observatoire IA 2027",   "en": "AI Observatory 2027"},
    "publisher":    {"fr": "Institut ESSEC Metalab", "en": "ESSEC Metalab Institute"},
    "tagline":      {"fr": "Ce que les candidats à l’élection présidentielle de 2027 disent de l’intelligence artificielle.",
                     "en": "What candidates in the 2027 French presidential election say about artificial intelligence."},
    "nav_fil":      {"fr": "Le fil",         "en": "The feed"},
    "nav_grille":   {"fr": "La grille",      "en": "The grid"},
    "nav_methodo":  {"fr": "Méthodologie",   "en": "Methodology"},
    "nav_corr":     {"fr": "Corrections",    "en": "Corrections"},
    "nav_legal":    {"fr": "Mentions légales", "en": "Legal notice"},
    "fil_title":    {"fr": "Le fil",         "en": "The feed"},
    "fil_intro":    {"fr": "Chaque position relevée, la plus récente d’abord.",
                     "en": "Every position recorded, most recent first."},
    "grid_title":   {"fr": "La grille",      "en": "The grid"},
    "grid_intro":   {"fr": "Chaque candidat sur chacun des six axes. Une case vide est une information : elle signifie qu’aucune position n’a été relevée.",
                     "en": "Every candidate on each of six axes. An empty cell is information: it means no position has been recorded."},
    "grid_caption": {"fr": "Positions relevées par candidat et par axe",
                     "en": "Recorded positions by candidate and axis"},
    "none_found":   {"fr": "Aucune position identifiée",
                     "en": "No position identified"},
    "source":       {"fr": "Source",         "en": "Source"},
    "archived":     {"fr": "archive",        "en": "archived"},
    "verified":     {"fr": "Vérifié le",     "en": "Verified"},
    "context":      {"fr": "Contexte — Metalab", "en": "Context — Metalab"},
    "translation":  {"fr": "traduction",     "en": "translation"},
    "quote_note":   {"fr": "Citation d’origine, non traduite.",
                     "en": "Original quote, untranslated."},
    "candidate":    {"fr": "Candidat",       "en": "Candidate"},
    "positions":    {"fr": "positions",      "en": "positions"},
    "other_lang":   {"fr": "English",        "en": "Français"},
    "scroll_grid":  {"fr": "Tableau défilant horizontalement",
                     "en": "Horizontally scrollable table"},
    "no_corrections": {"fr": "Aucune correction à ce jour.",
                       "en": "No corrections to date."},
    "updated":      {"fr": "Mis à jour le",  "en": "Updated"},
    "not_monitored":{"fr": "Non suivi",
                     "en": "Not monitored"},
    "not_monitored_help": {
        "fr": "Aucune source n’est encore suivie pour ce candidat. Une case vide ici ne dit rien de ses positions, seulement de notre couverture.",
        "en": "No source is monitored for this candidate yet. An empty cell here says nothing about their positions, only about our coverage."},
    "coverage":     {"fr": "Couverture",     "en": "Coverage"},
    "date_unknown": {"fr": "date non précisée", "en": "date not stated"},
    "tier_default": {"fr": "niveau par défaut, non confirmé",
                     "en": "default level, unconfirmed"},
}


def t(key: str, locale: str) -> str:
    return UI[key][locale]


def axis_label(axis: str, locale: str) -> str:
    return AXIS_LABELS[axis][locale]
