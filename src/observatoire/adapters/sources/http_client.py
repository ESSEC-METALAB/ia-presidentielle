"""HTTP GET for every reader, through the central RobotsPolicy."""

from urllib.parse import urljoin

import httpx

from observatoire.domain.errors import RobotsDisallowedError, SourceUnavailableError
from observatoire.services.robots_policy import RobotsFetcher, RobotsPolicy

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class PoliteHttpClient:
    """Checks robots.txt and waits its turn before every request, redirects included.

    Redirects are followed by hand so that a hop to another host is checked against
    that host's robots.txt too: no request reaches a domain whose robots.txt forbids
    it (acceptance criterion 7).
    """

    def __init__(self, client: httpx.Client, policy: RobotsPolicy, max_redirects: int) -> None:
        self._client = client
        self._policy = policy
        self._max_redirects = max_redirects

    def get(self, url: str) -> httpx.Response:
        current = url
        for _ in range(self._max_redirects + 1):
            response = self._request(current)
            if response.status_code not in _REDIRECT_STATUSES:
                return _require_ok(response, url)
            location = response.headers.get("location")
            if not location:
                raise SourceUnavailableError(url, f"HTTP {response.status_code} without Location")
            current = urljoin(current, location)
        raise SourceUnavailableError(url, f"more than {self._max_redirects} redirects")

    def _request(self, url: str) -> httpx.Response:
        if not self._policy.allows(url):
            raise RobotsDisallowedError(url)
        self._policy.wait_turn(url)
        try:
            return self._client.get(url, follow_redirects=False)
        except httpx.HTTPError as error:
            raise SourceUnavailableError(url, f"{type(error).__name__}: {error}") from error


def robots_fetcher(client: httpx.Client) -> RobotsFetcher:
    """robots.txt reader for RobotsPolicy: None when absent (4xx), OSError when unreadable."""

    def fetch(url: str) -> str | None:
        try:
            response = client.get(url, follow_redirects=True)
        except httpx.HTTPError as error:
            raise OSError(f"{type(error).__name__}: {error}") from error
        if response.is_client_error:
            return None
        if response.status_code != httpx.codes.OK:
            raise OSError(f"HTTP {response.status_code}")
        return response.text

    return fetch


def _require_ok(response: httpx.Response, url: str) -> httpx.Response:
    if response.status_code != httpx.codes.OK:
        raise SourceUnavailableError(url, f"HTTP {response.status_code}")
    return response
