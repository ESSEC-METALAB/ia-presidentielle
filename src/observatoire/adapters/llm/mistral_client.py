"""LLMClient for the Mistral chat completions API, with custom structured outputs.

Request shape from Mistral's documentation, "Custom Structured Outputs"
(docs.mistral.ai, studio-api/conversations/structured-output/custom) and the Chat
Completion API reference: `response_format = {"type": "json_schema", "json_schema":
{"name", "schema", "strict"}}`, answer in `choices[0].message.content`, token counts in
`usage.prompt_tokens` / `usage.completion_tokens`.

First exercised against the live API on 2026-11-04 (mistral-large-4-0), which showed two
things the documentation had not: greedy sampling (`temperature: 0`) is refused unless
`top_p` is 1, and a reasoning model answers with a list of chunks, its reasoning
("thinking") then the answer ("text"). Only the text chunks are the answer; the
reasoning is neither returned nor logged.
"""

import json

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from observatoire.domain.annotation import LLMResponse, Prompt, ResponseSchema
from observatoire.domain.errors import AnnotationUnavailableError

API_URL = "https://api.mistral.ai/v1/chat/completions"


class _Chunk(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    text: str = ""


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str | list[_Chunk]

    @property
    def answer(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "".join(chunk.text for chunk in self.content if chunk.type == "text")


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: _Message


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int
    completion_tokens: int


class _Completion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    choices: list[_Choice]
    usage: _Usage


def request_body(model: str, prompt: Prompt, schema: ResponseSchema) -> dict[str, object]:
    """The JSON body of one call; also the `body` of a batch request line."""
    return {
        "model": model,
        "temperature": 0,
        "top_p": 1,
        "messages": [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema.name,
                "schema": json.loads(schema.json_schema),
                "strict": True,
            },
        },
    }


class MistralClient:
    def __init__(self, http: httpx.Client, *, api_key: str, model: str) -> None:
        self._http = http
        self._api_key = api_key
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def complete(self, prompt: Prompt, schema: ResponseSchema) -> LLMResponse:
        try:
            response = self._http.post(
                API_URL,
                json=request_body(self._model, prompt, schema),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as error:
            raise AnnotationUnavailableError(f"mistral: {type(error).__name__}") from error
        if response.is_error:
            # Rate limit, outage, bad key or bad request: the passage stays pending. The
            # body may echo the request, so only the status is reported.
            raise AnnotationUnavailableError(f"mistral: HTTP {response.status_code}")
        return _parsed(response.content)


def _parsed(content: bytes) -> LLMResponse:
    try:
        completion = _Completion.model_validate_json(content)
    except ValidationError as error:
        raise AnnotationUnavailableError("mistral: unexpected response shape") from error
    if not completion.choices:
        raise AnnotationUnavailableError("mistral: no choice in the response")
    return LLMResponse(
        model=completion.model,
        content=completion.choices[0].message.answer,
        input_tokens=completion.usage.prompt_tokens,
        output_tokens=completion.usage.completion_tokens,
    )
