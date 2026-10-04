"""Light segmentation rules, on fictional texts."""

from observatoire.domain.models import DocumentSegmentation, ExclusionReason
from observatoire.services.segmentation import ParagraphSegmenter, SegmentationSettings
from support import document, source

SETTINGS = SegmentationSettings(
    min_chars=40,
    max_chars=200,
    wrapped_kinds=("pdf",),
    repeated_line_max_chars=120,
    repeated_in_document_min=3,
    repeated_in_document_min_words=2,
    repeated_in_source_min_documents=3,
    section_cut_markers=("Découvrez aussi",),
    interface_line_prefixes=("Nous utilisons des cookies",),
    stage_direction_patterns={"assemblee_nationale": (r"(?i)\(applaudissements[^()]*\)",)},
    abbreviations=("M.", "etc."),
)
SEGMENTER = ParagraphSegmenter(SETTINGS)

PARAGRAPH = "Camille Exemple propose un plan d'équipement numérique pour chaque commune du pays."


def _segment(text: str, kind: str = "rss") -> DocumentSegmentation:
    (result,) = SEGMENTER.segment(source(kind=kind), [document(text)])
    return result


def _texts(result: DocumentSegmentation) -> list[str]:
    return [segment.text for segment in result.segments]


def _excluded(result: DocumentSegmentation, text: str) -> list[tuple[str, ExclusionReason]]:
    return [(text[p.span[0] : p.span[1]], p.reason) for p in result.excluded]


def test_every_segment_is_the_documents_own_text_over_its_spans() -> None:
    text = (
        "Titre\n\n" + PARAGRAPH + "\n  Une   deuxième ligne,\tavec des espaces, reste exacte.  \n"
    )

    result = _segment(text)

    for segment in result.segments:
        rebuilt = " ".join(" ".join(text[s:e].split()) for s, e in segment.spans)
        assert rebuilt == segment.text


def test_interjections_alone_leave_nothing_usable() -> None:
    text = "Bravo !\n\nTrès bien !"

    result = _segment(text, kind="assemblee_nationale")

    assert result.is_empty
    assert {reason for _, reason in _excluded(result, text)} == {ExclusionReason.TOO_SHORT}


def test_stage_directions_are_cut_out_of_the_speakers_words_exactly() -> None:
    text = (
        PARAGRAPH
        + "\n\n"
        + (  # not on the first line: offsets must be absolute
            "Nous voterons ce texte avec conviction et sans hésitation. "
            "(Applaudissements sur les bancs du groupe Exemple.) Et nous le défendrons ici."
        )
    )

    result = _segment(text, kind="assemblee_nationale")

    assert _texts(result)[1] == (
        "Nous voterons ce texte avec conviction et sans hésitation. Et nous le défendrons ici."
    )
    assert _excluded(result, text) == [
        ("(Applaudissements sur les bancs du groupe Exemple.)", ExclusionReason.STAGE_DIRECTION)
    ]


def test_stage_directions_are_kept_in_sources_that_are_not_a_parliamentary_record() -> None:
    text = "Le public a réagi au discours (applaudissements nourris) pendant de longues minutes."

    assert _texts(_segment(text, kind="rss")) == [text]


def test_a_short_line_joins_the_next_line_of_its_block() -> None:
    result = _segment("Le numérique\n" + PARAGRAPH)

    assert _texts(result) == ["Le numérique " + PARAGRAPH]


def test_turns_separated_by_a_blank_line_are_never_merged() -> None:
    text = "C'est faux !\n\n" + PARAGRAPH

    result = _segment(text, kind="assemblee_nationale")

    assert _texts(result) == [PARAGRAPH]
    assert _excluded(result, text) == [("C'est faux !", ExclusionReason.TOO_SHORT)]


def test_long_paragraphs_are_cut_between_sentences_never_inside_one() -> None:
    sentences = [
        "M. Dupont, maire fictif de Valbourg, a présenté le projet de médiathèque numérique.",
        "Le chantier commencera au printemps et durera dix-huit mois selon le calendrier.",
        "Les habitants pourront consulter les plans en mairie, etc. jusqu'à la fin du mois.",
    ]

    result = _segment(" ".join(sentences))

    assert _texts(result) == [" ".join(sentences[:2]), sentences[2]]


def test_wrapped_lines_are_joined_back_into_their_paragraph() -> None:
    text = "Camille Exemple propose un plan\nd'équipement numérique pour chaque\ncommune du pays."

    assert _texts(_segment(text, kind="pdf")) == [PARAGRAPH]


def test_a_sentence_carried_over_a_page_break_stays_whole() -> None:
    text = (
        "Camille Exemple propose un plan d'équipement\n\n12\n\n"
        "numérique pour chaque commune du pays."
    )

    result = _segment(text, kind="pdf")

    assert _texts(result) == [PARAGRAPH]
    assert _excluded(result, text) == [("12", ExclusionReason.PAGE_NUMBER)]


def test_a_year_alone_on_a_wrapped_line_is_text_not_a_page_number() -> None:
    text = "Camille Exemple promet un accès au numérique pour tous d'ici\n2030\net sans exception."

    assert "2030" in _texts(_segment(text, kind="pdf"))[0]


def test_a_header_repeated_through_a_document_goes_but_repeated_small_words_stay() -> None:
    pages = [
        "Programme fictif pour demain\nla\n"
        f"proposition numéro {n} décrit une mesure précise et chiffrée."
        for n in range(3)
    ]
    text = "\n\n".join(pages)

    result = _segment(text, kind="pdf")

    reasons = [reason for _, reason in _excluded(result, text)]
    assert reasons == [ExclusionReason.REPEATED_IN_DOCUMENT] * 3
    assert all(segment.text.startswith("la proposition") for segment in result.segments)


def test_lines_shared_by_several_documents_of_a_source_are_excluded() -> None:
    documents = [
        document(f"{PARAGRAPH} Variante {n}.\nPrésidente du Parti Exemple") for n in range(3)
    ]

    results = SEGMENTER.segment(source(), documents)

    for result, doc in zip(results, documents, strict=True):
        assert _excluded(result, doc.text) == [
            ("Présidente du Parti Exemple", ExclusionReason.REPEATED_IN_SOURCE)
        ]


def test_a_line_shared_by_fewer_documents_than_the_threshold_is_kept() -> None:
    documents = [
        document(f"{PARAGRAPH} Variante {n}.\nPrésidente du Parti Exemple") for n in range(2)
    ]

    results = SEGMENTER.segment(source(), documents)

    reasons = {passage.reason for result in results for passage in result.excluded}
    assert ExclusionReason.REPEATED_IN_SOURCE not in reasons


def test_everything_after_a_related_articles_marker_is_excluded() -> None:
    text = PARAGRAPH + "\nDécouvrez aussi\nUn autre article\nEncore un autre article"

    result = _segment(text)

    assert _texts(result) == [PARAGRAPH]
    excluded_text, reason = _excluded(result, text)[0]
    assert reason == ExclusionReason.RELATED_LINKS
    assert excluded_text.endswith("Encore un autre article")


def test_interface_text_such_as_a_consent_banner_is_excluded() -> None:
    text = "Nous utilisons des cookies pour stocker des informations sur votre appareil."

    result = _segment(text)

    assert result.is_empty
    assert _excluded(result, text) == [(text, ExclusionReason.INTERFACE_TEXT)]


def test_the_version_changes_with_any_setting() -> None:
    other = ParagraphSegmenter(SETTINGS.model_copy(update={"min_chars": 41}))

    assert other.version != SEGMENTER.version


def test_segment_ids_are_stable_and_unique_within_a_document() -> None:
    sentences = " ".join(
        f"Phrase fictive numéro {n} qui décrit une mesure du programme." for n in range(6)
    )

    result = _segment(sentences)

    ids = [segment.id for segment in result.segments]
    assert len(ids) == len(set(ids)) > 1
    assert ids[0] == f"{result.document_hash[:16]}-000"
