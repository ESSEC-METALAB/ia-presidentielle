"""Business exceptions."""


class ObservatoireError(Exception):
    """Base of every error this package raises on purpose."""


class ConfigurationError(ObservatoireError):
    """config/*.yaml or the environment is invalid."""


class SourceUnavailableError(ObservatoireError):
    """A source could not be read. The run marks it failed and carries on."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason


class RobotsDisallowedError(SourceUnavailableError):
    """robots.txt forbids this crawler from fetching the URL."""

    def __init__(self, url: str) -> None:
        super().__init__(url, "disallowed by robots.txt")
