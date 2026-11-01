"""The Python shim takes a lease, holds it, and gives it back.

These tests need the Rust daemon; they skip themselves when the binary has
not been built (`cargo build --release` in ``tools/thor-admit``).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from thor_admit import LeaseRejected, lease, register_presence, socket_path

REPO = Path(__file__).resolve().parents[2]
CRATE = REPO / "tools" / "thor-admit"


def _binary() -> Path | None:
    for candidate in (
        CRATE / "target" / "release" / "thor-admit",
        CRATE / "target" / "debug" / "thor-admit",
    ):
        if candidate.exists():
            return candidate
    return None


BINARY = _binary()
needs_binary = pytest.mark.skipif(
    BINARY is None, reason="the thor-admit binary has not been built"
)


class Daemon:
    """A daemon under test, on its own socket and in its own state."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.socket = directory / "sock"
        self.state = directory / "state"
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        assert BINARY is not None
        # The floor is what this box can clear, not what the Thor can: the
        # tests are about the lease's round trip, not the admission
        # arithmetic, and they must run the same on a 3 GiB CI box and on
        # the box itself (the same rule the Rust integration tests follow).
        self.process = subprocess.Popen(
            [
                str(BINARY),
                "daemon",
                "--socket",
                str(self.socket),
                "--state-dir",
                str(self.state),
                "--floor",
                "64M",
                "--emergency-floor",
                "512M",
                "--idle-exit",
                "120",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.socket.exists():
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    probe.connect(str(self.socket))
                    return
                except OSError:
                    pass
                finally:
                    probe.close()
            time.sleep(0.05)
        raise RuntimeError("the daemon did not come up")

    def status(self) -> dict:
        assert BINARY is not None
        output = subprocess.run(
            [str(BINARY), "status", "--socket", str(self.socket), "--json"],
            capture_output=True,
            check=True,
        )
        return json.loads(output.stdout)

    def history(self) -> list[dict]:
        path = self.state / "peaks.jsonl"
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text().splitlines()
            if line.strip()
        ]

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None


@pytest.fixture
def daemon(tmp_path: Path):
    instance = Daemon(tmp_path)
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


@needs_binary
def test_a_lease_is_held_and_given_back(daemon: Daemon):
    with lease("1G", "shim-test", socket_path_override=daemon.socket) as held:
        assert held.lease_id > 0
        assert held.peak_bytes == 1024**3
        status = daemon.status()
        assert len(status["leases"]) == 1
        assert status["leases"][0]["label"] == "shim-test"

    # The lease is gone once the block ends.
    status = daemon.status()
    assert status["leases"] == []


@needs_binary
def test_the_peak_is_recorded_for_the_label(daemon: Daemon):
    with lease("1G", "shim-peak", socket_path_override=daemon.socket):
        pass

    records = daemon.history()
    assert len(records) == 1
    record = records[0]
    assert record["label"] == "shim-peak"
    assert record["basis"] == "measured"
    assert record["source"] == "thor-admit"
    # The shim reports its own high-water mark.
    assert record["peak_rss_bytes"] > 0


@needs_binary
def test_auto_uses_what_the_label_learned(daemon: Daemon):
    with lease("2G", "shim-auto", socket_path_override=daemon.socket):
        pass

    with lease("auto", "shim-auto", socket_path_override=daemon.socket) as held:
        assert held.peak_bytes > 0
        assert held.peak_bytes != 2 * 1024**3


@needs_binary
def test_auto_without_history_is_refused(daemon: Daemon):
    with pytest.raises(LeaseRejected):
        with lease("auto", "shim-never-seen", socket_path_override=daemon.socket):
            pass


@needs_binary
def test_a_dead_process_gives_its_lease_back(daemon: Daemon):
    # A shim that is killed inside its lease: the kernel drops the lock, so
    # the daemon must give the memory back on its own.
    script = (
        "import os, signal, sys, time\n"
        "from thor_admit import lease\n"
        "with lease('1G', 'shim-doomed', socket_path_override=sys.argv[1]):\n"
        "    print('held', flush=True)\n"
        "    os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(CRATE / "python")
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(daemon.socket)],
        stdout=subprocess.PIPE,
        env=environment,
        text=True,
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "held"

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not daemon.status()["leases"]:
            break
        time.sleep(0.1)
    assert daemon.status()["leases"] == [], "the lease leaked after the process died"
    child.wait(timeout=10)


@needs_binary
def test_the_shim_uses_the_environment_socket(daemon: Daemon, monkeypatch):
    monkeypatch.setenv("THOR_ADMIT_SOCKET", str(daemon.socket))
    assert socket_path() == daemon.socket
    with lease("1G", "shim-env", socket_path_override=socket_path()) as held:
        assert held.lease_id > 0


@needs_binary
def test_a_lease_says_its_tier(daemon: Daemon):
    with lease("1G", "shim-tier", tier="study", socket_path_override=daemon.socket):
        leases = daemon.status()["leases"]
        assert len(leases) == 1
        assert leases[0]["tier"] == "study"


@needs_binary
def test_a_lease_without_a_tier_is_live(daemon: Daemon):
    with lease("1G", "shim-unlabelled", socket_path_override=daemon.socket):
        leases = daemon.status()["leases"]
        assert len(leases) == 1
        assert leases[0]["tier"] == "live"


@needs_binary
def test_the_shim_registers_presence_work(daemon: Daemon, tmp_path: Path):
    marker = tmp_path / "ran"
    job_id = register_presence(
        "shim-presence",
        "study",
        "1G",
        ["sh", "-c", f"sleep 1; touch {marker}"],
        resumable=True,
        socket_path_override=daemon.socket,
    )
    assert job_id >= 0

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.1)
    assert marker.exists(), "the presence job did not run"

    presence = daemon.status()["presence"]
    assert len(presence) == 1
    assert presence[0]["label"] == "shim-presence"
    assert presence[0]["tier"] == "study"
    assert presence[0]["resumable"] is True
