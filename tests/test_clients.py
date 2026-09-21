import json
from types import SimpleNamespace

import pytest

from observatoire.clients import _OPENAI_STATUS, OpenAIBatchClient
from observatoire.schema import llm_json_schema

PAYLOAD = dict(custom_id="abc:0", model="gpt-5.6-luna",
               system="SYS", user="USR", schema=llm_json_schema())


def test_line_matches_the_documented_batch_format():
    line = OpenAIBatchClient.line(PAYLOAD)
    assert set(line) == {"custom_id", "method", "url", "body"}
    assert line["method"] == "POST"
    assert line["url"] == "/v1/chat/completions"
    assert line["custom_id"] == "abc:0"


def test_line_requests_strict_structured_output():
    rf = OpenAIBatchClient.line(PAYLOAD)["body"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False


def test_line_carries_both_prompt_roles_in_order():
    msgs = OpenAIBatchClient.line(PAYLOAD)["body"]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == "SYS" and msgs[1]["content"] == "USR"


def test_schema_sent_has_no_keywords_strict_mode_rejects():
    blob = json.dumps(OpenAIBatchClient.line(PAYLOAD))
    assert '"format"' not in blob


# --- status mapping: the pipeline branches on three outcomes ---------------

@pytest.mark.parametrize("raw,expected", [
    ("validating", "pending"), ("in_progress", "pending"), ("finalizing", "pending"),
    ("completed", "ready"), ("expired", "expired"),
    ("failed", "failed"), ("cancelled", "failed"), ("cancelling", "failed"),
])
def test_every_documented_status_is_mapped(raw, expected):
    assert _OPENAI_STATUS[raw] == expected


def test_unknown_status_is_treated_as_pending():
    assert _OPENAI_STATUS.get("something_new", "pending") == "pending"


# --- result parsing --------------------------------------------------------

def _client_with(lines, output_file_id="file-out"):
    """A stand-in exposing only the three SDK calls results() touches."""
    c = OpenAIBatchClient.__new__(OpenAIBatchClient)
    body = "\n".join(json.dumps(x) for x in lines)
    c.client = SimpleNamespace(
        batches=SimpleNamespace(
            retrieve=lambda _id: SimpleNamespace(output_file_id=output_file_id)),
        files=SimpleNamespace(
            content=lambda _id: SimpleNamespace(text=body)),
    )
    return c


def ok(custom_id, claims):
    return {"custom_id": custom_id, "error": None,
            "response": {"status_code": 200,
                         "body": {"choices": [{"message": {"content": json.dumps({"claims": claims})}}]}}}


def test_results_are_keyed_on_custom_id_not_order():
    c = _client_with([ok("b:1", []), ok("a:0", [{"x": 1}])])
    out = c.results("batch_1")
    assert set(out) == {"a:0", "b:1"}
    assert out["a:0"]["claims"] == [{"x": 1}]


def test_errored_line_is_skipped():
    c = _client_with([{"custom_id": "a:0", "error": {"message": "boom"}, "response": None},
                      ok("b:0", [])])
    assert set(c.results("b")) == {"b:0"}


def test_non_200_line_is_skipped():
    bad = ok("a:0", [])
    bad["response"]["status_code"] = 500
    c = _client_with([bad, ok("b:0", [])])
    assert set(c.results("b")) == {"b:0"}


def test_unparseable_content_is_skipped_not_guessed_at():
    broken = {"custom_id": "a:0", "error": None,
              "response": {"status_code": 200,
                           "body": {"choices": [{"message": {"content": "not json{"}}]}}}
    c = _client_with([broken, ok("b:0", [])])
    assert set(c.results("b")) == {"b:0"}


def test_batch_with_no_output_file_yields_nothing():
    assert _client_with([], output_file_id=None).results("b") == {}


def test_blank_lines_are_ignored():
    c = _client_with([ok("a:0", [])])
    c.client.files.content = lambda _id: SimpleNamespace(text="\n\n" + json.dumps(ok("a:0", [])) + "\n\n")
    assert set(c.results("b")) == {"a:0"}
