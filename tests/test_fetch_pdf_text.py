"""Flattening PDF layout before it reaches the model.

A PDF carries lines, not sentences. The quote gate is a byte-exact substring
test, so a model copying faithfully from line-broken text produces a quote that
can never match. Measured on the real LR programme: 30% of correct quotes
passed before this, 85% after.
"""
from observatoire.fetch import flatten_pdf_text


def test_a_sentence_broken_across_lines_becomes_one_sentence():
    raw = "Nous multiplierons par cinq les moyens\nconsacrés à l’IA de défense."
    assert flatten_pdf_text(raw) == "Nous multiplierons par cinq les moyens consacrés à l’IA de défense."


def test_non_breaking_spaces_become_ordinary_ones():
    raw = "À condition de le vouloir."
    assert flatten_pdf_text(raw) == "À condition de le vouloir."
    assert " " not in flatten_pdf_text(raw)


def test_paragraph_breaks_survive_because_chunking_splits_on_them():
    raw = "Premier paragraphe\nsur deux lignes.\n\nSecond paragraphe."
    assert flatten_pdf_text(raw) == "Premier paragraphe sur deux lignes.\n\nSecond paragraphe."


def test_french_typography_is_not_touched():
    """NFKC must not rewrite the characters the quotes are made of."""
    raw = "« L’IA — l’énergie décarbonée : 2,3 Md€ — À condition »"
    assert flatten_pdf_text(raw) == raw
    for ch in "«»’—€éÀ":
        assert ch in flatten_pdf_text(raw)


def test_a_quote_copied_from_flattened_text_passes_the_byte_exact_gate():
    """The whole point: what the model reads is what the lint compares."""
    from observatoire.lint import check_quote_in_source
    from tests.test_lint import claim

    source = flatten_pdf_text("Bruno Retailleau propose d'instaurer\nun pourcentage de souveraineté "
                              "applicable à tout logiciel ou équipement acquis par l'État.")
    c = claim(quote_fr="un pourcentage de souveraineté applicable à tout logiciel")
    assert check_quote_in_source(c, source) == []


def test_it_does_not_invent_word_joins():
    """Zero end-of-line hyphens were measured in the corpus, so de-hyphenation
    would be guesswork on the one field that must never be guessed at."""
    raw = "un sur-\namortissement"
    assert flatten_pdf_text(raw) == "un sur- amortissement"
