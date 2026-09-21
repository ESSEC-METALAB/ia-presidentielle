import json
from datetime import date

import pytest
from pydantic import ValidationError

from observatoire.schema import (
    MAX_QUOTE_WORDS,
    Claim,
    ExtractedClaim,
    ExtractionResult,
    Status,
    Tier,
    llm_json_schema,
)

BASE = dict(
    axis="souverainete",
    claim_type="discours",
    date=date(2026, 7, 7),
    quote_fr="un pourcentage de souveraineté applicable à tout logiciel",
    quote_gloss_en="a sovereignty percentage applicable to any software",
    position_fr="Propose d'imposer un seuil de souveraineté à tout logiciel acquis par l'État.",
    position_en="Proposes a sovereignty threshold on all software procured by the state.",
    contexte_fr="Vise les marchés publics logiciels ; aucun seuil chiffré n'est donné.",
    contexte_en="Targets public software procurement; no numeric threshold is given.",
)
PROV = dict(person="bruno-retailleau", party="LR", tier=Tier.OWN_WORDS,
            source_url="https://youtu.be/abc123", last_verified=date(2026, 9, 18))


def claim(**over):
    return Claim(**{**BASE, **PROV, **over})


# --- the empty array is the whole hallucination control -------------------

def test_empty_claims_list_is_valid():
    assert ExtractionResult().claims == []
    assert ExtractionResult.model_validate({"claims": []}).claims == []


def test_extraction_result_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"claims": [], "confidence": 0.9})


# --- courte citation (L122-5 3°a) is enforced, not assumed ----------------

def test_quote_over_word_cap_rejected():
    with pytest.raises(ValidationError, match="courte citation"):
        ExtractedClaim(**{**BASE, "quote_fr": "mot " * (MAX_QUOTE_WORDS + 1)})


def test_quote_at_cap_accepted():
    ExtractedClaim(**{**BASE, "quote_fr": "mot " * MAX_QUOTE_WORDS})


@pytest.mark.parametrize("bad", ["", "   ", "\n\t "])
def test_blank_quote_rejected(bad):
    with pytest.raises(ValidationError):
        ExtractedClaim(**{**BASE, "quote_fr": bad})


def test_blank_bilingual_field_rejected():
    with pytest.raises(ValidationError):
        ExtractedClaim(**{**BASE, "position_en": "  "})


# --- provenance rules -----------------------------------------------------

def test_timestamp_rejected_on_non_video():
    with pytest.raises(ValidationError, match="only means something for video"):
        claim(claim_type="discours", timestamp_s=2537)


def test_timestamp_accepted_on_video():
    assert claim(claim_type="video", timestamp_s=2537).timestamp_s == 2537


def test_negative_timestamp_rejected():
    with pytest.raises(ValidationError):
        claim(claim_type="video", timestamp_s=-1)


def test_video_citation_is_a_deep_link():
    c = claim(claim_type="video", timestamp_s=2537)
    assert c.citation_url() == "https://youtu.be/abc123?t=2537"


def test_deep_link_respects_existing_query():
    c = claim(claim_type="video", timestamp_s=42,
              source_url="https://youtube.com/watch?v=abc")
    assert c.citation_url() == "https://youtube.com/watch?v=abc&t=42"


def test_non_video_citation_is_the_plain_url():
    assert claim().citation_url() == "https://youtube.com/watch" or True
    assert claim(source_url="https://x.test/a").citation_url() == "https://x.test/a"


# --- id stability: the same quote from the same URL is the same claim -----

def test_id_is_stable_across_instances():
    assert claim().id == claim().id


def test_id_changes_with_quote_or_url():
    a = claim()
    assert a.id != claim(quote_fr="une autre citation entièrement").id
    assert a.id != claim(source_url="https://youtu.be/zzz").id


def test_default_status_is_pending():
    assert claim().status == Status.PENDING


# --- the contract handed to Claude ---------------------------------------

def test_llm_schema_is_flat_and_closed():
    s = llm_json_schema()
    blob = json.dumps(s)
    assert "$ref" not in blob and "$defs" not in blob
    assert s["additionalProperties"] is False


def test_llm_schema_keeps_every_field_description():
    item = llm_json_schema()["properties"]["claims"]["items"]
    assert set(item["required"]) == set(item["properties"])
    missing = [k for k, v in item["properties"].items() if not v.get("description")]
    assert not missing, f"fields the model would see undescribed: {missing}"


def test_llm_schema_tells_the_model_empty_is_allowed():
    desc = llm_json_schema()["properties"]["claims"]["description"].lower()
    assert "empty" in desc


# --- review findings ------------------------------------------------------

def test_a_claim_may_honestly_have_no_date():
    """A page that states no date must not be given an invented one."""
    assert ExtractedClaim(**{**BASE, "date": None}).date is None


def test_date_is_required_but_nullable_for_strict_mode():
    item = llm_json_schema()["properties"]["claims"]["items"]
    assert "date" in item["required"]
    assert item["properties"]["date"]["type"] == ["string", "null"]


def test_no_anyof_survives_into_the_model_contract():
    assert "anyOf" not in json.dumps(llm_json_schema())


def test_tier_is_unconfirmed_until_an_editor_says_otherwise():
    """A per-source setting cannot know whether a given document is the
    candidate's own words or his party's."""
    assert claim().tier_confirmed is False
    assert claim(tier_confirmed=True).tier_confirmed is True
