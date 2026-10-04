"""Central RobotsPolicy: robots.txt, per-domain rate limit and the crawler's identity
(CLAUDE.md §7). Every HTTP request of the pipeline goes through one instance.
"""

import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

# Returns the robots.txt body, None when the site has none (HTTP 4xx), and raises
# when it cannot be read at all.
RobotsFetcher = Callable[[str], str | None]

_DENY_ALL = ("User-agent: *", "Disallow: /")


class RobotsPolicy:
    """Follows RFC 9309 on failures: no robots.txt (4xx) allows everything, an
    unreadable one (5xx, network error) allows nothing until the next run.
    """

    def __init__(
        self,
        user_agent: str,
        min_delay_seconds: float,
        fetch_robots: RobotsFetcher,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.user_agent = user_agent
        self._min_delay = min_delay_seconds
        self._fetch_robots = fetch_robots
        self._monotonic = monotonic
        self._sleep = sleep
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}

    def allows(self, url: str) -> bool:
        origin = _origin(url)
        if origin not in self._parsers:
            self._parsers[origin] = self._load(origin)
        parser = self._parsers[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def wait_turn(self, url: str) -> None:
        """Blocks until at least `min_delay_seconds` passed since the last request to that host."""
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            remaining = self._min_delay - (self._monotonic() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._monotonic()

    def _load(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        try:
            body = self._fetch_robots(f"{origin}/robots.txt")
        except OSError:
            parser.parse(_DENY_ALL)
            return parser
        if body is None:
            return None
        parser.parse(body.splitlines())
        return parser


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
