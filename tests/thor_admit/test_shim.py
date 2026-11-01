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

from thor_admit import (
    LeaseRejected,
    _lock_holder,
    lease,
    phase,
    register_presence,
    socket_path,
)

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

    def __init__(
        self,
        directory: Path,
        available_bytes: int | None = None,
        extra: list[str] | None = None,
    ):
        self.directory = directory
        self.socket = directory / "sock"
        self.state = directory / "state"
        self.process: subprocess.Popen | None = None
        # A daemon whose view of the box's memory the test holds still: the
        # daemon reads the kernel's own file in production, and a test that
        # wants a lease to *wait* needs the answer to stay the same.
        self.available_bytes = available_bytes
        self.extra = extra or []
        self.meminfo = directory / "meminfo"

    def _write_meminfo(self, available_bytes: int) -> None:
        total = 128 * 1024**3

        def kb(value: int) -> int:
            return value // 1024

        self.meminfo.write_text(
            f"MemTotal:       {kb(total):>12} kB\n"
            f"MemFree:        {kb(available_bytes):>12} kB\n"
            f"MemAvailable:   {kb(available_bytes):>12} kB\n"
            "Buffers:              0 kB\n"
            f"Cached:         {kb(total - available_bytes):>12} kB\n"
            "SwapTotal:             0 kB\n"
            "SwapFree:              0 kB\n"
        )

    def set_available(self, available_bytes: int) -> None:
        """Move the box's free memory, as the test sees it."""
        self._write_meminfo(available_bytes)

    def start(self) -> None:
        assert BINARY is not None
        command = [
            str(BINARY),
            "daemon",
            "--socket",
            str(self.socket),
            "--state-dir",
            str(self.state),
            # These leases are CPU-only, so the box's real GPU pool
            # (other seats' CUDA work can leave it under the GPU floor)
            # must not be a part of their admission.
            "--gpu-probe",
            "off",
            "--idle-exit",
            "120",
        ]
        if self.available_bytes is not None:
            self._write_meminfo(self.available_bytes)
            command += ["--meminfo", str(self.meminfo)]
        command += self.extra
        self.process = subprocess.Popen(
            command,
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
    # A run teaches only if it lasted: the block below outlives the
    # five-second line, because a lease that ends in no time did no work
    # and its peak teaches the history nothing (round 9).
    with lease("1G", "shim-peak", socket_path_override=daemon.socket):
        time.sleep(5.5)

    records = daemon.history()
    assert len(records) == 1
    record = records[0]
    assert record["label"] == "shim-peak"
    assert record["basis"] == "measured"
    assert record["source"] == "thor-admit"
    # The shim reports its own high-water mark, and a clean finish.
    assert record["peak_rss_bytes"] > 0
    assert record["exit_code"] == 0


@needs_binary
def test_a_no_op_lease_teaches_nothing(daemon: Daemon):
    # The same lease, gone in milliseconds: measured, logged, and pointedly
    # absent from the history.
    with lease("1G", "shim-noop", socket_path_override=daemon.socket):
        pass

    assert daemon.history() == []


@needs_binary
def test_auto_uses_what_the_label_learned(daemon: Daemon):
    # auto refuses to guess until the label has three runs behind it, and
    # each of those runs has to have lasted long enough to teach.
    for _ in range(3):
        with lease("2G", "shim-auto", socket_path_override=daemon.socket):
            time.sleep(5.5)

    with lease("auto", "shim-auto", socket_path_override=daemon.socket) as held:
        assert held.peak_bytes > 0
        # The learned peak is what the shim measured, not what it asked for.
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
def test_a_lease_can_give_memory_back_while_it_runs(daemon: Daemon):
    # The work changed phase: the lease reserved 8G and now needs 1G, and
    # the difference goes back to the box at once.
    with lease("8G", "shim-phase", socket_path_override=daemon.socket) as held:
        leases = daemon.status()["leases"]
        assert leases[0]["peak_bytes"] == 8 * 1024**3

        phase(held, "1G", socket_path_override=daemon.socket)

        leases = daemon.status()["leases"]
        assert leases[0]["peak_bytes"] == 1024**3, "the reservation did not shrink"
        # The lease is still the lease: the id did not change.
        assert leases[0]["lease"] == held.lease_id


@needs_binary
def test_a_grow_the_box_has_no_room_for_is_refused(daemon: Daemon):
    # The box has 122 GiB. A grow to 500 GiB cannot fit, whatever else is
    # running, so the daemon refuses it and the lease keeps the promise it
    # has — it does not promise what it cannot keep.
    with lease("1G", "shim-grow", socket_path_override=daemon.socket) as held:
        with pytest.raises(LeaseRejected) as refusal:
            phase(held, "500G", socket_path_override=daemon.socket)
        assert "room" in str(refusal.value), str(refusal.value)

        leases = daemon.status()["leases"]
        assert leases[0]["peak_bytes"] == 1024**3, "a refused grow changed the lease"


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


@needs_binary
def test_the_shim_takes_the_box_lock_after_the_lease_is_granted(
    daemon: Daemon, tmp_path: Path
):
    # The box's legacy lock, held for as long as the leased block runs, and
    # given back when it ends.
    lock = tmp_path / "box.lock"
    with lease("1G", "shim-lock", socket_path_override=daemon.socket, lock=lock):
        assert _lock_holder(lock) == os.getpid(), "the lock is not held by the lease"
    assert _lock_holder(lock) is None, "the lock was not given back"


@needs_binary
def test_a_lease_that_inherited_the_box_lock_gives_it_back_while_it_waits(
    tmp_path: Path
):
    # The seat that has not migrated writes `flock heavy.lock python3 ...`,
    # so it holds the lock from the moment it starts. The shim repairs the
    # order: the lock goes back while the lease waits for room, and is taken
    # again when the lease is granted.
    directory = tmp_path / "box"
    directory.mkdir()
    # The floor is placed so that a 40 GiB lease does not fit: 100 GiB free
    # leaves 60 GiB, and the floor is 80 GiB. At 121 GiB free it fits.
    daemon = Daemon(
        directory,
        available_bytes=100 * 1024**3,
        extra=["--floor", "80G", "--emergency-floor", "1G"],
    )
    daemon.start()
    try:
        # The floor is placed so that a 40 GiB lease does not fit.
        lock = directory / "box.lock"
        script = (
            "import os, sys, time\n"
            "from thor_admit import lease\n"
            "with lease('40G', 'shim-queued', socket_path_override=sys.argv[1]):\n"
            "    print('held', flush=True)\n"
            "    time.sleep(3)\n"
            "print('done', flush=True)\n"
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(CRATE / "python")
        child = subprocess.Popen(
            ["flock", str(lock), sys.executable, "-c", script, str(daemon.socket)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            text=True,
        )
        assert child.stdout is not None
        assert child.stderr is not None

        # The lease is waiting for room.
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not daemon.status()["queue"]:
            time.sleep(0.1)
        assert daemon.status()["queue"], "the lease never waited for room"

        # And while it waits, it holds nothing: the lock is what the box's
        # own work waits for.
        assert _lock_holder(lock) is None, (
            "a lease that is waiting for room must not hold the box's lock"
        )

        # Make room: the lease is granted and the lock is taken back.
        daemon.set_available(121 * 1024**3)
        assert child.stdout.readline().strip() == "held", "the lease was not granted"
        assert _lock_holder(lock) == child.pid, "the lock was not taken back"

        assert child.stdout.readline().strip() == "done"
        child.wait(timeout=20)
        assert _lock_holder(lock) is None, "the lock was not given back"

        errors = child.stderr.read()
        assert "already holds" in errors, (
            f"the shim did not say that it inherited the lock: {errors}"
        )
    finally:
        daemon.stop()
