"""Deterministic LLMClient: the default, offline, and the one every test uses.

It answers `{"statements": []}` unless told otherwise: the correct answer for most
passages, so the fake exercises the whole path without inventing anything.
"""

from collections.abc import Mapping

from observatoire.domain.annotation import LLMResponse, Prompt, ResponseSchema

EMPTY_ANSWER = '{"statements": []}'
_CHARS_PER_TOKEN = 4  # a rough count, so `usage` has something to add up


class FakeLLMClient:
    def __init__(self, answers: Mapping[str, str] | None = None, *, model: str = "fake") -> None:
        """`answers`: passage substring -> JSON answer, for tests that need a statement."""
        self._answers = dict(answers or {})
        self._model = model
        self.prompts: list[Prompt] = []

    @property
    def model(self) -> str:
        return self._model

    def complete(self, prompt: Prompt, schema: ResponseSchema) -> LLMResponse:
        self.prompts.append(prompt)
        content = next(
            (answer for key, answer in self._answers.items() if key in prompt.user), EMPTY_ANSWER
        )
        return LLMResponse(
            model=self._model,
            content=content,
            input_tokens=(len(prompt.system) + len(prompt.user)) // _CHARS_PER_TOKEN,
            output_tokens=len(content) // _CHARS_PER_TOKEN,
        )
