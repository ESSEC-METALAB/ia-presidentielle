"""Provider clients.

Production extraction runs as a batch — for provenance as much as for the 50%
discount. The gold-set comparison runs synchronously instead: fifty documents
do not need a batch, and waiting hours per candidate model would make the
comparison tedious enough to skip.

Both paths build their request from :func:`request_body`, so the comparison
cannot quietly measure a different prompt or a looser schema than production
sends.

**The provider is a configuration value.** Chat completions are the same wire
format at every provider we use: Mistral documents its endpoint as
OpenAI-compatible, and its ``response_format`` serialises byte-identically,
``strict`` included. So one SDK — the OpenAI one, pointed at a different
``base_url`` — and one :func:`request_body` cover all of them, and
``schema.py`` never learns a provider exists.

Only the **batch transport** genuinely differs, because the two APIs are not
the same service: OpenAI puts the endpoint on each JSONL line and Mistral puts
it on the job. That is the whole of the per-provider code.

Request and response shapes here were read from the provider's current API
documentation and from the ``mistralai`` SDK's own generated types, not
recalled.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass

# OpenAI batch status values, mapped onto the three outcomes the pipeline
# actually branches on.
_OPENAI_STATUS = {
    "validating": "pending", "in_progress": "pending", "finalizing": "pending",
    "completed": "ready",
    "expired": "expired",
    "failed": "failed", "cancelled": "failed", "cancelling": "failed",
}


# Why an answer could not be used. These arrived as the same ``None`` before,
# which hid the one that matters: a **truncated** answer means the model ran out
# of output tokens mid-JSON and the claims it had not written yet are simply
# gone. Chunking at CHUNK_CHARS exists to prevent exactly that, so a truncation
# is a measurement about the chunk size, not a transient error — and it is
# indistinguishable from a broken answer unless finish_reason is read.
REFUSED = "refused"
TRUNCATED = "truncated"
EMPTY = "empty"
UNPARSEABLE = "unparseable"


@dataclass(frozen=True)
class Provider:
    """Where a model lives, and which batch dialect it speaks."""

    name: str
    base_url: str | None
    """``None`` leaves the SDK on its own default, which is OpenAI's."""
    key_env: str | None
    """``None`` for a local server, which takes no key."""
    batch: str
    """``openai``, ``mistral`` or ``sync`` — see :func:`batch_client`."""
    default_model: str


PROVIDERS = {
    p.name: p for p in (
        Provider("openai", None, "OPENAI_API_KEY", "openai", "gpt-5.6-luna"),
        # A French model for a French election observatory, and one several of
        # the monitored candidates name by name — which is a reason to say so
        # in the methodology, not a reason to avoid it.
        Provider("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY",
                 "mistral", "mistral-large-latest"),
        # A model on this machine, through Ollama's OpenAI-compatible endpoint,
        # which honours `response_format` with `strict` json_schema (checked
        # 2026-11-13 against Ollama 0.40.13). The default is deliberately tiny:
        # it proves the loop, not the extraction. Pass --model for a larger one.
        Provider("ollama", "http://localhost:11434/v1", None, "sync", "qwen3:0.6b"),
    )
}


def sdk(provider: Provider, api_key: str | None = None):
    """The OpenAI SDK, pointed at whichever provider this is.

    Built lazily so the module imports without a key, and raises by name so a
    missing credential says *which* one rather than failing inside the SDK.
    """
    from openai import OpenAI

    # A local server ignores the key, but the SDK refuses to start without one.
    key = api_key or (os.environ.get(provider.key_env) if provider.key_env else "local")
    if not key:
        raise RuntimeError(
            f"{provider.key_env} is not set — needed to reach {provider.name}")
    return OpenAI(api_key=key, base_url=provider.base_url)


def unusable_reason(refusal, finish_reason, content) -> str | None:
    """``None`` if the answer can be used, otherwise why it cannot.

    Takes primitives rather than a response object: the synchronous path holds
    SDK objects and the batch path holds parsed JSONL, and one rule has to
    cover both or they drift.
    """
    if refusal:
        return REFUSED
    if finish_reason == "length":
        return TRUNCATED
    if not content:
        return EMPTY
    return None


def request_body(payload: dict) -> dict:
    """The request itself, shared by the batch and synchronous paths.

    Defined once on purpose. The gold set exists to choose a model, and a
    comparison that sent a different prompt or a looser schema than production
    sends would be measuring the wrong thing. Both callers build from here, so
    they cannot drift apart.
    """
    return {
        "model": payload["model"],
        "messages": [
            {"role": "system", "content": payload["system"]},
            {"role": "user", "content": payload["user"]},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "extraction",
                "schema": payload["schema"],
                "strict": True,
            },
        },
    }


def parse_results(raw: str) -> tuple[dict[str, dict], dict[str, str]]:
    """``(usable, unusable)`` from a batch output file.

    Shared by both dialects: the *input* line differs between providers, but
    both return an output line carrying ``custom_id`` and the chat-completions
    response the sync path would have produced. One parser means an answer
    becomes a claim by exactly the same route whoever produced it.

    Output order does not match input order, so everything is keyed on
    ``custom_id``. A line that errored or came back unparseable is skipped
    rather than guessed at; the missing chunk shows up as a gap, which is the
    honest outcome — now with the reason beside it.
    """
    out: dict[str, dict] = {}
    unusable: dict[str, str] = {}
    for row in raw.splitlines():
        if not row.strip():
            continue
        rec = json.loads(row)
        cid = rec.get("custom_id", "?")
        if rec.get("error") or rec.get("response", {}).get("status_code") != 200:
            unusable[cid] = str(rec.get("error") or
                                rec.get("response", {}).get("status_code"))
            continue
        try:
            choice = rec["response"]["body"]["choices"][0]
            content = choice["message"].get("content")
            reason = unusable_reason(choice["message"].get("refusal"),
                                     choice.get("finish_reason"), content)
            if reason:
                unusable[cid] = reason
                continue
            out[cid] = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError):
            unusable[cid] = UNPARSEABLE
    return out, unusable


class OpenAIBatchClient:
    """Batch extraction via the Chat Completions endpoint with strict
    Structured Outputs, so the schema is guaranteed rather than hoped for."""

    endpoint = "/v1/chat/completions"

    def __init__(self, api_key: str | None = None, *, completion_window: str = "24h",
                 provider: Provider | None = None):
        self.client = sdk(provider or PROVIDERS["openai"], api_key)
        self.completion_window = completion_window
        # custom_id -> why its answer could not be used. A gap in the results
        # is honest, but a gap with no reason beside it cannot be acted on.
        self.unusable: dict[str, str] = {}

    @staticmethod
    def line(payload: dict) -> dict:
        """One JSONL line of the batch input file."""
        return {
            "custom_id": payload["custom_id"],
            "method": "POST",
            "url": OpenAIBatchClient.endpoint,
            "body": request_body(payload),
        }

    def submit(self, payloads: list[dict]) -> str:
        body = "\n".join(json.dumps(self.line(p), ensure_ascii=False) for p in payloads)
        buf = io.BytesIO(body.encode("utf-8"))
        buf.name = "extraction.jsonl"
        uploaded = self.client.files.create(file=buf, purpose="batch")
        batch = self.client.batches.create(
            input_file_id=uploaded.id,
            endpoint=self.endpoint,
            completion_window=self.completion_window,
        )
        return batch.id

    def poll(self, batch_id: str) -> str:
        return _OPENAI_STATUS.get(self.client.batches.retrieve(batch_id).status, "pending")

    def results(self, batch_id: str) -> dict[str, dict]:
        """``custom_id`` → parsed extraction.

        Output order does not match input order, so everything is keyed on
        ``custom_id``. A line that errored or came back unparseable is skipped
        rather than guessed at; the missing chunk shows up as a gap, which is
        the honest outcome.
        """
        batch = self.client.batches.retrieve(batch_id)
        if not batch.output_file_id:
            self.unusable = {}
            return {}
        # Assigned at the end: the reasons belong to *this* batch, so
        # accumulating them across calls would be wrong.
        out, self.unusable = parse_results(self.client.files.content(batch.output_file_id).text)
        return out


# Mistral's own vocabulary, mapped onto the four outcomes the pipeline
# branches on. Read from the mistralai SDK's generated BatchJobStatus.
_MISTRAL_STATUS = {
    "QUEUED": "pending", "RUNNING": "pending",
    "SUCCESS": "ready",
    "TIMEOUT_EXCEEDED": "expired",
    "FAILED": "failed", "CANCELLED": "failed", "CANCELLATION_REQUESTED": "failed",
}


class MistralBatchClient:
    """Mistral's batch API. Same request body, different transport.

    Two things differ from OpenAI and nothing else does:

    * the JSONL line is ``{custom_id, body}`` — no ``method`` or ``url``,
      because the endpoint is set once on the job rather than per line;
    * the job is created at ``/v1/batch/jobs`` with ``input_files`` (plural)
      and carries ``model`` itself.

    Driven through the OpenAI SDK's raw ``post``/``get`` rather than the
    ``mistralai`` package: the request body is already identical, so pulling in
    a second SDK and eighteen transitive packages would buy four REST calls.
    Paths and status values were read from the ``mistralai`` SDK's generated
    types, so they are the real ones.
    """

    endpoint = "/v1/chat/completions"

    def __init__(self, api_key: str | None = None, *, provider: Provider | None = None):
        self.client = sdk(provider or PROVIDERS["mistral"], api_key)
        self.unusable: dict[str, str] = {}

    @staticmethod
    def line(payload: dict) -> dict:
        """One JSONL line. The endpoint lives on the job, not here."""
        return {"custom_id": payload["custom_id"], "body": request_body(payload)}

    def submit(self, payloads: list[dict]) -> str:
        body = "\n".join(json.dumps(self.line(p), ensure_ascii=False) for p in payloads)
        uploaded = self.client.post(
            "/files",
            body={"purpose": "batch"},
            files=[("file", ("extraction.jsonl", io.BytesIO(body.encode("utf-8")),
                             "application/jsonl"))],
            cast_to=object,
        )
        job = self.client.post(
            "/batch/jobs",
            body={
                "input_files": [uploaded["id"]],
                # Mistral pins the model on the job. Every payload in a batch
                # carries the same one, so taking the first is not a guess.
                "model": payloads[0]["model"],
                "endpoint": self.endpoint,
            },
            cast_to=object,
        )
        return job["id"]

    def poll(self, batch_id: str) -> str:
        job = self.client.get(f"/batch/jobs/{batch_id}", cast_to=object)
        return _MISTRAL_STATUS.get(job.get("status"), "pending")

    def results(self, batch_id: str) -> dict[str, dict]:
        job = self.client.get(f"/batch/jobs/{batch_id}", cast_to=object)
        output = job.get("output_file")
        if not output:
            self.unusable = {}
            return {}
        raw = self.client.get(f"/files/{output}/content", cast_to=object)
        out, self.unusable = parse_results(raw if isinstance(raw, str) else raw.text)
        return out


def batch_client(provider: str = "openai", api_key: str | None = None):
    """The batch client for a provider, by name."""
    p = PROVIDERS[provider]
    kind = {"mistral": MistralBatchClient, "sync": SyncBatchClient}.get(p.batch, OpenAIBatchClient)
    return kind(api_key, provider=p)


class SyncClient:
    """One call, one answer, at any provider.

    Production extraction is batched, for provenance as much as for the 50%.
    The gold comparison is not: fifty documents do not need a batch, waiting
    hours per candidate model would make the comparison tedious enough to skip,
    and a synchronous call sends the identical body — see :func:`request_body`.

    Nothing here is OpenAI-specific. Chat completions are the same wire format
    at every provider we use, so changing ``provider`` is the whole of the
    change — which is what makes a Mistral-versus-OpenAI gold run a fair
    comparison rather than two different pipelines.
    """

    def __init__(self, api_key: str | None = None, *, provider: str = "openai"):
        self.provider = PROVIDERS[provider]
        self.client = sdk(self.provider, api_key)
        self.unusable: dict[str, str] = {}

    def complete(self, payload: dict) -> dict | None:
        """The parsed extraction, or ``None`` if the answer was unusable.

        A model that returns something unparseable has failed the document,
        and that is a result worth scoring — so it is reported as a failure
        rather than smoothed into an empty extraction, which is the *correct*
        answer for most documents and would flatter the model.

        ``None`` stays the answer, because the gold set scores a failure as a
        failure. What changed is that ``unusable`` now records *why*, keyed on
        ``custom_id`` — a refusal, a truncation and a broken answer are three
        different problems and only one of them is the model's fault.
        """
        answer = self.client.chat.completions.create(**request_body(payload))
        choice = answer.choices[0]
        cid = payload.get("custom_id", "?")
        content = choice.message.content
        reason = unusable_reason(getattr(choice.message, "refusal", None),
                                 choice.finish_reason, content)
        if reason:
            self.unusable[cid] = reason
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            self.unusable[cid] = UNPARSEABLE
            return None


class SyncBatchClient:
    """The batch surface over one synchronous call per chunk, for a server with
    no batch API — a local model.

    Answers live in memory, so submit and collect must run in one process; the
    extract command does that for a ``sync`` provider. A ``local-`` batch left
    behind by a process that died is reported failed, so its chunks return to
    the queue. Any other id belongs to another provider and is left alone:
    reporting it failed would discard a batch this client knows nothing about.
    """

    def __init__(self, api_key: str | None = None, *, provider: Provider):
        self.sync = SyncClient(api_key, provider=provider.name)
        self.batch_id: str | None = None
        self.answers: dict[str, dict] = {}

    @property
    def unusable(self) -> dict[str, str]:
        return self.sync.unusable

    def submit(self, payloads: list[dict]) -> str:
        for p in payloads:
            answer = self.sync.complete(p)
            if answer is not None:
                self.answers[p["custom_id"]] = answer
        ids = "\n".join(p["custom_id"] for p in payloads)
        self.batch_id = "local-" + hashlib.sha256(ids.encode()).hexdigest()[:16]
        return self.batch_id

    def poll(self, batch_id: str) -> str:
        if batch_id == self.batch_id:
            return "ready"
        return "failed" if batch_id.startswith("local-") else "pending"

    def results(self, batch_id: str) -> dict[str, dict]:
        return self.answers if batch_id == self.batch_id else {}
