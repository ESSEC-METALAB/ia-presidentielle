"""Versioned prompt files, rendered with the taxonomy, and fingerprints of rendered prompts."""

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from observatoire.domain.annotation import AnnotationContext, Dimension, Prompt
from observatoire.domain.models import TrustLevel

PROMPTS_DIR = Path(__file__).parent / "prompts"
_LEADING_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)
_TRUST_LABELS = {
    TrustLevel.OWN_WORDS: "the person's own words",
    TrustLevel.PARTY: "the party or campaign team, by default; it may carry the person's words",
    TrustLevel.PRESS: "press",
    TrustLevel.THIRD_PARTY: "third party",
}


def fingerprint(prompt: Prompt) -> str:
    """Identifies one exact request: the key under which its answer is recorded."""
    digest = hashlib.sha256(f"{prompt.system}\x00{prompt.user}".encode())
    return digest.hexdigest()[:24]


class PromptTemplate:
    """`classify_dimension.v1.md` -> system prompt with the dimensions written in."""

    def __init__(self, name: str, dimensions: Sequence[Dimension]) -> None:
        raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        listed = "\n".join(
            f"- `{d.id}` ({d.label_en}): {' '.join(d.definition_en.split())}" for d in dimensions
        )
        self._system = _LEADING_COMMENT.sub("", raw).replace("{dimensions}", listed).strip()
        digest = hashlib.sha256(self._system.encode()).hexdigest()[:12]
        self._version = f"{name}@{digest}"

    @property
    def version(self) -> str:
        """File name and content hash: a changed prompt or taxonomy is a new version."""
        return self._version

    def render(self, passage: str, context: AnnotationContext) -> Prompt:
        published = context.published_on.isoformat() if context.published_on else "not stated"
        user = (
            f"Person: {context.speaker} ({context.party})\n"
            f"Published by: {context.source_label} ({_TRUST_LABELS[context.trust_level]})\n"
            f"Document title: {context.title or '(untitled)'}\n"
            f"Date: {published}\n\n---\n\n{passage}"
        )
        return Prompt(version=self._version, system=self._system, user=user)
