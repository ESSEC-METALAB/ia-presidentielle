"""The deterministic halves of annotation: the AI prefilter and the gates. Fictional texts."""

import pytest
from pydantic import ValidationError

from observatoire.domain.annotation import RejectionReason
from observatoire.services.ai_relevance import RelevanceSettings, TermRelevanceFilter
from observatoire.services.annotation_gates import AnnotationGates, GateSettings, find_quote
from support import draft, segment

RELEVANCE = RelevanceSettings(
    strong_patterns=(r"intelligence\s+artificielle", r"\bIA\b"),
    weak_patterns=(r"\bnum[ée]rique", r"\bdonn[ée]es"),
    weak_min_distinct=2,
)
GATES = AnnotationGates(
    ["regulation", "emploi"],
    GateSettings(
        quote_max_words=12, evaluative_stems_fr=("ambitieu",), evaluative_stems_en=("sensible",)
    ),
)
PASSAGE = (
    "Nous créerons une autorité de contrôle de l\u2019IA dotée de vrais pouvoirs. Le reste suit."
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Un plan pour l'intelligence  artificielle.", True),
        ("Former à l'IA dès le lycée.", True),
        ("Un TAIAUT n'est pas un sigle.", False),
        ("La réforme des données fiscales.", False),
        ("Le numérique et les données publiques.", True),
        ("Le numérique, encore le numérique.", False),
    ],
)
def test_one_strong_term_or_two_distinct_weak_ones_make_a_passage_relevant(
    text: str, expected: bool
) -> None:
    assert TermRelevanceFilter(RELEVANCE).is_relevant(text) is expected


def test_a_pattern_that_does_not_compile_is_a_configuration_error() -> None:
    with pytest.raises(ValidationError):
        RelevanceSettings(strong_patterns=("(unclosed",))


def test_without_weak_patterns_only_strong_ones_count() -> None:
    only_strong = TermRelevanceFilter(RelevanceSettings(strong_patterns=(r"\bIA\b",)))

    assert not only_strong.is_relevant("Le numérique et les données publiques.")


def test_an_exact_quote_is_kept_with_its_span() -> None:
    passage = segment(PASSAGE)

    accepted, rejected = GATES.review(passage, [draft("une autorité de contrôle de l\u2019IA")])

    assert rejected == []
    (annotation,) = accepted
    start, end = annotation.quote_span
    assert passage.text[start:end] == annotation.quote == "une autorité de contrôle de l\u2019IA"


def test_a_typographic_variant_matches_but_the_stored_quote_is_the_source_text() -> None:
    accepted, _ = GATES.review(segment(PASSAGE), [draft("autorité de contrôle de l'IA")])

    assert accepted[0].quote == "autorité de contrôle de l\u2019IA"


def test_whitespace_differences_do_not_hide_a_real_quote() -> None:
    span = find_quote(PASSAGE, "  une   autorité\nde contrôle ")

    assert span is not None
    assert PASSAGE[span[0] : span[1]] == "une autorité de contrôle"


def test_an_empty_quote_is_never_found() -> None:
    assert find_quote(PASSAGE, "   ") is None


@pytest.mark.parametrize(
    ("proposal", "reason"),
    [
        (draft("une autorité indépendante"), RejectionReason.QUOTE_NOT_IN_PASSAGE),
        (draft("une autorité de contrôle", dimension="sport"), RejectionReason.UNKNOWN_DIMENSION),
        (draft(PASSAGE), RejectionReason.QUOTE_TOO_LONG),
        (
            draft("une autorité de contrôle", summary_fr="Propose un plan ambitieux."),
            RejectionReason.EVALUATIVE_LANGUAGE,
        ),
    ],
)
def test_a_proposal_that_fails_a_gate_is_rejected_with_its_reason(
    proposal: object, reason: RejectionReason
) -> None:
    accepted, rejected = GATES.review(segment(PASSAGE), [proposal])  # type: ignore[list-item]

    assert accepted == []
    assert [r.reason for r in rejected] == [reason]


def test_the_same_quote_twice_is_kept_once() -> None:
    quote = "une autorité de contrôle"

    accepted, rejected = GATES.review(segment(PASSAGE), [draft(quote), draft(quote, "emploi")])

    assert [a.index for a in accepted] == [0]
    assert [r.reason for r in rejected] == [RejectionReason.DUPLICATE_QUOTE]


def test_the_candidates_own_judgement_words_are_never_censored() -> None:
    passage = segment("Notre plan est ambitieux pour l'IA et nous le tiendrons.")

    accepted, rejected = GATES.review(passage, [draft("Notre plan est ambitieux pour l'IA")])

    assert rejected == []
    assert accepted[0].quote == "Notre plan est ambitieux pour l'IA"


def test_without_a_stem_list_no_summary_is_judged() -> None:
    lenient = AnnotationGates(["regulation"], GateSettings(quote_max_words=12))

    accepted, _ = lenient.review(
        segment(PASSAGE), [draft("une autorité de contrôle", summary_fr="Un plan ambitieux.")]
    )

    assert len(accepted) == 1


def test_a_word_is_judged_only_in_the_language_whose_list_names_it() -> None:
    passage = segment(PASSAGE)
    french = draft("une autorité de contrôle", summary_fr="Protège les données sensibles.")
    english = draft("une autorité de contrôle", summary_en="A sensible authority.")

    kept, _ = GATES.review(passage, [french])
    _, rejected = GATES.review(passage, [english])

    assert len(kept) == 1
    assert rejected[0].detail == "summary_en: 'sensible'"
