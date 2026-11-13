"""A reviewer's PDF of what one extraction produced.

Not part of the publication chain. ``render.py`` builds the site; this builds a
single document an editor can read away from a screen, or attach to a review.
It shows, per claim, the evidence a reviewer has to check: the quote, whose
words it is held to be, and the two links that let them verify it themselves.

The header carries the model and the prompt hash, because a claim is explained
by the prompt that produced it as much as by the model — the same provenance
the batch artifacts record.

pymupdf is already a dependency; it reads the source PDFs in ``fetch``. Text is
laid out line by line rather than with ``insert_textbox`` so pagination stays
predictable: every line advances ``y`` by a known amount, and a block that
would cross the bottom margin starts a new page instead of being clipped.
"""

from __future__ import annotations

import textwrap
from datetime import date as Date
from pathlib import Path

import pymupdf

from .i18n import AXIS_LABELS
from .schema import Claim

# A4 in points, with margins wide enough that a quote does not run to the edge.
PAGE = pymupdf.paper_rect("a4")
MARGIN = 56.0
FONT = "helv"
FONT_BOLD = "hebo"
FONT_ITALIC = "heit"
BODY, LEAD = 9.5, 13.0


def _wrap(font: pymupdf.Font, text: str, size: float, width: float) -> list[str]:
    """Wrap to the column, measuring the face rather than guessing a width."""
    sample = "abcdefghijklmnopqrstuvwxyzáéèêç ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    per_char = font.text_length(sample, fontsize=size) / len(sample)
    return textwrap.wrap(text, width=max(20, int(width / per_char))) or [""]


class _Writer:
    """Cursor over a growing document. Knows only how to put a line down and
    when to start a new page.

    Text goes through ``TextWriter`` rather than ``insert_text``: the latter
    encodes Base14 fonts as Latin-1, which has no U+2019. The quotes in this
    corpus use the typographic apostrophe — ``l’IA`` — and it rendered as a
    stray dot. The quote is the evidence, so it has to come out of the PDF
    byte-for-byte as it went in. A ``TextWriter`` carries one colour, so there
    is one per colour in use on the page, all flushed when the page is done.
    """

    def __init__(self) -> None:
        self.doc = pymupdf.open()
        self.fonts = {FONT: pymupdf.Font("helv"), FONT_BOLD: pymupdf.Font("hebo"),
                      FONT_ITALIC: pymupdf.Font("heit")}
        self.page = None
        self.writers: dict[tuple, pymupdf.TextWriter] = {}
        self._new_page()

    def _flush(self) -> None:
        for colour, tw in self.writers.items():
            tw.write_text(self.page, color=colour)
        self.writers = {}

    def _new_page(self) -> None:
        if self.page is not None:
            self._flush()
        self.page = self.doc.new_page(width=PAGE.width, height=PAGE.height)
        self.y = MARGIN

    @property
    def width(self) -> float:
        return PAGE.width - 2 * MARGIN

    def space(self, needed: float) -> None:
        """Start a new page if ``needed`` points would cross the bottom margin."""
        if self.y + needed > PAGE.height - MARGIN:
            self._new_page()

    def line(self, text: str, *, size: float = BODY, font: str = FONT,
             indent: float = 0.0, colour=(0, 0, 0)) -> None:
        face = self.fonts[font]
        for part in _wrap(face, text, size, self.width - indent):
            self.space(LEAD)
            tw = self.writers.setdefault(tuple(colour), pymupdf.TextWriter(self.page.rect))
            tw.append((MARGIN + indent, self.y), part, font=face, fontsize=size)
            self.y += LEAD

    def gap(self, points: float = LEAD * 0.6) -> None:
        self.y += points

    def rule(self) -> None:
        self.space(LEAD)
        self.page.draw_line((MARGIN, self.y), (PAGE.width - MARGIN, self.y),
                            color=(0.8, 0.8, 0.78), width=0.6)
        self.y += LEAD * 0.7


GREY = (0.42, 0.42, 0.40)


def write_report(path: str | Path, claims: list[Claim], *, model: str,
                 prompt_hash: str, built_on: Date | None = None,
                 batch_id: str | None = None, locale: str = "fr") -> Path:
    """Write the review document. Returns the path it wrote."""
    built_on = built_on or Date.today()
    w = _Writer()

    w.line("Revue d'extraction", size=17, font=FONT_BOLD)
    w.line("Institut ESSEC Metalab · Observatoire IA 2027", size=9, colour=GREY)
    w.gap()
    w.line(f"Généré le {built_on} · modèle {model} · prompt {prompt_hash}",
           size=8.5, colour=GREY)
    if batch_id:
        w.line(f"Lot {batch_id}", size=8.5, colour=GREY)
    people = sorted({c.person for c in claims})
    w.line(f"{len(claims)} position(s) · {len(people)} personne(s) · "
           f"{len({c.axis for c in claims})} axe(s)", size=8.5, colour=GREY)
    w.gap()
    w.line("Document de relecture. Chaque position doit être vérifiée contre sa source "
           "avant publication : la citation est la preuve, le reste est du contexte.",
           size=8.5, font=FONT_ITALIC, colour=GREY)
    w.gap(LEAD)

    if not claims:
        w.rule()
        w.line("Aucune position extraite. C'est la réponse attendue pour la plupart "
               "des documents et ce n'est pas une erreur.", size=9.5, font=FONT_ITALIC)

    for claim in sorted(claims, key=lambda c: (c.person, c.axis.value, c.date or Date.min)):
        # Keep a claim's header with at least its quote, never orphaned.
        w.space(LEAD * 5)
        w.rule()
        axis = AXIS_LABELS[claim.axis.value][locale]
        w.line(f"{claim.person} · {axis}", size=11, font=FONT_BOLD)

        tier = {"1": "ses propres mots", "2": "parti ou entourage", "3": "presse"}[claim.tier.value]
        confirmed = "" if claim.tier_confirmed else " *"
        when = claim.date.isoformat() if claim.date else "date non précisée"
        w.line(f"{when} · {tier}{confirmed} · {claim.claim_type.value}", size=8.5, colour=GREY)
        w.gap(4)

        w.line(f"« {claim.quote_fr} »", size=BODY, font=FONT_ITALIC, indent=10)
        w.gap(4)
        w.line(claim.position_fr, size=BODY)
        w.line(claim.contexte_fr, size=8.8, colour=GREY)
        w.gap(4)

        w.line(f"Source : {claim.citation_url()}", size=7.8, colour=GREY, indent=10)
        if claim.archive_url:
            w.line(f"Archive : {claim.archive_url}", size=7.8, colour=GREY, indent=10)
        else:
            w.line("Archive : aucune — la citation ne survivrait pas à une suppression",
                   size=7.8, colour=(0.7, 0.1, 0.1), indent=10)
        w.line(f"id {claim.id}", size=7.5, colour=GREY, indent=10)
        w.gap()

    if any(not c.tier_confirmed for c in claims):
        w.gap()
        w.rule()
        w.line("* Niveau de source non confirmé : c'est la valeur par défaut de la source, "
               "pas un constat sur ce document. Un site de parti publie aussi bien ses "
               "communiqués que les discours du candidat.", size=8, font=FONT_ITALIC,
               colour=GREY)

    out = Path(path)
    w._flush()          # the last page's text is still pending
    w.doc.save(out)
    w.doc.close()
    return out
