"""LLM adapters, offline: the prompt, the annotator, Mistral over a mock transport,
the recorded batch, and usage accounting. No network, no key."""

import json
from pathlib import Path

import httpx
import pytest

from observatoire.adapters.llm.fake_llm_client import EMPTY_ANSWER, FakeLLMClient
from observatoire.adapters.llm.llm_annotator import LLMAnnotator, response_schema
from observatoire.adapters.llm.mistral_client import API_URL, MistralClient
from observatoire.adapters.llm.prompt_template import PromptTemplate, fingerprint
from observatoire.adapters.llm.recorded_llm_client import (
    BatchRequestWriter,
    RecordedLLMClient,
    load_answers,
)
from observatoire.domain.annotation import Dimension, Prompt
from observatoire.domain.errors import (
    AnnotationUnavailableError,
    ConfigurationError,
    MalformedAnnotationError,
)
from observatoire.observability.usage_tracker import UsageRecordingClient
from support import FrozenClock, InMemoryStore, context, segment

DIMENSIONS = (
    Dimension(
        id="regulation",
        label_fr="Régulation",
        label_en="Regulation",
        definition_fr="Règles.",
        definition_en="Rules,\n  bans.",
    ),
)
TEMPLATE = PromptTemplate("classify_dimension.v1", DIMENSIONS)
SCHEMA = response_schema(["regulation"])
PASSAGE = "Nous créerons une autorité de contrôle de l'IA."
ANSWER = json.dumps(
    {
        "statements": [
            {
                "dimension": "regulation",
                "quote": "une autorité de contrôle",
                "summary_fr": "Propose une autorité.",
                "summary_en": "Proposes an authority.",
                "context_fr": "Texte fictif.",
                "context_en": "Fictional text.",
                "gloss_en": "an oversight authority",
            }
        ]
    }
)


def _prompt() -> Prompt:
    return TEMPLATE.render(PASSAGE, context())


def test_the_prompt_lists_the_dimensions_and_never_sends_the_file_comment() -> None:
    prompt = _prompt()

    assert "- `regulation` (Regulation): Rules, bans." in prompt.system
    assert "<!--" not in prompt.system
    assert prompt.user.endswith(PASSAGE)
    assert "Person: Camille Exemple (Parti Exemple)" in prompt.user


def test_the_prompt_version_changes_with_the_taxonomy() -> None:
    other = PromptTemplate("classify_dimension.v1", (DIMENSIONS[0].model_copy(update={"id": "x"}),))

    assert TEMPLATE.version.startswith("classify_dimension.v1@")
    assert other.version != TEMPLATE.version


def test_the_response_schema_restricts_dimensions_to_the_taxonomy() -> None:
    schema = json.loads(SCHEMA.json_schema)

    assert schema["$defs"]["StatementDraft"]["properties"]["dimension"]["enum"] == ["regulation"]
    assert schema["$defs"]["StatementDraft"]["additionalProperties"] is False


def test_the_annotator_returns_the_proposals_of_a_valid_answer() -> None:
    annotator = LLMAnnotator(FakeLLMClient({PASSAGE: ANSWER}), TEMPLATE, ["regulation"])

    (proposal,) = annotator.annotate(segment(PASSAGE), context())

    assert proposal.quote == "une autorité de contrôle"
    assert annotator.version == f"fake+{TEMPLATE.version}"


def test_the_fake_answers_nothing_by_default() -> None:
    annotator = LLMAnnotator(FakeLLMClient(), TEMPLATE, ["regulation"])

    assert annotator.annotate(segment(PASSAGE), context()) == []


@pytest.mark.parametrize(
    "content", ["not json", '{"statements": [{"quote": "x"}]}', '{"statements": [], "who": 1}']
)
def test_an_answer_outside_the_schema_is_malformed(content: str) -> None:
    annotator = LLMAnnotator(FakeLLMClient({PASSAGE: content}), TEMPLATE, ["regulation"])

    with pytest.raises(MalformedAnnotationError):
        annotator.annotate(segment(PASSAGE), context())


def _mistral(handler: httpx.MockTransport) -> MistralClient:
    return MistralClient(httpx.Client(transport=handler), api_key="test-key", model="m-test")


def test_mistral_sends_a_strict_json_schema_request_and_reads_usage() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {
            "model": "m-test-2611",
            "choices": [{"message": {"role": "assistant", "content": ANSWER}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        }
        return httpx.Response(200, json=body)

    response = _mistral(httpx.MockTransport(answer)).complete(_prompt(), SCHEMA)

    (request,) = seen
    sent = json.loads(request.content)
    assert str(request.url) == API_URL
    assert request.headers["Authorization"] == "Bearer test-key"
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert (response.content, response.model) == (ANSWER, "m-test-2611")
    assert (response.input_tokens, response.output_tokens) == (120, 30)


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(429, json={"message": "rate limited"}),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0},
            },
        ),
    ],
)
def test_mistral_without_a_usable_answer_leaves_the_passage_pending(reply: httpx.Response) -> None:
    client = _mistral(httpx.MockTransport(lambda request: reply))

    with pytest.raises(AnnotationUnavailableError):
        client.complete(_prompt(), SCHEMA)


def test_mistral_out_of_reach_leaves_the_passage_pending() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(AnnotationUnavailableError):
        _mistral(httpx.MockTransport(unreachable)).complete(_prompt(), SCHEMA)


def _recording(path: Path, *lines: dict[str, object]) -> Path:
    path.write_text("".join(json.dumps(line) + "\n" for line in lines) + "\n", encoding="utf-8")
    return path


def test_a_recorded_answer_is_replayed_for_the_exact_same_request(tmp_path: Path) -> None:
    file = _recording(
        tmp_path / "answers.jsonl",
        {"custom_id": fingerprint(_prompt()), "model": "draft", "content": ANSWER},
    )
    client = RecordedLLMClient(load_answers(file))

    response = client.complete(_prompt(), SCHEMA)

    assert (client.model, response.content) == ("draft", ANSWER)


def test_a_changed_request_has_no_recorded_answer(tmp_path: Path) -> None:
    file = _recording(tmp_path / "a.jsonl", {"custom_id": "other", "model": "draft", "content": ""})

    with pytest.raises(AnnotationUnavailableError):
        RecordedLLMClient(load_answers(file)).complete(_prompt(), SCHEMA)


def test_a_recording_mixing_models_is_refused(tmp_path: Path) -> None:
    file = _recording(
        tmp_path / "a.jsonl",
        {"custom_id": "1", "model": "a", "content": ""},
        {"custom_id": "2", "model": "b", "content": ""},
    )

    with pytest.raises(ConfigurationError):
        RecordedLLMClient(load_answers(file))


def test_an_unreadable_recording_line_names_its_line(tmp_path: Path) -> None:
    file = tmp_path / "a.jsonl"
    file.write_text('{"custom_id": "1"}\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"a\.jsonl:1"):
        load_answers(file)


def test_an_empty_recording_answers_nothing() -> None:
    assert RecordedLLMClient({}).model == "recorded"


def test_the_batch_writer_records_each_request_once_and_defers_it() -> None:
    writer = BatchRequestWriter("m-test")

    for _ in range(2):
        with pytest.raises(AnnotationUnavailableError):
            writer.complete(_prompt(), SCHEMA)

    (line,) = writer.lines()
    request = json.loads(line)
    assert request["custom_id"] == fingerprint(_prompt())
    assert request["body"]["model"] == writer.model == "m-test"


def test_every_answered_call_is_counted() -> None:
    tracker = InMemoryStore()
    client = UsageRecordingClient(FakeLLMClient(), tracker, FrozenClock(), "annotate")

    response = client.complete(_prompt(), SCHEMA)

    (record,) = tracker.usage
    assert response.content == EMPTY_ANSWER
    assert (record.step, record.model, client.model) == ("annotate", "fake", "fake")
    assert record.input_tokens > 0
