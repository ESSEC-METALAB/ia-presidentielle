import json

import pytest

from observatoire.extract import (
    CHUNK_CHARS,
    EXPIRED_SUFFIX,
    REQUESTS_SUFFIX,
    RESPONSES_SUFFIX,
    FakeClient,
    build_requests,
    chunk,
    collect,
    pending_batches,
    submit,
    submitted_ids,
    to_claims,
)
from observatoire.prompt import prompt_hash, system_prompt
from observatoire.schema import Cue, Document, ExtractionResult, Tier

EC = dict(
    axis="souverainete", claim_type="discours", date="2026-07-07",
    quote_fr="un pourcentage de souveraineté applicable à tout logiciel",
    quote_gloss_en="a sovereignty percentage applicable to any software",
    position_fr="Propose un seuil de souveraineté sur les logiciels de l'État.",
    position_en="Proposes a sovereignty threshold on state software.",
    contexte_fr="Vise les marchés publics ; aucun seuil chiffré.",
    contexte_en="Targets public procurement; no numeric threshold.",
)


def document(**over):
    base = dict(person="bruno-retailleau", source_id="s", kind="pdf", tier=Tier.OWN_WORDS,
                url="https://republicains.fr/LR_IA.pdf", text="texte", title="Programme")
    return Document(**{**base, **over})


# --- chunking ------------------------------------------------------------

def test_short_text_is_one_chunk():
    assert chunk("court") == ["court"]


def test_empty_text_yields_nothing():
    assert chunk("") == [] and chunk("   ") == []


def test_long_text_is_split_and_nothing_is_lost():
    text = "\n\n".join(f"Paragraphe {i}. " + "mot " * 80 for i in range(40))
    parts = chunk(text)
    assert len(parts) > 1
    assert len("".join(parts)) >= len(text.strip())


def test_chunks_respect_the_size_budget():
    text = "\n\n".join("phrase. " * 60 for _ in range(30))
    assert all(len(c) <= CHUNK_CHARS for c in chunk(text))


def test_overlap_keeps_a_boundary_quote_intact():
    """A quote must survive falling on a chunk edge, or the lint drops a real claim."""
    quote = "un pourcentage de souveraineté applicable à tout logiciel et équipement"
    text = ("préambule. " * 700) + quote + (" conclusion. " * 700)
    assert any(quote in c for c in chunk(text))


# --- requests ------------------------------------------------------------

def test_one_request_per_chunk_with_traceable_ids():
    doc = document(text="\n\n".join("phrase. " * 60 for _ in range(30)))
    reqs = build_requests([doc], {"bruno-retailleau": "Bruno Retailleau"})
    assert len(reqs) == len(chunk(doc.text))
    assert all(r.custom_id.startswith(doc.url_hash + ":") for r in reqs)
    assert reqs[0].person_name == "Bruno Retailleau"


def test_payload_carries_schema_and_named_person():
    reqs = build_requests([document()], {"bruno-retailleau": "Bruno Retailleau"})
    p = reqs[0].payload("gpt-5.6-luna")
    assert p["schema"]["additionalProperties"] is False
    assert "Bruno Retailleau" in p["user"]
    assert "empty list" in p["system"]


# --- artifacts: the provenance record --------------------------------------

def test_submit_writes_an_auditable_request_record(tmp_path):
    reqs = build_requests([document()], {})
    client = FakeClient()
    bid = submit(reqs, client, "gpt-5.6-luna", tmp_path)
    lines = (tmp_path / f"{bid}.requests.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    assert rec["model"] == "gpt-5.6-luna"
    assert rec["prompt_hash"] == prompt_hash()
    assert len(rec["text_sha256"]) == 64
    assert rec["url"] == "https://republicains.fr/LR_IA.pdf"


def test_collect_writes_the_raw_response(tmp_path):
    reqs = build_requests([document()], {})
    client = FakeClient(answers={reqs[0].custom_id: {"claims": [EC]}})
    bid = submit(reqs, client, "m", tmp_path)
    collect(bid, reqs, client, tmp_path)
    rec = json.loads((tmp_path / f"{bid}.responses.jsonl").read_text().splitlines()[0])
    assert rec["response"]["claims"][0]["quote_fr"] == EC["quote_fr"]


def test_empty_result_produces_no_claims(tmp_path):
    reqs = build_requests([document()], {})
    client = FakeClient()  # defaults to {"claims": []}
    bid = submit(reqs, client, "m", tmp_path)
    assert collect(bid, reqs, client, tmp_path) == []


def test_malformed_answer_is_dropped_not_guessed_at(tmp_path):
    reqs = build_requests([document()], {})
    client = FakeClient(answers={reqs[0].custom_id: {"claims": [{"axis": "nope"}]}})
    bid = submit(reqs, client, "m", tmp_path)
    assert collect(bid, reqs, client, tmp_path) == []


# --- what has been asked already, so nothing is paid for twice -------------
#
# The artifacts the provenance rules already require double as the queue.
# There is no batch-id table to drift out of sync with them.

def test_nothing_is_submitted_when_there_is_nothing_new(tmp_path):
    assert submitted_ids(tmp_path) == set()
    reqs = build_requests([document()], {})
    submit(reqs, FakeClient(), "m", tmp_path)
    assert submitted_ids(tmp_path) == {r.custom_id for r in reqs}


def test_a_chunk_that_answered_nothing_is_not_asked_again(tmp_path):
    """``claims: []`` is the expected answer for most documents. Re-asking
    would pay for the whole corpus again every morning."""
    reqs = build_requests([document()], {})
    client = FakeClient()  # defaults to {"claims": []}
    bid = submit(reqs, client, "m", tmp_path)
    assert collect(bid, reqs, client, tmp_path) == []
    assert submitted_ids(tmp_path) == {r.custom_id for r in reqs}


def test_a_collected_batch_is_no_longer_pending(tmp_path):
    reqs = build_requests([document()], {})
    client = FakeClient()
    bid = submit(reqs, client, "m", tmp_path)
    assert pending_batches(tmp_path) == [bid]
    collect(bid, reqs, client, tmp_path)
    assert pending_batches(tmp_path) == []


def test_an_expired_batch_returns_its_chunks_to_the_queue(tmp_path):
    """Its record is kept, but it counts as neither submitted nor pending, so
    the next submit asks for those chunks again."""
    reqs = build_requests([document()], {})
    bid = submit(reqs, FakeClient(), "m", tmp_path)
    (tmp_path / f"{bid}{REQUESTS_SUFFIX}").rename(tmp_path / f"{bid}{EXPIRED_SUFFIX}")

    assert submitted_ids(tmp_path) == set()
    assert pending_batches(tmp_path) == []
    assert (tmp_path / f"{bid}{EXPIRED_SUFFIX}").exists()


# --- provenance is attached by code, never by the model --------------------

def test_provenance_comes_from_the_document():
    doc = document(archive_url="https://web.archive.org/web/2026/x")
    claims = to_claims(doc, ExtractionResult(claims=[EC]), party="LR")
    c = claims[0]
    assert c.person == "bruno-retailleau" and c.party == "LR"
    assert c.tier == Tier.OWN_WORDS
    assert c.source_url == doc.url and c.archive_url == doc.archive_url


def test_model_cannot_supply_its_own_provenance():
    with pytest.raises(Exception):
        ExtractionResult.model_validate(
            {"claims": [{**EC, "source_url": "https://evil.test/made-up"}]})


def test_video_quote_is_resolved_to_a_timestamp():
    doc = document(kind="youtube", cues=[
        Cue(t=10, line="Nous doublerons la puissance"),
        Cue(t=62, line="de calcul nationale d'ici 2030."),
    ])
    ec = {**EC, "claim_type": "video", "quote_fr": "la puissance de calcul nationale"}
    c = to_claims(doc, ExtractionResult(claims=[ec]))[0]
    assert c.timestamp_s == 10
    assert c.citation_url().endswith("?t=10")


def test_video_quote_absent_from_the_transcript_gets_no_timestamp():
    doc = document(kind="youtube", cues=[Cue(t=10, line="autre chose entièrement")])
    ec = {**EC, "claim_type": "video", "quote_fr": "un pourcentage de souveraineté"}
    assert to_claims(doc, ExtractionResult(claims=[ec]))[0].timestamp_s is None


def test_non_video_claims_carry_no_timestamp():
    assert to_claims(document(), ExtractionResult(claims=[EC]))[0].timestamp_s is None


def test_claims_start_pending():
    assert to_claims(document(), ExtractionResult(claims=[EC]))[0].status == "pending"


# --- the prompt is versioned ----------------------------------------------

def test_prompt_hash_tracks_prompt_changes():
    assert prompt_hash() == prompt_hash()
    assert len(prompt_hash()) == 16


def test_prompt_states_the_rules_the_lints_enforce():
    sp = system_prompt()
    assert "empty list" in sp                  # anti-invention
    assert "character for character" in sp     # quote-in-source
    assert "ambitieux" in sp                   # neutrality
    assert sp.count("- **") == 6               # six axes


def test_a_batch_where_every_line_errored_is_not_a_successful_extraction(tmp_path):
    """An account over its billing limit completes the batch with every line
    errored. `results` skips errored lines, so that arrives as zero results —
    while a document that legitimately holds no AI position still comes back
    as {"claims": []}, which IS a result.

    Measured 2026-09-21: batch_6ab0fe55 came back "0 claims" this way, and
    treating it as success marked all 110 chunks done so they would never be
    asked again.
    """
    reqs = build_requests([document()], {})
    submitted = FakeClient()
    bid = submit(reqs, submitted, "m", tmp_path)

    class EveryLineErrored(FakeClient):
        def results(self, batch_id):
            return {}

    assert collect(bid, reqs, EveryLineErrored(), tmp_path) == []
    # The discriminator the CLI acts on: nothing was written at all.
    assert (tmp_path / f"{bid}{RESPONSES_SUFFIX}").stat().st_size == 0


def test_a_batch_that_genuinely_found_nothing_still_writes_a_response(tmp_path):
    """The contrast that makes the check above safe: [] is the expected answer
    for most documents and must keep counting as extracted."""
    reqs = build_requests([document()], {})
    client = FakeClient()  # defaults to {"claims": []}
    bid = submit(reqs, client, "m", tmp_path)
    assert collect(bid, reqs, client, tmp_path) == []
    assert (tmp_path / f"{bid}{RESPONSES_SUFFIX}").stat().st_size > 0
