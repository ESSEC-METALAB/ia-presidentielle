"""Runs the update command on demand, one run at a time and no more often than allowed.

The register's "Actualiser" button lands here, through the web server. A run reads the
candidates' sites again, so the cooldown is what keeps a button pressed in a loop from
hammering them under the Metalab's name. The annotation step only calls the model for
passages that are new: a run that collects nothing new costs no model call.

The last run is kept in a small JSON file, so a restarted server still knows when the
register was last refreshed and how that ended. The last update of any origin (this
button, or the scheduled morning run) is read from the file the update command writes
when it ends (`last_update_path`): that is the date the site shows.
"""

import json
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Literal, Protocol

from observatoire.domain.ports import Clock

StartOutcome = Literal["started", "running", "too_soon"]


class Process(Protocol):
    def poll(self) -> int | None: ...


Launcher = Callable[[Sequence[str], Path, IO[bytes]], Process]


def launch_process(command: Sequence[str], cwd: Path, log: IO[bytes]) -> Process:
    return subprocess.Popen(
        list(command), cwd=cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
    )


@dataclass(frozen=True)
class RefreshStatus:
    running: bool
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    next_allowed_at: datetime | None
    last_update_at: datetime | None = None
    last_update_exit_code: int | None = None

    def as_json(self) -> dict[str, object]:
        def iso(moment: datetime | None) -> str | None:
            return moment.isoformat() if moment else None

        return {
            "running": self.running,
            "startedAt": iso(self.started_at),
            "finishedAt": iso(self.finished_at),
            "exitCode": self.exit_code,
            "nextAllowedAt": iso(self.next_allowed_at),
            "lastUpdateAt": iso(self.last_update_at),
            "lastUpdateExitCode": self.last_update_exit_code,
        }


class RefreshJob:
    def __init__(
        self,
        *,
        command: Sequence[str],
        workdir: Path,
        state_path: Path,
        log_path: Path,
        cooldown: timedelta,
        clock: Clock,
        last_update_path: Path | None = None,
        launcher: Launcher = launch_process,
    ) -> None:
        self._command = tuple(command)
        self._last_update_path = last_update_path
        self._workdir = workdir
        self._state_path = state_path
        self._log_path = log_path
        self._cooldown = cooldown
        self._clock = clock
        self._launch = launcher
        self._process: Process | None = None
        self._state = _read_json(state_path)
        self._lock = threading.Lock()  # the web server answers from several threads

    def start(self) -> StartOutcome:
        with self._lock:
            return self._start()

    def status(self) -> RefreshStatus:
        with self._lock:
            return self._status()

    def _start(self) -> StartOutcome:
        if self._status().running:
            return "running"
        allowed = self._next_allowed()
        if allowed is not None and self._clock.now() < allowed:
            return "too_soon"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("ab") as log:
            self._process = self._launch(self._command, self._workdir, log)
        self._state = {"started_at": self._clock.now().isoformat()}
        self._save()
        return "started"

    def _status(self) -> RefreshStatus:
        self._reap()
        last = _read_json(self._last_update_path) if self._last_update_path else {}
        return RefreshStatus(
            running=self._process is not None,
            started_at=_moment(self._state.get("started_at")),
            finished_at=_moment(self._state.get("finished_at")),
            exit_code=_code(self._state.get("exit_code")),
            next_allowed_at=self._next_allowed(),
            last_update_at=_moment(last.get("finishedAt")),
            last_update_exit_code=_code(last.get("exitCode")),
        )

    def _reap(self) -> None:
        if self._process is None:
            return
        code = self._process.poll()
        if code is None:
            return
        self._process = None
        self._state = self._state | {
            "finished_at": self._clock.now().isoformat(),
            "exit_code": code,
        }
        self._save()

    def _next_allowed(self) -> datetime | None:
        started = _moment(self._state.get("started_at"))
        return started + self._cooldown if started else None

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self._state), encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _code(value: object) -> int | None:
    return value if isinstance(value, int) else None
