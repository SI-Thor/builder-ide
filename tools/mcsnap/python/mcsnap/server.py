"""The private world: its own port, its own loopback, its own lease.

The live world is a Paper server on 25565 with a human in it. This build
never touches it. What it runs instead is a **copy**: the same Paper jar
and the same JDK, on port 25610, bound to 127.0.0.1, in offline mode,
with its own world directory grown from the same seed (``agent-world``)
so the terrain matches the live world's without being the live world's
files.

Three things the copy must never do:

* bind the live Bedrock port — Geyser and Floodgate are **removed** from
  the copy, because the live server already owns 19132 and two servers
  cannot both own it;
* reach the live world — it has its own world directory, its own port, and
  its own RCON port;
* run without a memory lease. On the Thor, GPU memory is system memory; a
  Java server that starts without a lease can take the box down. The lease
  is honest: the peak is what the server actually touches.

Nothing is downloaded. The jar and the JDK are the ones the live world
already runs, read from ``agent-world/runtime``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .rcon import RconClient, RconError

__all__ = [
    "PrivateServer",
    "ServerResult",
    "read_server_properties",
    "default_java",
    "default_jar",
    "live_server_command",
]


def read_server_properties(server_dir: str | Path) -> dict[str, str]:
    """A Paper server's ``server.properties``, as a dict."""
    path = Path(server_dir) / "server.properties"
    properties: dict[str, str] = {}
    if not path.is_file():
        return properties
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        properties[key.strip()] = value.strip()
    return properties


def live_world_build() -> str:
    """The build the live world is running, from its own version history.

    The runtime holds more than one Paper jar, and the newest one by
    timestamp is not the one the world runs: 1.21.11 was fetched after
    26.1.2, and the world's own version is 26.1.2. The live server writes
    down which build it is (``version_history.json``), so that file is the
    authority. A private copy of the world has to be a copy of *that*
    server, or the world it grows is a different kind of world.
    """
    history = (
        Path.home() / "lm-wt" / "agent-world" / "runtime" / "paper" / "version_history.json"
    )
    if not history.is_file():
        return ""
    try:
        data = json.loads(history.read_text(encoding="utf-8"))
    except ValueError:
        return ""
    return str(data.get("currentVersion") or "").split(" ")[0]


def default_java() -> Path | None:
    """The JDK the live world already runs — the newest one it has."""
    runtime = Path.home() / "lm-wt" / "agent-world" / "runtime"
    if not runtime.is_dir():
        return None
    candidates = sorted(runtime.glob("jdk-*/bin/java"))
    for candidate in reversed(candidates):
        if candidate.is_file():
            return candidate
    return None


def default_jar() -> Path | None:
    """The Paper jar the live world already runs — never downloaded."""
    runtime = Path.home() / "lm-wt" / "agent-world" / "runtime"
    dl = runtime / "dl"
    if not dl.is_dir():
        return None
    build = live_world_build()
    jars = sorted(dl.glob("paper-*.jar"))
    if build:
        for jar in jars:
            stem = jar.stem.replace("paper-", "")
            if build == stem or build.startswith(stem):
                return jar
    return jars[-1] if jars else None


@dataclass
class ServerResult:
    """What a start or a stop produced."""

    ok: bool
    detail: str = ""
    seconds: float = 0.0
    pid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "seconds": round(self.seconds, 3),
            "pid": self.pid,
        }


class PrivateServer:
    """The private Paper server: start it, stop it, ask it questions."""

    def __init__(
        self,
        server_dir: str | Path,
        *,
        java: str | Path | None = None,
        jar: str | Path | None = None,
        label: str = "world-snapshot.server",
        peak: str = "4G",
        tier: str = "live",
        xms: str = "1G",
        xmx: str = "2G",
        thor_admit: str | Path | None = None,
        world_name: str = "world",
    ) -> None:
        self.server_dir = Path(server_dir)
        self.java = Path(java) if java else default_java()
        self.jar = Path(jar) if jar else default_jar()
        self.label = label
        self.peak = peak
        self.tier = tier
        self.xms = xms
        self.xmx = xmx
        self.thor_admit = (
            Path(thor_admit)
            if thor_admit
            else Path.home() / "lm-tools" / "thor-admit"
        )
        self.world_name = world_name
        properties = read_server_properties(self.server_dir)
        self.properties = properties
        self.rcon_host = properties.get("server-ip") or "127.0.0.1"
        self.rcon_port = int(properties.get("rcon.port") or 25575)
        self.rcon_password = properties.get("rcon.password") or ""
        self.log_dir = self.server_dir / "logs"
        self.pid_file = self.log_dir / "mcsnap-server.pid"
        self.log_file = self.log_dir / "console.log"

    # -- paths ---------------------------------------------------------------

    @property
    def world_dir(self) -> Path:
        """The world's own directory inside the server directory."""
        name = self.properties.get("level-name") or self.world_name
        return self.server_dir / name

    # -- the lease -----------------------------------------------------------

    def _command(self) -> list[str]:
        """The command line the server runs under."""
        if self.java is None or self.jar is None:
            raise RuntimeError("no JDK or no Paper jar to run")
        return [
            str(self.thor_admit),
            "run",
            "--tier",
            self.tier,
            "--peak",
            self.peak,
            "--label",
            self.label,
            "--",
            str(self.java),
            f"-Xms{self.xms}",
            f"-Xmx{self.xmx}",
            "-XX:+UseG1GC",
            "-XX:MaxGCPauseMillis=100",
            "-Dcom.mojang.eula.agree=true",
            "-jar",
            str(self.jar),
            "--nogui",
        ]

    # -- lifecycle -----------------------------------------------------------

    def start(self, *, wait_seconds: float = 240.0) -> ServerResult:
        """Start the server and wait until it answers on RCON."""
        if self.status()["running"]:
            return ServerResult(ok=True, detail="the server is already running")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        command = self._command()
        with open(self.log_file, "ab") as log:
            process = subprocess.Popen(
                command,
                cwd=str(self.server_dir),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # its own session: it outlives this tool
            )
        self.pid_file.write_text(f"{process.pid}\n", encoding="utf-8")

        deadline = time.monotonic() + wait_seconds
        last_error = ""
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return ServerResult(
                    ok=False,
                    detail=f"the server exited with {process.returncode}; see {self.log_file}",
                    seconds=time.perf_counter() - started,
                    pid=process.pid,
                )
            try:
                self.command("version")
                return ServerResult(
                    ok=True,
                    detail="the server is up",
                    seconds=time.perf_counter() - started,
                    pid=process.pid,
                )
            except (RconError, OSError) as error:
                last_error = str(error)
                time.sleep(2.0)
        return ServerResult(
            ok=False,
            detail=f"the server did not answer on RCON within {wait_seconds:.0f}s ({last_error})",
            seconds=time.perf_counter() - started,
            pid=process.pid,
        )

    def stop(self, *, timeout: float = 240.0) -> ServerResult:
        """Stop the server cleanly: ``stop`` on the console, then wait.

        A clean stop is the server's own save, so the world's files on disk
        are the world's final state.
        """
        started = time.perf_counter()
        pid = self.pid()
        try:
            self.command("stop")
        except (RconError, OSError) as error:
            if pid is None:
                return ServerResult(
                    ok=False, detail=f"the server was not answering: {error}",
                    seconds=time.perf_counter() - started,
                )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pid is None or not self._alive(pid):
                return ServerResult(
                    ok=True,
                    detail="the server has stopped",
                    seconds=time.perf_counter() - started,
                    pid=pid,
                )
            time.sleep(0.5)
        return ServerResult(
            ok=False,
            detail=f"the server was still running after {timeout:.0f}s",
            seconds=time.perf_counter() - started,
            pid=pid,
        )

    # -- questions -----------------------------------------------------------

    def command(self, command: str) -> str:
        """Run one console command over RCON."""
        return RconClient(
            self.rcon_host, self.rcon_port, self.rcon_password
        ).run(command)

    def pid(self) -> int | None:
        """The pid of the server process, if it is running."""
        if not self.pid_file.is_file():
            return None
        try:
            pid = int(self.pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            return None
        return pid if self._alive(pid) else None

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def status(self) -> dict[str, Any]:
        """Is the server up, and what does it say about itself?"""
        pid = self.pid()
        listening = False
        try:
            with socket.create_connection((self.rcon_host, self.rcon_port), timeout=2.0):
                listening = True
        except OSError:
            listening = False
        answer = ""
        if listening:
            try:
                answer = self.command("version").strip()
            except (RconError, OSError):
                answer = ""
        return {
            "running": bool(pid) and listening,
            "pid": pid,
            "rcon": {"host": self.rcon_host, "port": self.rcon_port},
            "listening": listening,
            "version": answer,
            "world_dir": str(self.world_dir),
            "log": str(self.log_file),
        }
