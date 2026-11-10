"""Framer backed by any LLMClient: says whether a statement presents AI as an opportunity
or a threat, from the versioned prompt `frame_statement.v1.md`."""

import hashlib
import json

from pydantic import ValidationError

from observatoire.adapters.llm.prompt_template import _LEADING_COMMENT, PROMPTS_DIR
from observatoire.domain.annotation import FramingDraft, Prompt, ResponseSchema
from observatoire.domain.errors import MalformedAnnotationError
from observatoire.domain.ports import LLMClient
from observatoire.domain.register import RegisterEntry

PROMPT = "frame_statement.v1"


class LLMFramer:
    def __init__(self, client: LLMClient, name: str = PROMPT) -> None:
        raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        self._client = client
        self._system = _LEADING_COMMENT.sub("", raw).strip()
        digest = hashlib.sha256(self._system.encode()).hexdigest()[:12]
        self._version = f"{client.model}+{name}@{digest}"
        schema = FramingDraft.model_json_schema()
        self._schema = ResponseSchema(name="framing", json_schema=json.dumps(schema))

    @property
    def version(self) -> str:
        """Model and prompt: a new one frames every statement again."""
        return self._version

    def frame(self, entry: RegisterEntry, speaker: str, axis_label: str) -> FramingDraft:
        statement = entry.annotation
        user = (
            f"Person: {speaker}\n"
            f"Axis: {axis_label}\n"
            f"Summary: {statement.summary_fr}\n"
            f"Context: {statement.context_fr}\n\n---\n\nQuote: {statement.quote}"
        )
        prompt = Prompt(version=self._version, system=self._system, user=user)
        response = self._client.complete(prompt, self._schema)
        try:
            return FramingDraft.model_validate_json(response.content)
        except ValidationError as error:
            raise MalformedAnnotationError(f"{statement.id}: framing unreadable") from error
