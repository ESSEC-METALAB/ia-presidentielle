"""robots.txt, rate limit and identification: CLAUDE.md §7, acceptance criterion 7."""

import httpx
import pytest

from observatoire.adapters.sources.http_client import PoliteHttpClient, robots_fetcher
from observatoire.domain.errors import RobotsDisallowedError, SourceUnavailableError
from observatoire.services.robots_policy import RobotsPolicy

UA = "ObservatoireTest/1.0 (+https://example.test)"
ROBOTS = "User-agent: *\nDisallow: /prive/\n"


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _policy(
    body: str | None = ROBOTS, delay: float = 0.0, time: FakeTime | None = None
) -> RobotsPolicy:
    clock = time or FakeTime()
    return RobotsPolicy(UA, delay, lambda _url: body, monotonic=clock.monotonic, sleep=clock.sleep)


def _raise_os_error(_url: str) -> str | None:
    raise OSError("unreachable")


def test_a_path_disallowed_by_robots_txt_is_refused() -> None:
    policy = _policy()

    assert policy.allows("https://site.test/prive/page") is False
    assert policy.allows("https://site.test/public/page") is True


def test_a_site_without_robots_txt_allows_everything() -> None:
    assert _policy(body=None).allows("https://site.test/prive/page") is True


def test_an_unreadable_robots_txt_allows_nothing() -> None:
    policy = RobotsPolicy(UA, 0.0, _raise_os_error)

    assert policy.allows("https://site.test/public/page") is False


def test_robots_txt_is_read_once_per_site() -> None:
    reads: list[str] = []

    def fetch(url: str) -> str:
        reads.append(url)
        return ROBOTS

    policy = RobotsPolicy(UA, 0.0, fetch)

    policy.allows("https://site.test/a")
    policy.allows("https://site.test/b")

    assert reads == ["https://site.test/robots.txt"]


def test_requests_to_one_host_are_spaced_by_the_minimum_delay() -> None:
    time = FakeTime()
    policy = _policy(delay=1.5, time=time)

    policy.wait_turn("https://site.test/a")
    time.now += 0.5
    policy.wait_turn("https://site.test/b")

    assert time.slept == [pytest.approx(1.0)]


def test_requests_to_different_hosts_do_not_wait_for_each_other() -> None:
    time = FakeTime()
    policy = _policy(delay=1.5, time=time)

    policy.wait_turn("https://one.test/a")
    policy.wait_turn("https://two.test/a")

    assert time.slept == []


def _client(routes: dict[str, httpx.Response], seen: list[str]) -> PoliteHttpClient:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.url} UA={request.headers['user-agent']}")
        return routes.get(str(request.url), httpx.Response(404))

    raw = httpx.Client(transport=httpx.MockTransport(handle), headers={"User-Agent": UA})
    return PoliteHttpClient(raw, RobotsPolicy(UA, 0.0, robots_fetcher(raw)), max_redirects=3)


def test_every_request_carries_the_crawler_user_agent() -> None:
    seen: list[str] = []
    http = _client({"https://site.test/page": httpx.Response(200, text="ok")}, seen)

    http.get("https://site.test/page")

    assert all(line.endswith(f"UA={UA}") for line in seen)


def test_a_disallowed_url_is_never_requested() -> None:
    seen: list[str] = []
    http = _client({"https://site.test/robots.txt": httpx.Response(200, text=ROBOTS)}, seen)

    with pytest.raises(RobotsDisallowedError):
        http.get("https://site.test/prive/page")

    assert not any("/prive/" in line for line in seen)


def test_a_redirect_to_a_disallowed_url_is_not_followed() -> None:
    seen: list[str] = []
    routes = {
        "https://site.test/robots.txt": httpx.Response(200, text=ROBOTS),
        "https://site.test/go": httpx.Response(302, headers={"location": "/prive/page"}),
    }
    http = _client(routes, seen)

    with pytest.raises(RobotsDisallowedError):
        http.get("https://site.test/go")

    assert not any("/prive/" in line for line in seen)


def test_a_non_200_answer_is_a_source_failure() -> None:
    http = _client({"https://site.test/page": httpx.Response(503)}, [])

    with pytest.raises(SourceUnavailableError, match="HTTP 503"):
        http.get("https://site.test/page")


def test_a_server_error_on_robots_txt_counts_as_unreadable() -> None:
    raw = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500)))

    with pytest.raises(OSError, match="HTTP 500"):
        robots_fetcher(raw)("https://site.test/robots.txt")
