"""Provider clients.

Only the batch surface is implemented, because production extraction runs as a
batch — for provenance as much as for the 50% discount. The gold-set comparison
uses ordinary synchronous calls instead; 50 documents do not need a batch, and
keeping the comparison synchronous means a second provider costs no extra
client code.

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
            "body": {
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
            },
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
