"""Turn attributor backed by any LLMClient: splits the captions of an interview into
speaking turns, from the versioned prompt `attribute_turns.v1.md`."""

import hashlib
import json
from collections.abc import Sequence

from pydantic import ValidationError

from observatoire.adapters.llm.prompt_template import _LEADING_COMMENT, PROMPTS_DIR
from observatoire.domain.annotation import Prompt, ResponseSchema
from observatoire.domain.errors import MalformedAnnotationError
from observatoire.domain.models import SpeakingTurn, SpeakingTurns
from observatoire.domain.ports import LLMClient

PROMPT = "attribute_turns.v1"


class LLMTurnAttributor:
    def __init__(self, client: LLMClient, name: str = PROMPT) -> None:
        raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        self._client = client
        self._system = _LEADING_COMMENT.sub("", raw).strip()
        digest = hashlib.sha256(self._system.encode()).hexdigest()[:12]
        self._version = f"{client.model}+{name}@{digest}"
        schema = SpeakingTurns.model_json_schema()
        self._schema = ResponseSchema(name="turns", json_schema=json.dumps(schema))

    def attribute(self, speaker: str, title: str, lines: Sequence[str]) -> list[SpeakingTurn]:
        numbered = "\n".join(f"[{i}] {line}" for i, line in enumerate(lines))
        user = f"Candidate (the guest): {speaker}\nVideo title: {title}\n\n---\n\n{numbered}"
        prompt = Prompt(version=self._version, system=self._system, user=user)
        response = self._client.complete(prompt, self._schema)
        try:
            return list(SpeakingTurns.model_validate_json(response.content).turns)
        except ValidationError as error:
            raise MalformedAnnotationError(f"{title}: speaking turns unreadable") from error
