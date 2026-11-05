"""The refresh job and the web server's endpoints, with a fake process and no network."""

import json
import threading
from collections.abc import Iterator, Sequence
from datetime import timedelta
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import IO

import pytest

from observatoire.adapters.web.refresh_job import RefreshJob
from observatoire.adapters.web.server import RegisterHandler
from support import T0, FrozenClock


class FakeProcess:
    def __init__(self) -> None:
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code


class FakeLauncher:
    def __init__(self) -> None:
        self.launched: list[FakeProcess] = []

    def __call__(self, command: Sequence[str], cwd: Path, log: IO[bytes]) -> FakeProcess:
        process = FakeProcess()
        self.launched.append(process)
        return process


class SettableClock(FrozenClock):
    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _job(tmp_path: Path, launcher: FakeLauncher, clock: FrozenClock) -> RefreshJob:
    return RefreshJob(
        command=["scripts/daily.sh"],
        workdir=tmp_path,
        state_path=tmp_path / "refresh.json",
        log_path=tmp_path / "logs" / "refresh.log",
        cooldown=timedelta(minutes=10),
        clock=clock,
        launcher=launcher,
    )


def test_a_refresh_starts_the_update_command(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    job = _job(tmp_path, launcher, FrozenClock())

    outcome = job.start()

    assert (outcome, len(launcher.launched), job.status().running) == ("started", 1, True)


def test_a_second_refresh_while_one_runs_is_refused(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    job = _job(tmp_path, launcher, FrozenClock())
    job.start()

    assert (job.start(), len(launcher.launched)) == ("running", 1)


def test_a_refresh_within_the_cooldown_is_refused(tmp_path: Path) -> None:
    launcher, clock = FakeLauncher(), SettableClock()
    job = _job(tmp_path, launcher, clock)
    job.start()
    launcher.launched[0].code = 0
    clock.advance(timedelta(minutes=9))

    assert job.start() == "too_soon"


def test_a_refresh_after_the_cooldown_starts_again(tmp_path: Path) -> None:
    launcher, clock = FakeLauncher(), SettableClock()
    job = _job(tmp_path, launcher, clock)
    job.start()
    launcher.launched[0].code = 0
    clock.advance(timedelta(minutes=10))

    assert (job.start(), len(launcher.launched)) == ("started", 2)


def test_the_last_run_survives_a_restart(tmp_path: Path) -> None:
    launcher, clock = FakeLauncher(), SettableClock()
    job = _job(tmp_path, launcher, clock)
    job.start()
    clock.advance(timedelta(minutes=3))
    launcher.launched[0].code = 1
    job.status()

    status = _job(tmp_path, FakeLauncher(), clock).status()

    assert (status.running, status.exit_code) == (False, 1)
    assert status.started_at == T0
    assert status.finished_at == T0 + timedelta(minutes=3)
    assert status.next_allowed_at == T0 + timedelta(minutes=10)


def _job_with_last_update(tmp_path: Path, content: str) -> RefreshJob:
    (tmp_path / "last-update.json").write_text(content, encoding="utf-8")
    return RefreshJob(
        command=["scripts/daily.sh"],
        workdir=tmp_path,
        state_path=tmp_path / "refresh.json",
        log_path=tmp_path / "logs" / "refresh.log",
        cooldown=timedelta(minutes=10),
        clock=FrozenClock(),
        last_update_path=tmp_path / "last-update.json",
        launcher=FakeLauncher(),
    )


def test_the_last_update_of_any_origin_is_reported(tmp_path: Path) -> None:
    job = _job_with_last_update(
        tmp_path, '{"finishedAt": "2026-11-05T07:04:12+00:00", "exitCode": 0}'
    )

    body = job.status().as_json()

    assert (body["lastUpdateAt"], body["lastUpdateExitCode"]) == ("2026-11-05T07:04:12+00:00", 0)
    assert body["finishedAt"] is None


@pytest.mark.parametrize("content", ["", "[]", '{"finishedAt": "hier", "exitCode": "0"}'])
def test_an_unreadable_last_update_is_unknown(tmp_path: Path, content: str) -> None:
    status = _job_with_last_update(tmp_path, content).status()

    assert (status.last_update_at, status.last_update_exit_code) == (None, None)


def test_a_damaged_state_file_is_a_fresh_start(tmp_path: Path) -> None:
    (tmp_path / "refresh.json").write_text("[]", encoding="utf-8")

    status = _job(tmp_path, FakeLauncher(), FrozenClock()).status()

    assert (status.started_at, status.next_allowed_at) == (None, None)


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[HTTPConnection, FakeLauncher]]:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>registre</p>", encoding="utf-8")
    launcher = FakeLauncher()
    handler = partial(
        RegisterHandler, job=_job(tmp_path, launcher, FrozenClock()), directory=str(site)
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5), launcher
    httpd.shutdown()
    httpd.server_close()


def _call(connection: HTTPConnection, method: str, path: str) -> tuple[int, bytes, str]:
    connection.request(method, path)
    response = connection.getresponse()
    return response.status, response.read(), response.getheader("Cache-Control") or ""


def test_the_site_is_served_without_caching(server: tuple[HTTPConnection, FakeLauncher]) -> None:
    status, body, cache = _call(server[0], "GET", "/index.html")

    assert (status, body, cache) == (200, b"<p>registre</p>", "no-cache")


def test_refresh_then_refresh_again(server: tuple[HTTPConnection, FakeLauncher]) -> None:
    connection, launcher = server

    first, body, _ = _call(connection, "POST", "/api/refresh")
    second, _, _ = _call(connection, "POST", "/api/refresh")

    assert (first, json.loads(body)["outcome"], second) == (202, "started", 409)
    assert len(launcher.launched) == 1


def test_status_reports_the_running_refresh(server: tuple[HTTPConnection, FakeLauncher]) -> None:
    connection, _ = server
    _call(connection, "POST", "/api/refresh")

    status, body, _ = _call(connection, "GET", "/api/status?t=1")

    assert (status, json.loads(body)["running"]) == (200, True)


def test_posting_elsewhere_is_not_found(server: tuple[HTTPConnection, FakeLauncher]) -> None:
    status, _, _ = _call(server[0], "POST", "/index.html")

    assert status == 404
