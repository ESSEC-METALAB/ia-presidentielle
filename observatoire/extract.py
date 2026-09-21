"""Turn documents into claims.

Runs as a batch: submit at T, collect at T+2h. Batch is chosen for provenance
rather than the 50% discount — the submitted JSONL carries, per chunk, the
exact prompt, schema and pinned model, and the results JSONL carries the raw
output. Both are committed beside the claims they produced, so every published
claim can be traced to what produced it.

The provider is a configuration value. ``schema.py`` is neutral, so the same
Pydantic model drives OpenAI's strict Structured Outputs and Claude's
``output_config.format``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path
from typing import Protocol

from .prompt import prompt_hash, system_prompt, user_prompt
from .schema import Claim, Document, ExtractionResult, Status, llm_json_schema
from .transcript import locate

# ~1,700 tokens. Long documents are split because recall drops across a very
# long context and a 56-page programme would otherwise have to emit every claim
# in one response, risking truncation.
CHUNK_CHARS = 6000
# A 40-word French quote is ~250 characters; 400 ensures one is never split
# across a boundary and lost.
OVERLAP_CHARS = 400


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split on paragraph boundaries where possible, with overlap."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            brk = text.rfind("\n\n", start + size // 2, end)
            if brk == -1:
                brk = text.rfind(". ", start + size // 2, end)
            if brk != -1:
                end = brk + 1
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in out if c]


@dataclass(frozen=True)
class Request:
    custom_id: str
    document: Document
    person_name: str
    text: str

    def payload(self, model: str) -> dict:
        return {
            "custom_id": self.custom_id,
            "model": model,
            "system": system_prompt(),
            "user": user_prompt(self.person_name, self.document.title, self.text),
            "schema": llm_json_schema(),
        }


def build_requests(docs: list[Document], people: dict[str, str]) -> list[Request]:
    """One request per chunk. ``custom_id`` maps the answer back to its document."""
    out = []
    for doc in docs:
        for i, part in enumerate(chunk(doc.text)):
            out.append(Request(f"{doc.url_hash}:{i}", doc, people.get(doc.person, doc.person), part))
    return out


class BatchClient(Protocol):
    """Minimal surface both providers satisfy."""

    def submit(self, payloads: list[dict]) -> str: ...

    def poll(self, batch_id: str) -> str:
        """``pending`` | ``ready`` | ``expired`` | ``failed``"""

    def results(self, batch_id: str) -> dict[str, dict]:
        """``custom_id`` → raw provider response."""


class FakeClient:
    """Deterministic stand-in. Lets the whole pipeline be exercised, and the
    artifacts verified, without spending money or holding a key."""

    def __init__(self, answers: dict[str, dict] | None = None, status: str = "ready"):
        self.answers = answers or {}
        self.status = status
        self.submitted: list[dict] = []

    def submit(self, payloads: list[dict]) -> str:
        self.submitted = payloads
        return "batch_fake_001"

    def poll(self, batch_id: str) -> str:
        return self.status

    def results(self, batch_id: str) -> dict[str, dict]:
        return {p["custom_id"]: self.answers.get(p["custom_id"], {"claims": []})
                for p in self.submitted}


def submit(requests: list[Request], client: BatchClient, model: str,
           artifacts: Path) -> str:
    """Submit and write the request artifact. That file is the audit record."""
    artifacts.mkdir(parents=True, exist_ok=True)
    payloads = [r.payload(model) for r in requests]
    batch_id = client.submit(payloads)
    path = artifacts / f"{batch_id}.requests.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r, p in zip(requests, payloads):
            fh.write(json.dumps({
                "custom_id": r.custom_id,
                "url": r.document.url,
                "person": r.document.person,
                "model": model,
                "prompt_hash": prompt_hash(),
                "text_sha256": __import__("hashlib").sha256(r.text.encode()).hexdigest(),
                "request": p,
            }, ensure_ascii=False) + "\n")
    return batch_id


def collect(batch_id: str, requests: list[Request], client: BatchClient,
            artifacts: Path) -> list[Claim]:
    """Fetch results, write the response artifact, assemble claims.

    Batch results are retained by the provider for 29 days only, so they are
    downloaded and committed rather than linked.
    """
    raw = client.results(batch_id)
    artifacts.mkdir(parents=True, exist_ok=True)
    with (artifacts / f"{batch_id}.responses.jsonl").open("w", encoding="utf-8") as fh:
        for cid, body in raw.items():
            fh.write(json.dumps({"custom_id": cid, "response": body}, ensure_ascii=False) + "\n")

    by_id = {r.custom_id: r for r in requests}
    claims: list[Claim] = []
    for cid, body in raw.items():
        req = by_id.get(cid)
        if req is None:
            continue
        try:
            parsed = ExtractionResult.model_validate(body)
        except Exception:
            continue  # a malformed answer is dropped, never guessed at
        claims.extend(to_claims(req.document, parsed))
    return claims


def to_claims(doc: Document, result: ExtractionResult, *, party: str = "",
              verified: Date | None = None) -> list[Claim]:
    """Attach provenance the model never saw.

    The model is not asked where it read something and is not trusted to say.
    Person, tier, source URL and archive URL come from the fetch context.
    """
    out = []
    for ec in result.claims:
        timestamp = None
        if doc.cues:
            timestamp = locate([(c.t, c.line) for c in doc.cues], ec.quote_fr)
        out.append(Claim(
            **ec.model_dump(),
            person=doc.person,
            party=party,
            tier=doc.tier,
            source_url=doc.url,
            archive_url=doc.archive_url,
            timestamp_s=timestamp,
            last_verified=verified or Date.today(),
            status=Status.PENDING,
        ))
    return out
