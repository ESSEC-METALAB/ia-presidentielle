"""structlog configuration: JSON on stderr, one event per step.

Events carry run_id, source_id, document counts and duration_ms. Never a secret,
never a full document body.
"""

import logging
import sys

import structlog


def configure_logging(level: str) -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=_stderr_logger,
        # Not cached: a cached logger keeps the stream it first saw, which breaks as soon
        # as that stream is replaced (a test capturing output, a redirected process).
        cache_logger_on_first_use=False,
    )


def _stderr_logger(*_args: object) -> structlog.PrintLogger:
    return structlog.PrintLogger(file=sys.stderr)
