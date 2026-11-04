"""Serves the register site, plus two endpoints behind its "Actualiser" button.

    GET  /api/status   the last refresh: running, started, finished, exit code, next allowed
    POST /api/refresh  starts a refresh: 202 started, 409 one is running, 429 too soon

Standard library only (CLAUDE.md §8: no web framework for the POC). Every response is
sent with `Cache-Control: no-cache`, so a reload after a refresh shows the new `data.js`.
"""

import json
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from observatoire.adapters.web.refresh_job import RefreshJob, StartOutcome

_START_STATUS: dict[StartOutcome, HTTPStatus] = {
    "started": HTTPStatus.ACCEPTED,
    "running": HTTPStatus.CONFLICT,
    "too_soon": HTTPStatus.TOO_MANY_REQUESTS,
}


class RegisterHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, job: RefreshJob, directory: str, **kwargs: Any) -> None:
        self._job = job
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/api/status":
            self._send_json(HTTPStatus.OK, self._job.status().as_json())
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/refresh":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        outcome = self._job.start()
        body = {"outcome": outcome} | self._job.status().as_json()
        self._send_json(_START_STATUS[outcome], body)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return  # requests are not logged: no visitor data is kept

    def _send_json(self, status: HTTPStatus, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(site_dir: Path, job: RefreshJob, *, host: str, port: int) -> None:
    handler = partial(RegisterHandler, job=job, directory=str(site_dir))
    with ThreadingHTTPServer((host, port), handler) as server:
        server.serve_forever()
