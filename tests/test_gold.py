"""Scoring the gold set.

The number that decides the model is empty discipline. Every other metric
rewards finding things; only that one catches a model that manufactures a
position because it was asked to find one.
"""
from observatoire.gold import Scorecard, same_quote, score
from observatoire.schema import Document, Tier

QUOTE = "un pourcentage de souveraineté applicable à tout logiciel"
SOURCE = f"Le candidat a déclaré : « {QUOTE} », lors de son discours."

CLAIM = dict(
    axis="souverainete", claim_type="discours", date="2026-07-07",
    quote_fr=QUOTE, quote_gloss_en="a sovereignty percentage for any software",
    position_fr="Propose un seuil de souveraineté.",
    position_en="Proposes a sovereignty threshold.",
    contexte_fr="Vise les marchés publics.", contexte_en="Targets procurement.",
)


def document(text=SOURCE, **over):
    base = dict(person="bruno-retailleau", source_id="s", kind="pdf",
                tier=Tier.OWN_WORDS, url="https://republicains.fr/a",
                text=text, title="Discours")
    return Document(**{**base, **over})


def run(gold, answer):
    doc = document()
    return score("stub", gold, {doc.url_hash: doc}, lambda d: answer)


# --- the control that matters ----------------------------------------------

def test_a_model_that_stays_silent_on_a_silent_document_scores_full_marks():
    card = run([{"url_hash": document().url_hash, "claims": []}], {"claims": []})
    assert card.empty_discipline == 1.0
    assert card.invented == []


def test_a_position_invented_where_a_human_found_none_is_recorded_in_full():
    """Not merely counted. Someone has to read what the model made up."""
    card = run([{"url_hash": document().url_hash, "claims": []}], {"claims": [CLAIM]})
    assert card.empty_discipline == 0.0
    assert len(card.invented) == 1
    assert QUOTE[:30] in card.invented[0]


def test_an_unusable_answer_is_an_error_not_an_empty_extraction():
    """[] is the correct answer for most documents, so folding a failure into
    one would flatter the model into looking disciplined."""
    card = run([{"url_hash": document().url_hash, "claims": []}], None)
    assert card.failures and card.stayed_empty == 0
    assert card.empty_discipline == 0.0


def test_a_malformed_answer_is_an_error_too():
    card = run([{"url_hash": document().url_hash, "claims": []}],
               {"claims": [{"axis": "pas-un-axe"}]})
    assert card.failures and card.stayed_empty == 0


# --- quote fidelity ---------------------------------------------------------

def test_a_verbatim_quote_passes_the_same_gate_production_uses():
    card = run([{"url_hash": document().url_hash, "claims": [{"axis": "souverainete",
                                                              "quote_fr": QUOTE}]}],
               {"claims": [CLAIM]})
    assert card.quote_fidelity == 1.0


def test_a_quote_not_in_the_source_fails():
    invented = {**CLAIM, "quote_fr": "une phrase jamais prononcée"}
    card = run([{"url_hash": document().url_hash, "claims": []}], {"claims": [invented]})
    assert card.quote_fidelity == 0.0


# --- axis agreement ---------------------------------------------------------

def test_agreeing_with_the_human_axis_counts():
    card = run([{"url_hash": document().url_hash,
                 "claims": [{"axis": "souverainete", "quote_fr": QUOTE}]}],
               {"claims": [CLAIM]})
    assert card.recall == 1.0 and card.axis_agreement == 1.0


def test_the_right_quote_under_the_wrong_axis_is_found_but_not_agreed():
    card = run([{"url_hash": document().url_hash,
                 "claims": [{"axis": "financement", "quote_fr": QUOTE}]}],
               {"claims": [CLAIM]})
    assert card.recall == 1.0 and card.axis_agreement == 0.0


def test_a_missed_claim_lowers_recall_without_inventing_an_agreement():
    card = run([{"url_hash": document().url_hash,
                 "claims": [{"axis": "souverainete", "quote_fr": QUOTE}]}],
               {"claims": []})
    assert card.recall == 0.0 and card.axis_agreement is None


# --- comparing quotes the way a reader would --------------------------------

def test_a_typographic_apostrophe_is_not_a_disagreement():
    assert same_quote("l’IA souveraine", "l'IA souveraine")


def test_whitespace_and_case_are_not_disagreements():
    assert same_quote("l'IA   SOUVERAINE\n", "l'ia souveraine")


def test_a_longer_selection_around_the_same_sentence_still_matches():
    """The schema does not constrain how much context a model includes, so
    scoring a wider span as a miss would punish a judgement call."""
    assert same_quote("l'IA souveraine", "je crois que l'IA souveraine est la clé")


def test_a_different_sentence_does_not_match():
    assert not same_quote("l'IA souveraine", "la régulation européenne")


def test_an_empty_quote_never_matches():
    assert not same_quote("", "l'IA souveraine")


# --- reporting --------------------------------------------------------------

def test_a_document_missing_from_the_corpus_is_an_error_not_a_silent_skip():
    card = score("stub", [{"url_hash": "deadbeef", "claims": []}], {}, lambda d: {"claims": []})
    assert card.documents == 0 and len(card.failures) == 1


def test_metrics_are_none_rather_than_zero_when_nothing_was_measured():
    """A model that was never asked has not scored 0%. Printing 0 would read
    as a failure it did not earn."""
    card = Scorecard(model="stub")
    assert card.empty_discipline is None and card.quote_fidelity is None
    assert card.recall is None and card.axis_agreement is None
    assert "n/a" in card.row()
