"""Runs one Apify actor and returns its dataset, through Apify's REST API.

Apify (apify.com) hosts the scrapers that read the candidates' social media accounts,
whose platforms offer no affordable official access. One synchronous call per account:
the run starts, waits, and returns its items. Every run carries a spending cap.
"""

from typing import Any

import httpx

from observatoire.domain.errors import SourceUnavailableError

_RUN = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


class ApifyClient:
    def __init__(
        self,
        http: httpx.Client,
        token: str | None,
        *,
        max_charge_usd: float,
        timeout_seconds: int,
    ) -> None:
        self._http = http
        self._token = token
        self._max_charge_usd = max_charge_usd
        self._timeout_seconds = timeout_seconds

    def run(self, actor: str, run_input: dict[str, Any], *, label: str) -> list[dict[str, Any]]:
        """The run's dataset items; `label` names the source in errors."""
        if not self._token:
            raise SourceUnavailableError(label, "APIFY_TOKEN is not set")
        try:
            response = self._http.post(
                _RUN.format(actor=actor.replace("/", "~")),
                params={
                    "token": self._token,
                    "maxTotalChargeUsd": self._max_charge_usd,
                    "timeout": self._timeout_seconds,
                },
                json=run_input,
                timeout=self._timeout_seconds + 30,
            )
        except httpx.HTTPError as error:
            raise SourceUnavailableError(label, f"Apify: {type(error).__name__}") from error
        if response.status_code >= 400:
            raise SourceUnavailableError(label, f"Apify {actor}: HTTP {response.status_code}")
        items = response.json()
        if not isinstance(items, list):
            raise SourceUnavailableError(label, f"Apify {actor}: unexpected answer")
        return [item for item in items if isinstance(item, dict)]
