"""Provider clients.

Production extraction runs as a batch — for provenance as much as for the 50%
discount. The gold-set comparison runs synchronously instead: fifty documents
do not need a batch, and waiting hours per candidate model would make the
comparison tedious enough to skip.

Both paths build their request from :func:`request_body`, so the comparison
cannot quietly measure a different prompt or a looser schema than production
sends. Only OpenAI is implemented; an Anthropic client is about twenty lines
when a Claude model needs scoring, and `schema.py` is already neutral.

Request and response shapes here were read from the provider's current API
documentation, not recalled.
"""

from __future__ import annotations

import io
import json

# OpenAI batch status values, mapped onto the three outcomes the pipeline
# actually branches on.
_OPENAI_STATUS = {
    "validating": "pending", "in_progress": "pending", "finalizing": "pending",
    "completed": "ready",
    "expired": "expired",
    "failed": "failed", "cancelled": "failed", "cancelling": "failed",
}


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


class OpenAIBatchClient:
    """Batch extraction via the Chat Completions endpoint with strict
    Structured Outputs, so the schema is guaranteed rather than hoped for."""

    endpoint = "/v1/chat/completions"

    def __init__(self, api_key: str | None = None, *, completion_window: str = "24h"):
        from openai import OpenAI  # imported here so the module loads without a key

        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self.completion_window = completion_window

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
            return {}
        raw = self.client.files.content(batch.output_file_id).text
        out: dict[str, dict] = {}
        for row in raw.splitlines():
            if not row.strip():
                continue
            rec = json.loads(row)
            if rec.get("error") or rec.get("response", {}).get("status_code") != 200:
                continue
            try:
                content = rec["response"]["body"]["choices"][0]["message"]["content"]
                out[rec["custom_id"]] = json.loads(content)
            except (KeyError, IndexError, json.JSONDecodeError):
                continue
        return out


class OpenAISyncClient:
    """One call, one answer. Used only to score the gold set.

    Production extraction is batched, for provenance as much as for the 50%.
    The comparison is not: fifty documents do not need a batch, waiting hours
    per candidate model would make the comparison tedious enough to skip, and
    a synchronous call sends the identical body — see :func:`request_body`.
    """

    def __init__(self, api_key: str | None = None):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()

    def complete(self, payload: dict) -> dict | None:
        """The parsed extraction, or ``None`` if the answer was unusable.

        A model that returns something unparseable has failed the document,
        and that is a result worth scoring — so it is reported as a failure
        rather than smoothed into an empty extraction, which is the *correct*
        answer for most documents and would flatter the model.
        """
        answer = self.client.chat.completions.create(**request_body(payload))
        content = answer.choices[0].message.content
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
