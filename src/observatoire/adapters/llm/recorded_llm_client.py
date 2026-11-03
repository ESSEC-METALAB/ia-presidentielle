"""LLM batches in two halves: write the requests, later replay the recorded answers.

`BatchRequestWriter` stands in for a model during a run: it records each exact request
and defers it, so nothing is stored. Whoever answers the batch (Mistral's batch API, or
an annotator working offline) writes one answer per request id. `RecordedLLMClient` then
replays those answers through the same annotator, gates and store as a live call: the
recording is the provenance of every annotation it produces.

Answer file, one JSON object per line:
  {"custom_id": "<fingerprint>", "model": "...", "content": "<JSON answer>",
   "input_tokens": 0, "output_tokens": 0}
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from observatoire.adapters.llm.mistral_client import request_body
from observatoire.adapters.llm.prompt_template import fingerprint
from observatoire.domain.annotation import LLMResponse, Prompt, ResponseSchema
from observatoire.domain.errors import AnnotationUnavailableError, ConfigurationError


class RecordedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    custom_id: str
    model: str = Field(min_length=1)
    content: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


def load_answers(path: Path) -> dict[str, RecordedAnswer]:
    answers: dict[str, RecordedAnswer] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            answer = RecordedAnswer.model_validate_json(line)
        except ValidationError as error:
            raise ConfigurationError(f"{path}:{number}: {error}") from error
        answers[answer.custom_id] = answer
    return answers


class RecordedLLMClient:
    def __init__(self, answers: dict[str, RecordedAnswer]) -> None:
        models = {answer.model for answer in answers.values()}
        if len(models) > 1:
            raise ConfigurationError(f"one model per recording, found: {sorted(models)}")
        self._answers = answers
        self._model = models.pop() if models else "recorded"

    @property
    def model(self) -> str:
        return self._model

    def complete(self, prompt: Prompt, schema: ResponseSchema) -> LLMResponse:
        answer = self._answers.get(fingerprint(prompt))
        if answer is None:
            # Not in the batch, or the prompt, taxonomy or passage changed since.
            raise AnnotationUnavailableError("no recorded answer for this exact request")
        return LLMResponse(
            model=answer.model,
            content=answer.content,
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
        )


class BatchRequestWriter:
    """Collects requests instead of answering them; `lines()` is the batch file."""

    def __init__(self, model: str) -> None:
        self._model = model
        self._lines: dict[str, str] = {}

    @property
    def model(self) -> str:
        return self._model

    def complete(self, prompt: Prompt, schema: ResponseSchema) -> LLMResponse:
        custom_id = fingerprint(prompt)
        body = request_body(self._model, prompt, schema)
        self._lines[custom_id] = json.dumps(
            {"custom_id": custom_id, "body": body}, ensure_ascii=False
        )
        raise AnnotationUnavailableError("deferred to a batch")

    def lines(self) -> list[str]:
        return list(self._lines.values())
