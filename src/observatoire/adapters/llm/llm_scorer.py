"""Scorer backed by any LLMClient: places a statement on the scales of config/scoring.yaml,
from the versioned prompt `score_statement.v1.md`."""

import hashlib
import json
from collections.abc import Sequence

from pydantic import ValidationError

from observatoire.adapters.llm.prompt_template import _LEADING_COMMENT, PROMPTS_DIR
from observatoire.domain.annotation import Prompt, ResponseSchema
from observatoire.domain.errors import MalformedAnnotationError
from observatoire.domain.ports import LLMClient
from observatoire.domain.register import RegisterEntry
from observatoire.domain.scoring import ScoreDraft, ScoreScale

PROMPT = "score_statement.v1"


def _scale_text(scale: ScoreScale) -> str:
    lines = [f"### `{scale.id}`: {scale.label_en} (1 = {scale.low_en}, 5 = {scale.high_en})"]
    lines.append(" ".join(scale.question_en.split()))
    if scale.anchors:
        lines.append("Axis anchors:")
        for axis, marks in scale.anchors.items():
            detail = "; ".join(f"{level} = {text}" for level, text in sorted(marks.items()))
            lines.append(f"- `{axis}`: {detail}")
    return "\n".join(lines)


class LLMScorer:
    def __init__(self, client: LLMClient, scales: Sequence[ScoreScale], name: str = PROMPT) -> None:
        raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        listed = "\n\n".join(_scale_text(scale) for scale in scales)
        self._client = client
        self._system = _LEADING_COMMENT.sub("", raw).replace("{scales}", listed).strip()
        digest = hashlib.sha256(self._system.encode()).hexdigest()[:12]
        self._version = f"{client.model}+{name}@{digest}"
        schema = ScoreDraft.model_json_schema()
        schema["$defs"]["ScaleDraft"]["properties"]["scale"]["enum"] = [s.id for s in scales]
        self._schema = ResponseSchema(name="scores", json_schema=json.dumps(schema))

    @property
    def version(self) -> str:
        """Model, prompt and scales: any change scores every statement again."""
        return self._version

    def score(self, entry: RegisterEntry, speaker: str, axis: str) -> ScoreDraft:
        statement = entry.annotation
        user = (
            f"Person: {speaker}\n"
            f"Axis: `{statement.dimension}` ({axis})\n"
            f"Summary: {statement.summary_fr}\n"
            f"Context: {statement.context_fr}\n\n---\n\nQuote: {statement.quote}"
        )
        prompt = Prompt(version=self._version, system=self._system, user=user)
        response = self._client.complete(prompt, self._schema)
        try:
            return ScoreDraft.model_validate_json(response.content)
        except ValidationError as error:
            raise MalformedAnnotationError(f"{statement.id}: scores unreadable") from error
