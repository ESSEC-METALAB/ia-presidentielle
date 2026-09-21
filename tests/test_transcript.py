import pytest

from observatoire.transcript import (
    estimate_tokens, flatten, locate, mentions_ai, parse_vtt,
)

# Mirrors real yt-dlp auto-caption output: a 10ms repaint cue, then a real cue
# carrying the previous line as rolling context plus new words with per-word tags.
VTT = """WEBVTT
Kind: captions
Language: fr

00:00:10.590 --> 00:00:10.600 align:start position:0%
 

00:00:10.600 --> 00:00:12.830 align:start position:0%

Nous<00:00:10.920><c> doublerons</c><00:00:11.240><c> la</c><00:00:11.400><c> puissance</c>

00:00:12.830 --> 00:00:12.840 align:start position:0%
Nous doublerons la puissance
 

00:00:12.840 --> 00:00:15.180 align:start position:0%
Nous doublerons la puissance
de<00:00:13.100><c> calcul</c><00:00:13.500><c> nationale</c><00:00:14.000><c> d'ici</c><00:00:14.400><c> 2030.</c>

00:01:02.000 --> 00:01:04.500 align:start position:0%
de calcul nationale d'ici 2030.
Et<00:01:02.300><c> cent</c><00:01:02.600><c> mille</c><00:01:03.000><c> ingénieurs</c><00:01:03.600><c> formés.</c>
"""


@pytest.fixture
def cues():
    return parse_vtt(VTT)


# --- parsing: the rolling-caption duplication is the whole problem ---------

def test_keeps_only_new_content(cues):
    assert [c[1] for c in cues] == [
        "Nous doublerons la puissance",
        "de calcul nationale d'ici 2030.",
        "Et cent mille ingénieurs formés.",
    ]


def test_strips_word_timing_tags(cues):
    assert all("<" not in line for _, line in cues)


def test_repaint_cues_do_not_duplicate_lines(cues):
    lines = [c[1] for c in cues]
    assert len(lines) == len(set(lines))


def test_timestamps_are_cue_start_seconds(cues):
    assert [c[0] for c in cues] == [10, 12, 62]


def test_flatten_joins_with_single_spaces(cues):
    assert flatten(cues).startswith("Nous doublerons la puissance de calcul")


def test_empty_input_is_not_an_error():
    assert parse_vtt("") == []
    assert locate([], "anything") is None


# --- locate(): citation timestamp AND anti-fabrication, one operation ------

def test_locate_returns_the_second_the_quote_starts(cues):
    assert locate(cues, "Nous doublerons la puissance") == 10


def test_locate_finds_a_quote_spanning_two_cues(cues):
    assert locate(cues, "la puissance de calcul nationale") == 10


def test_locate_finds_a_later_quote(cues):
    assert locate(cues, "cent mille ingénieurs") == 62


def test_locate_rejects_a_quote_that_was_never_said(cues):
    assert locate(cues, "je propose deux cents milliards d'euros") is None


def test_locate_tolerates_surrounding_whitespace(cues):
    assert locate(cues, "  cent mille ingénieurs  ") == 62


# --- prefilter: measured against real French political speech --------------

@pytest.mark.parametrize("text", [
    "L'IA doit rester sous contrôle démocratique.",
    "Nous doublerons la puissance de calcul nationale.",
    "L'AI Act européen doit être simplifié.",
    "Un audit de l'intelligence artificielle dans l'administration.",
    "La reconnaissance faciale sera encadrée.",
])
def test_strong_terms_pass(text):
    assert mentions_ai(text)


@pytest.mark.parametrize("text", [
    # "calcul" here means political calculation — a real false positive we hit
    "Le report de l'âge de départ. C'est des calculs politiques, rien de plus.",
    # one stray weak term should not drag in a 29K-token transcript
    "Nous devons protéger les données fiscales des petites entreprises.",
    "Le débat sur le logement social doit être rouvert.",
])
def test_political_speech_without_ai_is_filtered_out(text):
    assert not mentions_ai(text)


def test_two_distinct_weak_terms_corroborate():
    assert mentions_ai("La transition numérique suppose des données fiables.")


def test_same_weak_term_repeated_does_not_corroborate():
    assert not mentions_ai("Des données, encore des données, toujours des données.")


def test_ia_inside_another_word_does_not_match():
    assert not mentions_ai("Les médias via cette initiative sociale.")


# --- token estimate is the basis of the video cost argument ----------------

def test_token_estimate_matches_measured_ratio():
    # 48,705 chars measured at 13,915 tokens on a real 43-minute programme
    assert estimate_tokens("x" * 48705) == pytest.approx(13915, rel=0.01)
