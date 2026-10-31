"""The resident process and the RPC that reaches it.

The resident is a **subprocess** with a line-delimited JSON RPC on its
standard output. Two rules from the spike's findings are baked in here,
because both are silent failures:

* **the diagnostics never share the protocol channel** (WS §5.5). Blender's
  render progress writes to stdout on every frame; if that shared the pipe
  the RPC reads, the resident would block forever on a write nobody drains.
  So the child's stdout is the protocol, its stderr is a **log file** (a
  file, never a pipe: a pipe nobody reads fills up), and the child copies
  its own stdout onto stderr before it imports anything that might chat.
* **the resident answers on its main thread** (WS §5.1). ``bpy`` is not
  thread-safe — a threaded server segfaults the process the moment a request
  touches the window manager. The worker therefore reads frames in one loop
  on the thread that imported the engine, and the adapter talks to it one
  request at a time. There is no concurrency here on purpose.

Health is a *question*, not a guess: :meth:`ResidentProcess.ping` asks the
resident whether it is alive, and the adapter treats a failed ping, a dead
process, or a timed-out call the same way — the resident is gone, and the
adapter's job is to rebuild it.
"""
from __future__ import annotations

import errno
import os
import select
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from core.engine.resident import protocol

__all__ = [
    "ResidentProcess",
    "ResidentError",
    "ResidentCrashed",
    "ResidentTimeout",
    "ResidentRefused",
    "WORKER_PATH",
]

#: The worker script. It is run **by path**, not with ``-m``, so the resident
#: never imports the ``core`` package: the resident may run under the
#: engine's own interpreter (bpy pins Python 3.11; the core is 3.12).
WORKER_PATH = Path(__file__).with_name("worker.py")


def canonical_pin_json(pin: dict) -> str:
    """The pin as one sorted-key JSON string for the worker's ``--pin``."""
    import json

    return json.dumps(pin, sort_keys=True, separators=(",", ":"))


class ResidentError(Exception):
    """Base for everything that can go wrong between the core and a resident."""


class ResidentCrashed(ResidentError):
    """The resident is gone: it exited, or its channel closed."""


class ResidentTimeout(ResidentError):
    """The resident did not answer in time. A hung resident is a dead one."""


class ResidentRefused(ResidentError):
    """The resident answered, and the answer was a refusal."""

    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail or {}


class ResidentProcess:
    """One resident process and the channel to it."""

    def __init__(
        self,
        *,
        python: str | os.PathLike[str],
        backend: str,
        root: Path | str,
        log_path: Path | str,
        worker: Path | str = WORKER_PATH,
        pin: dict | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.python = str(python)
        self.backend = backend
        self.root = Path(root)
        self.log_path = Path(log_path)
        self.worker = Path(worker)
        self._pin = pin or {}
        self._env = env
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_handle: Any = None
        self._buffer = b""
        self._next_id = 1
        self._fd = -1

    # -- lifecycle ---------------------------------------------------------

    @property
    def pid(self) -> int | None:
        return None if self._proc is None else self._proc.pid

    @property
    def argv(self) -> list[str]:
        argv = [
            self.python,
            str(self.worker),
            "--backend", self.backend,
            "--root", str(self.root),
        ]
        if self._pin:
            # The pin crosses as data so the resident can report it back —
            # the check is only real when both sides know it.
            argv += ["--pin", canonical_pin_json(self._pin)]
        return argv

    def start(self, *, timeout_s: float) -> dict:
        """Start the resident and wait for it to answer its first ping.

        The start-up cost is the tax the warm server exists to pay **once**:
        on this box a cold Blender is ~0.25 s of imports (WS §4.2), and the
        v2 experiment measured ~2.4 s per scene of process start-up
        (E §5.2) — that is the whole of the warm win.
        """
        if self._proc is not None:
            raise ResidentError("this resident is already running")
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open("ab")
        self._buffer = b""
        env = dict(os.environ)
        if self._env:
            env.update(self._env)
        self._proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log_handle,
            cwd=str(self.root),
            env=env,
        )
        self._fd = self._proc.stdout.fileno() if self._proc.stdout else -1
        try:
            hello = self.call("ping", {}, timeout_s=timeout_s)
        except ResidentError:
            self.stop()
            raise
        return hello

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self, *, timeout_s: float = 10.0) -> None:
        """Ask the resident to shut down, then make sure it did."""
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    self.call("shutdown", {}, timeout_s=min(timeout_s, 5.0))
                except ResidentError:
                    pass
                try:
                    proc.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=timeout_s)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=timeout_s)
        finally:
            self._close_streams()
            self._proc = None
            self._fd = -1
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None

    def kill(self) -> None:
        """SIGKILL: no cleanup, no flush, no goodbye.

        This is the crash the recovery path is built for — the spike's
        ``kill -9`` (WS §4.4). The resident's own state dies with it; the
        journal does not.
        """
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                os.kill(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        # no cleanup *for the child* — but our own file handles still close
        self._close_streams()
        self._proc = None
        self._fd = -1
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _close_streams(self) -> None:
        for stream in (self._proc.stdin if self._proc else None,
                       self._proc.stdout if self._proc else None):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    # -- the RPC ------------------------------------------------------------

    def call(
        self, method: str, params: dict | None = None, *, timeout_s: float = 60.0
    ) -> dict:
        """One request, one response, one deadline."""
        if self._proc is None:
            raise ResidentCrashed("the resident is not running")
        request_id = self._next_id
        self._next_id += 1
        frame = {"id": request_id, "method": method, "params": params or {}}
        try:
            self._proc.stdin.write(protocol.encode(frame))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ResidentCrashed(
                f"the resident closed the channel: {exc}\n{self.log_tail()}"
            ) from exc

        deadline = time.monotonic() + timeout_s
        while True:
            line = self._read_line(deadline)
            try:
                answer = protocol.decode(line)
            except protocol.ProtocolError as exc:
                raise ResidentCrashed(f"garbage from the resident: {exc}") from exc
            if answer.get("id") != request_id:
                continue  # a stale frame; keep reading
            if answer.get("ok"):
                result = answer.get("result")
                return result if isinstance(result, dict) else {}
            error = answer.get("error") or {}
            raise ResidentRefused(
                str(error.get("code", "resident_error")),
                str(error.get("message", "the resident refused the request")),
                error.get("detail") if isinstance(error.get("detail"), dict) else None,
            )

    def ping(self, *, timeout_s: float = 5.0) -> dict:
        """Is the resident still there? The health check, asked."""
        return self.call("ping", {}, timeout_s=timeout_s)

    def _read_line(self, deadline: float) -> bytes:
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ResidentTimeout(
                    f"the resident did not answer within the deadline\n{self.log_tail()}"
                )
            try:
                ready, _, _ = select.select([self._fd], [], [], remaining)
            except (OSError, ValueError) as exc:
                raise ResidentCrashed(f"the resident's channel failed: {exc}") from exc
            if not ready:
                if not self.alive():
                    raise ResidentCrashed(
                        f"the resident exited ({self._proc.returncode})\n{self.log_tail()}"
                    )
                continue
            try:
                chunk = os.read(self._fd, 65536)
            except OSError as exc:
                if exc.errno == errno.EAGAIN:
                    continue
                raise ResidentCrashed(f"the resident's channel failed: {exc}") from exc
            if not chunk:
                raise ResidentCrashed(
                    f"the resident closed the channel (exit {self._proc.returncode})\n"
                    f"{self.log_tail()}"
                )
            self._buffer += chunk
        line, _, rest = self._buffer.partition(b"\n")
        self._buffer = rest
        return line

    # -- the resident's own measurements ------------------------------------

    def rss_mb(self) -> float | None:
        """The resident's resident set size, in MiB, read from ``/proc``.

        The spike measured the *server* process's ``VmHWM`` the same way
        (WS §4.3). ``None`` where ``/proc`` is not there — the guard then
        falls back to the resident's own report, and says so.
        """
        pid = self.pid
        if pid is None:
            return None
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
        except (OSError, ValueError, IndexError):
            return None
        return None

    def peak_rss_mb(self) -> float | None:
        pid = self.pid
        if pid is None:
            return None
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024.0
        except (OSError, ValueError, IndexError):
            return None
        return None

    def log_tail(self, lines: int = 20) -> str:
        """The resident's last words — the engine's own output, verbatim."""
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        tail = text.strip().splitlines()[-lines:]
        return "\n".join(tail)
