"""Token accounting: a decorator that records every LLM call's usage, whatever the client."""

import threading

from observatoire.domain.annotation import LLMResponse, Prompt, ResponseSchema, UsageRecord
from observatoire.domain.ports import Clock, LLMClient, UsageTracker


class UsageRecordingClient:
    """An LLMClient that forwards to another one and records tokens in and out."""

    def __init__(self, client: LLMClient, tracker: UsageTracker, clock: Clock, step: str) -> None:
        self._client = client
        self._tracker = tracker
        self._clock = clock
        self._step = step

    @property
    def model(self) -> str:
        return self._client.model

    def complete(self, prompt: Prompt, schema: ResponseSchema) -> LLMResponse:
        response = self._client.complete(prompt, schema)
        self._tracker.record_usage(
            UsageRecord(
                step=self._step,
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                recorded_at=self._clock.now(),
            )
        )
        return response


class BufferedUsage:
    """A UsageTracker for calls made from several threads: records are kept in memory,
    then written by the thread that owns the database (`flush`)."""

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._lock = threading.Lock()

    def record_usage(self, record: UsageRecord) -> None:
        with self._lock:
            self._records.append(record)

    def flush(self, tracker: UsageTracker) -> None:
        with self._lock:
            records, self._records = self._records, []
        for record in records:
            tracker.record_usage(record)
