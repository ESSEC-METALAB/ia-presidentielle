"""Provider-agnostic transport.

The point of this layer is that changing provider changes the transport and
nothing else. If the two dialects ever sent different bodies, a gold-set
comparison between them would be measuring two pipelines instead of two
models — which is the one thing gold.py exists to avoid.
"""
import json

import pytest

from observatoire.clients import (
    _MISTRAL_STATUS,
    _OPENAI_STATUS,
    PROVIDERS,
    MistralBatchClient,
    OpenAIBatchClient,
    batch_client,
    parse_results,
    request_body,
    sdk,
)
from observatoire.schema import llm_json_schema

PAYLOAD = dict(custom_id="abc:0", model="m", system="SYS", user="USR",
               schema=llm_json_schema())


# --- the agnosticism guarantee -------------------------------------------

def test_both_dialects_send_a_byte_identical_body():
    """Mistral's response_format serialises the same as OpenAI's, strict
    included — verified against the mistralai SDK's generated types."""
    assert OpenAIBatchClient.line(PAYLOAD)["body"] == MistralBatchClient.line(PAYLOAD)["body"]
    assert request_body(PAYLOAD) == MistralBatchClient.line(PAYLOAD)["body"]


def test_only_the_envelope_differs():
    """OpenAI puts the endpoint on every line; Mistral puts it on the job."""
    assert set(OpenAIBatchClient.line(PAYLOAD)) == {"custom_id", "method", "url", "body"}
    assert set(MistralBatchClient.line(PAYLOAD)) == {"custom_id", "body"}


def test_mistral_line_is_one_json_object_per_line():
    """'Do not add line breaks within a JSON object' — Mistral batch docs."""
    blob = json.dumps(MistralBatchClient.line(PAYLOAD), ensure_ascii=False)
    assert "\n" not in blob


def test_strict_structured_output_survives_at_both_providers():
    for line in (OpenAIBatchClient.line(PAYLOAD), MistralBatchClient.line(PAYLOAD)):
        rf = line["body"]["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["strict"] is True
        assert rf["json_schema"]["schema"]["additionalProperties"] is False


# --- the registry ---------------------------------------------------------

def test_every_provider_declares_what_it_needs():
    for name, p in PROVIDERS.items():
        assert p.name == name
        # Only a local server goes without a key.
        assert (p.key_env is None) == (p.batch == "sync")
        assert p.key_env is None or p.key_env.endswith("_API_KEY")
        assert p.batch in {"openai", "mistral", "sync"}
        assert p.default_model


def test_a_missing_key_names_the_variable_it_wanted(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        sdk(PROVIDERS["mistral"])


def test_the_factory_picks_the_dialect_not_the_name(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("MISTRAL_API_KEY", "y")
    assert isinstance(batch_client("openai"), OpenAIBatchClient)
    assert isinstance(batch_client("mistral"), MistralBatchClient)


def test_mistral_client_points_at_mistral(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "y")
    assert "api.mistral.ai" in str(batch_client("mistral").client.base_url)


# --- status vocabularies map onto the same four outcomes ------------------

def test_both_status_maps_cover_the_four_outcomes_the_pipeline_branches_on():
    for table in (_OPENAI_STATUS, _MISTRAL_STATUS):
        assert set(table.values()) <= {"pending", "ready", "expired", "failed"}
        assert "ready" in table.values() and "pending" in table.values()


def test_mistral_timeout_returns_chunks_to_the_queue_rather_than_failing():
    """TIMEOUT_EXCEEDED is Mistral's expiry; collect renames the artifact and
    the chunks are picked up by the next submit."""
    assert _MISTRAL_STATUS["TIMEOUT_EXCEEDED"] == "expired"
    assert _MISTRAL_STATUS["SUCCESS"] == "ready"
    assert _MISTRAL_STATUS["QUEUED"] == "pending"


# --- one parser for both --------------------------------------------------

def test_results_are_parsed_the_same_way_whoever_produced_them():
    row = {"custom_id": "a:0",
           "response": {"status_code": 200,
                        "body": {"choices": [{"finish_reason": "stop",
                                              "message": {"content": '{"claims":[]}'}}]}}}
    out, unusable = parse_results(json.dumps(row))
    assert out == {"a:0": {"claims": []}} and unusable == {}


# --- a local model: the batch surface over synchronous calls ----------------

def test_a_local_provider_needs_no_key_and_gets_the_sync_client():
    from observatoire.clients import SyncBatchClient
    assert isinstance(batch_client("ollama"), SyncBatchClient)


def _local(monkeypatch, answers):
    from observatoire.clients import SyncBatchClient, SyncClient
    monkeypatch.setattr(SyncClient, "complete", lambda self, p: answers.get(p["custom_id"]))
    return SyncBatchClient(provider=PROVIDERS["ollama"])


def test_a_local_batch_is_answered_by_the_time_it_is_submitted(monkeypatch):
    client = _local(monkeypatch, {"a:0": {"claims": []}})
    bid = client.submit([{**PAYLOAD, "custom_id": "a:0"}, {**PAYLOAD, "custom_id": "b:0"}])
    assert client.poll(bid) == "ready"
    # b:0 gave no usable answer, so it is absent rather than invented as empty.
    assert client.results(bid) == {"a:0": {"claims": []}}


def test_a_local_batch_lost_with_its_process_returns_to_the_queue(monkeypatch):
    assert _local(monkeypatch, {}).poll("local-0123456789abcdef") == "failed"


def test_another_providers_batch_is_never_declared_failed_by_the_local_client(monkeypatch):
    """Declared failed, it would be renamed .expired and its claims never collected."""
    assert _local(monkeypatch, {}).poll("batch_68f0c1") == "pending"
