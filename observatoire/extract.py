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
            name = people.get(doc.person, doc.person)
            out.append(Request(f"{doc.url_hash}:{i}", doc, name, part))
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


REQUESTS_SUFFIX = ".requests.jsonl"
RESPONSES_SUFFIX = ".responses.jsonl"
# An expired or failed batch is renamed to this. The file stays — it is still
# an audit record — but it counts as neither submitted nor pending, so the
# chunks inside it are picked up again by the next submit. That is the
# "retry expired custom_ids" rule, kept without a second place to store state.
EXPIRED_SUFFIX = ".expired.jsonl"


def submitted_ids(artifacts: Path) -> set[str]:
    """Every ``custom_id`` already sent in some batch.

    Keyed on what was *asked*, not on what came back: a chunk that answered
    ``[]`` has been extracted correctly — that is the expected answer for most
    documents — and must not be paid for again tomorrow.
    """
    out: set[str] = set()
    for path in artifacts.glob(f"*{REQUESTS_SUFFIX}"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.add(json.loads(line)["custom_id"])
    return out


def pending_batches(artifacts: Path) -> list[str]:
    """Batches submitted but not yet collected — a request file with no
    response file beside it. No batch-id registry is needed; the artifacts the
    provenance rules already require are the registry."""
    ids = [p.name[: -len(REQUESTS_SUFFIX)] for p in artifacts.glob(f"*{REQUESTS_SUFFIX}")]
    return sorted(i for i in ids if not (artifacts / f"{i}{RESPONSES_SUFFIX}").exists())


def submit(requests: list[Request], client: BatchClient, model: str,
           artifacts: Path) -> str:
    """Submit and write the request artifact. That file is the audit record."""
    artifacts.mkdir(parents=True, exist_ok=True)
    payloads = [r.payload(model) for r in requests]
    batch_id = client.submit(payloads)
    path = artifacts / f"{batch_id}{REQUESTS_SUFFIX}"
    with path.open("w", encoding="utf-8") as fh:
        for r, p in zip(requests, payloads, strict=True):
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
            artifacts: Path, parties: dict[str, str] | None = None) -> list[Claim]:
    """Fetch results, write the response artifact, assemble claims.

    Batch results are retained by the provider for 29 days only, so they are
    downloaded and committed rather than linked.

    ``parties`` maps a person slug to their party, from ``sources.yaml``. Like
    every other provenance field it comes from the fetch context, never from
    the model.
    """
    raw = client.results(batch_id)
    artifacts.mkdir(parents=True, exist_ok=True)
    with (artifacts / f"{batch_id}{RESPONSES_SUFFIX}").open("w", encoding="utf-8") as fh:
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
        claims.extend(to_claims(req.document, parsed,
                                party=(parties or {}).get(req.document.person, "")))
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
            # Carried from the fetch context like every other provenance
            # field. True only where the source names its own speaker, which
            # today means the official parliamentary record; everything else
            # stays a default for an editor to confirm, and the site marks it
            # with an asterisk.
            tier_confirmed=doc.tier_confirmed,
            source_url=doc.url,
            archive_url=doc.archive_url,
            timestamp_s=timestamp,
            last_verified=verified or Date.today(),
            status=Status.PENDING,
        ))
    return out


# The docs list no dated snapshot for this model — checked 2026-09-21, the
# models page offers `gpt-5.6-luna` and nothing else — so there is no pin to
# take. The defence against an alias moving underneath us is therefore the
# artifact: every request line records the model id, the prompt hash and the
# SHA-256 of the text, so a changed answer can at least be attributed. Pin
# this the day a dated snapshot is published.
MODEL = "gpt-5.6-luna"


if __name__ == "__main__":
    import argparse

    import yaml

    from .store import Store, merge_claims

    ap = argparse.ArgumentParser(
        description="Extract claims from fetched documents, as a batch.")
    ap.add_argument("command", choices=["submit", "collect"])
    ap.add_argument("--db", default="data/observatoire.db")
    ap.add_argument("--sources", default="sources.yaml")
    ap.add_argument("--claims", default="data/claims.json")
    ap.add_argument("--artifacts", default="data/artifacts", type=Path)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--dry-run", action="store_true",
                    help="run against the fake client: exercises the whole path "
                         "and writes real artifacts, but spends nothing")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.sources).read_text(encoding="utf-8"))
    names = {p["slug"]: p["name"] for p in cfg["people"]}
    parties = {p["slug"]: p.get("party", "") for p in cfg["people"]}

    def open_client():
        """Built only once there is actually something to send.

        Constructing it eagerly would mean a morning with nothing outstanding
        still needed a key, so the daily run would fail on a day it had no
        work to do — the least useful moment to demand a credential.
        """
        if args.dry_run:
            return FakeClient()
        from .clients import OpenAIBatchClient
        return OpenAIBatchClient()

    store = Store(args.db)
    requests = build_requests(store.documents(), names)

    if args.command == "submit":
        already = submitted_ids(args.artifacts)
        todo = [r for r in requests if r.custom_id not in already]
        if not todo:
            print(f"nothing new to extract ({len(requests)} chunks already submitted)")
        else:
            batch_id = submit(todo, open_client(), args.model, args.artifacts)
            print(f"submitted {len(todo)} chunks as {batch_id} ({args.model})")
    else:
        outstanding = pending_batches(args.artifacts)
        if not outstanding:
            print("no batch outstanding")
        client = open_client() if outstanding else None
        for batch_id in outstanding:
            status = client.poll(batch_id)
            if status == "pending":
                print(f"{batch_id} still running")
                continue
            if status in ("expired", "failed"):
                # Leave the record, drop it from both sets, and the next
                # submit picks its chunks up again.
                (args.artifacts / f"{batch_id}{REQUESTS_SUFFIX}").rename(
                    args.artifacts / f"{batch_id}{EXPIRED_SUFFIX}")
                print(f"{batch_id} {status} — its chunks return to the queue")
                continue
            claims = collect(batch_id, requests, client, args.artifacts, parties)

            # A batch can complete with every single line errored — an account
            # over its billing limit does exactly this — and `results` skips
            # errored lines, so that arrives here as zero results. A document
            # that legitimately holds no AI position still comes back as
            # `{"claims": []}`, which IS a result. So no results at all, from
            # a batch that was sent requests, means nothing was extracted
            # rather than nothing was found. Treated as success it would mark
            # every chunk as done and they would never be asked again.
            responses = args.artifacts / f"{batch_id}{RESPONSES_SUFFIX}"
            if responses.exists() and responses.stat().st_size == 0:
                responses.unlink()
                (args.artifacts / f"{batch_id}{REQUESTS_SUFFIX}").rename(
                    args.artifacts / f"{batch_id}{EXPIRED_SUFFIX}")
                print(f"{batch_id} answered nothing at all — every line failed. "
                      "Its chunks return to the queue.")
                continue

            for claim in claims:
                store.add_claim(claim)
            store.commit()
            added = merge_claims(args.claims, claims)
            print(f"{batch_id}: {len(claims)} claims, {added} new in {args.claims}")

    store.close()
