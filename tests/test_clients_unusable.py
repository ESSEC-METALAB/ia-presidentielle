"""Why an answer could not be used.

A refusal, a truncation and a broken answer all arrived as the same ``None``.
Only one of them is the model's fault, and one of them — truncation — means
claims were silently lost because the chunk was too big.
"""
from observatoire.clients import (
    EMPTY,
    REFUSED,
    TRUNCATED,
    UNPARSEABLE,
    OpenAIBatchClient,
    unusable_reason,
)


def test_a_usable_answer_has_no_reason():
    assert unusable_reason(None, "stop", '{"claims":[]}') is None


def test_truncation_is_named_not_treated_as_a_broken_answer():
    """finish_reason 'length' means the model ran out of output tokens
    mid-JSON. The claims it had not written yet are gone."""
    assert unusable_reason(None, "length", '{"claims":[{"axis":') == TRUNCATED


def test_a_refusal_is_distinguished_from_a_failure():
    assert unusable_reason("I cannot help with that", "stop", None) == REFUSED


def test_an_empty_answer_is_named():
    assert unusable_reason(None, "stop", "") == EMPTY
    assert unusable_reason(None, "stop", None) == EMPTY


def test_refusal_outranks_everything_else():
    assert unusable_reason("refused", "length", "") == REFUSED


class _Files:
    def __init__(self, text): self.text = text
    def content(self, _): return self


class _Batches:
    def __init__(self, fid): self.output_file_id = fid
    def retrieve(self, _): return self


class _Stub(OpenAIBatchClient):
    """Exercises results() without the SDK or a key."""
    def __init__(self, rows):
        import json
        self.unusable = {}
        body = "\n".join(json.dumps(r) for r in rows)
        self.client = type("C", (), {"files": _Files(body), "batches": _Batches("f")})()


def _row(cid, content, finish="stop", refusal=None, status=200):
    return {"custom_id": cid,
            "response": {"status_code": status,
                         "body": {"choices": [{"finish_reason": finish,
                                               "message": {"content": content,
                                                           "refusal": refusal}}]}}}


def test_batch_results_records_why_each_gap_happened():
    stub = _Stub([
        _row("ok:0", '{"claims":[]}'),
        _row("cut:1", '{"claims":[{"axis":', finish="length"),
        _row("no:2", None, refusal="no"),
        _row("bad:3", "not json at all"),
        _row("http:4", '{"claims":[]}', status=500),
    ])
    out = stub.results("b")
    assert list(out) == ["ok:0"]                 # only the usable one parses
    assert stub.unusable["cut:1"] == TRUNCATED   # and the rest say why
    assert stub.unusable["no:2"] == REFUSED
    assert stub.unusable["bad:3"] == UNPARSEABLE
    assert "http:4" in stub.unusable
