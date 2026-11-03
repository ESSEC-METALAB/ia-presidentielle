"""Annotator backed by any LLMClient: Mistral, the fake, or a recorded batch."""

import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, ValidationError

from observatoire.adapters.llm.prompt_template import PromptTemplate
from observatoire.domain.annotation import (
    AnnotationContext,
    ResponseSchema,
    StatementDraft,
)
from observatoire.domain.errors import MalformedAnnotationError
from observatoire.domain.models import Segment
from observatoire.domain.ports import LLMClient


class AnnotationAnswer(BaseModel):
    """The response contract, shared by every provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statements: tuple[StatementDraft, ...]


def response_schema(dimension_ids: Sequence[str]) -> ResponseSchema:
    """The answer's JSON Schema, with the dimension restricted to the taxonomy's ids."""
    schema = AnnotationAnswer.model_json_schema()
    schema["$defs"]["StatementDraft"]["properties"]["dimension"]["enum"] = list(dimension_ids)
    return ResponseSchema(name="annotations", json_schema=json.dumps(schema, ensure_ascii=False))


class LLMAnnotator:
    def __init__(
        self, client: LLMClient, template: PromptTemplate, dimension_ids: Sequence[str]
    ) -> None:
        self._client = client
        self._template = template
        self._schema = response_schema(dimension_ids)

    @property
    def version(self) -> str:
        return f"{self._client.model}+{self._template.version}"

    def annotate(self, segment: Segment, context: AnnotationContext) -> list[StatementDraft]:
        prompt = self._template.render(segment.text, context)
        response = self._client.complete(prompt, self._schema)
        try:
            answer = AnnotationAnswer.model_validate_json(response.content)
        except ValidationError as error:
            raise MalformedAnnotationError(
                f"{segment.id}: {error.error_count()} error(s)"
            ) from error
        return list(answer.statements)
