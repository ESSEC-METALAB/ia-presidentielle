"""Speech check backed by any LLMClient: says whether a video transcript is the named
candidate speaking alone, from the versioned prompt `check_speech.v1.md`."""

import hashlib
import json

from pydantic import ValidationError

from observatoire.adapters.llm.prompt_template import _LEADING_COMMENT, PROMPTS_DIR
from observatoire.domain.annotation import Prompt, ResponseSchema
from observatoire.domain.errors import MalformedAnnotationError
from observatoire.domain.models import SpeechVerdict
from observatoire.domain.ports import LLMClient

PROMPT = "check_speech.v1"


class LLMSpeechCheck:
    def __init__(self, client: LLMClient, name: str = PROMPT) -> None:
        raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        self._client = client
        self._system = _LEADING_COMMENT.sub("", raw).strip()
        digest = hashlib.sha256(self._system.encode()).hexdigest()[:12]
        self._version = f"{client.model}+{name}@{digest}"
        schema = SpeechVerdict.model_json_schema()
        self._schema = ResponseSchema(name="speech_check", json_schema=json.dumps(schema))

    def check(self, speaker: str, title: str, transcript: str) -> SpeechVerdict:
        user = f"Candidate: {speaker}\nVideo title: {title}\n\n---\n\n{transcript}"
        prompt = Prompt(version=self._version, system=self._system, user=user)
        response = self._client.complete(prompt, self._schema)
        try:
            return SpeechVerdict.model_validate_json(response.content)
        except ValidationError as error:
            raise MalformedAnnotationError(f"{title}: speech check unreadable") from error
