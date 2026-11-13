"""The review PDF.

One property matters: the quote is the evidence, so it has to come out of the
document exactly as it went in. Base14 fonts encode as Latin-1, which has no
U+2019, and this corpus is full of « l’IA » — the first version of this module
rendered that as a stray dot.
"""
import re
from datetime import date

import pymupdf

from observatoire.report import write_report
from observatoire.schema import Claim, Tier

QUOTE = "À mes yeux, l’IA dépasse ce qu’a été le nucléaire — un coût de 2,3 Md€"


def claim(**over):
    base = dict(
        axis="defense", claim_type="programme", date=date(2026, 7, 7),
        quote_fr=QUOTE, quote_gloss_en="In my view, AI surpasses nuclear power",
        position_fr="Place l’IA au-dessus du précédent nucléaire.",
        position_en="Frames AI as surpassing the nuclear precedent.",
        contexte_fr="Analogie avec le choix nucléaire français.",
        contexte_en="An analogy with the French nuclear choice.",
        person="bruno-retailleau", party="LR", tier=Tier.OWN_WORDS,
        source_url="https://republicains.fr/a",
        archive_url="https://web.archive.org/web/20260918144520/https://a.test/1",
        last_verified=date(2026, 9, 18))
    return Claim(**{**base, **over})


def flat(path):
    doc = pymupdf.open(path)
    return re.sub(r"\s+", " ", "\n".join(p.get_text() for p in doc))


def test_the_quote_survives_byte_for_byte(tmp_path):
    out = write_report(tmp_path / "r.pdf", [claim()], model="m", prompt_hash="h")
    assert re.sub(r"\s+", " ", QUOTE) in flat(out)


def test_french_typography_is_not_mangled(tmp_path):
    out = write_report(tmp_path / "r.pdf", [claim()], model="m", prompt_hash="h")
    text = flat(out)
    for ch in "’«»éÀ€—":
        assert ch in text, f"{ch!r} did not survive"


def test_the_provenance_header_names_the_model_and_the_prompt(tmp_path):
    out = write_report(tmp_path / "r.pdf", [claim()], model="gpt-5.6-luna",
                       prompt_hash="b30d85529924783a")
    text = flat(out)
    assert "gpt-5.6-luna" in text and "b30d85529924783a" in text


def test_both_links_a_reviewer_needs_are_present(tmp_path):
    c = claim()
    out = write_report(tmp_path / "r.pdf", [c], model="m", prompt_hash="h")
    text = flat(out)
    assert c.source_url in text and c.archive_url in text


def test_a_missing_archive_is_called_out_not_omitted(tmp_path):
    out = write_report(tmp_path / "r.pdf", [claim(archive_url=None)],
                       model="m", prompt_hash="h")
    assert "ne survivrait pas" in flat(out)


def test_an_empty_extraction_says_so_rather_than_producing_a_blank_page(tmp_path):
    """[] is the expected answer for most documents, not a failure."""
    out = write_report(tmp_path / "r.pdf", [], model="m", prompt_hash="h")
    assert "Aucune position extraite" in flat(out)


def test_many_claims_paginate_without_clipping(tmp_path):
    claims = [claim(source_url=f"https://republicains.fr/{i}") for i in range(12)]
    out = write_report(tmp_path / "r.pdf", claims, model="m", prompt_hash="h")
    doc = pymupdf.open(out)
    assert doc.page_count > 1
    text = flat(out)
    assert text.count(re.sub(r"\s+", " ", QUOTE)) == 12   # none lost to a page break
