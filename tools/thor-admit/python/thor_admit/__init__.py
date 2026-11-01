"""Take a memory lease from the box's admission daemon.

The shim is what a seat uses when its work is already a Python process: the
seat does not have to spawn a command, it just says how much memory it is
about to use and works inside the lease.

    from thor_admit import lease

    with lease("40G", "trellis"):
        ...the heavy work...

    with lease("auto", "trellis"):      # the daemon's learned p95
        ...the same work, with the peak the last runs measured...

**What the lease really is.** The client holds an exclusive ``flock(2)`` on
a file the daemon names. The kernel drops that lock when this process dies,
whatever killed it, so the daemon can tell a dead client from a working one
and give the memory back. Nothing has to be cleaned up by hand.

**The protocol** is JSON, one object per line, over the daemon's Unix
socket: the same one the ``thor-admit`` CLI speaks, so ``nc -U`` can read it.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

__all__ = [
    "DaemonNotRunning",
    "Lease",
    "LeaseError",
    "LeaseRejected",
    "default_socket_path",
    "lease",
    "phase",
    "register_presence",
    "socket_path",
]

#: How often the shim says it is alive while it holds a lease. The lock on
#: the lease file says this process is not *dead*; only the heartbeat says
#: it is not *stuck* — and the daemon gives a silent client a grace period
#: (60 s by default) before it takes the lease back.
HEARTBEAT_INTERVAL_S = 5.0


class LeaseError(RuntimeError):
    """Something went wrong taking or holding a lease."""


class DaemonNotRunning(LeaseError):
    """The admission daemon is not answering on its socket."""


class LeaseRejected(LeaseError):
    """The daemon refused the lease."""


def default_socket_path() -> Path:
    """Where the daemon listens by default."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "thor-admit.sock"
    return Path(f"/tmp/thor-admit-{os.getuid()}.sock")


def socket_path() -> Path:
    """The socket to use: ``THOR_ADMIT_SOCKET`` if it is set."""
    override = os.environ.get("THOR_ADMIT_SOCKET")
    if override:
        return Path(override)
    return default_socket_path()


@dataclass
class Lease:
    """A lease that has been granted."""

    #: The daemon's number for this lease.
    lease_id: int
    #: The label it was taken under.
    label: str
    #: The peak the daemon is holding the lease to.
    peak_bytes: int
    #: The floor the box was holding when it was granted.
    floor_bytes: int
    #: The file the lock is on.
    lock_path: Path


def _peak_argument(peak: Any) -> Any:
    """``"auto"`` or a size in bytes goes over the wire as it is."""
    if isinstance(peak, str):
        if peak.strip().lower() == "auto":
            return "auto"
        return _parse_size(peak)
    if isinstance(peak, int):
        return peak
    raise TypeError(f"a peak is a size in bytes or \"auto\", not {peak!r}")


def _parse_size(text: str) -> int:
    """``"40G"`` into bytes. The same units the CLI takes."""
    raw = text.strip()
    split = 0
    for index, character in enumerate(raw):
        if not (character.isdigit() or character == "."):
            split = index
            break
    else:
        split = len(raw)
    number = raw[:split].strip()
    unit = raw[split:].strip().lower()
    if not number:
        raise ValueError(f"cannot read {text!r} as a size")
    multipliers = {
        "": 1,
        "b": 1,
        "k": 1024,
        "kb": 1024,
        "kib": 1024,
        "m": 1024**2,
        "mb": 1024**2,
        "mib": 1024**2,
        "g": 1024**3,
        "gb": 1024**3,
        "gib": 1024**3,
        "t": 1024**4,
        "tb": 1024**4,
        "tib": 1024**4,
    }
    if unit not in multipliers:
        raise ValueError(f"unknown size unit {unit!r} in {text!r}")
    return int(float(number) * multipliers[unit])


def _peak_rss_bytes() -> int | None:
    """This process's own high-water mark, which is what the lease used."""
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def _connect(path: Path, timeout: float | None) -> socket.socket:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    if timeout is not None:
        connection.settimeout(timeout)
    try:
        connection.connect(str(path))
    except (FileNotFoundError, ConnectionRefusedError) as error:
        connection.close()
        raise DaemonNotRunning(
            f"no admission daemon on {path}; start it with `thor-admit daemon` ({error})"
        ) from error
    return connection


def _start_daemon(path: Path) -> bool:
    """Start the daemon if it is not running. True when it came up."""
    candidates = []
    from_env = os.environ.get("THOR_ADMIT_BIN")
    if from_env:
        candidates.append(Path(from_env))
    candidates.append(Path(__file__).resolve().parent.parent.parent / "target/release/thor-admit")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "target/debug/thor-admit")
    for binary in candidates:
        if not binary.exists():
            continue
        try:
            subprocess.Popen(
                [str(binary), "daemon", "--socket", str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            continue
        for _ in range(100):
            time.sleep(0.1)
            try:
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                probe.connect(str(path))
                probe.close()
                return True
            except OSError:
                continue
        return False
    return False


@contextlib.contextmanager
def lease(
    peak: Any,
    label: str = "",
    *,
    priority: int = 0,
    tier: str = "live",
    timeout: float | None = None,
    socket_path_override: Path | None = None,
    start_daemon: bool = True,
) -> Iterator[Lease]:
    """Take a lease for the length of the block.

    ``peak`` is a size (``"40G"``, ``40 * 1024 ** 3``) or ``"auto"``, which
    asks the daemon for the p95 of this label's own history. ``label`` is
    the name the peak is learned under.

    ``tier`` says what kind of work this is: ``live``, ``preparation``,
    ``practice`` or ``study``. The tier is the accounting band the ledger
    books the lease's time to, and only ``live`` work may pre-empt the box's
    presence queue. The default is ``live``.

    The lease covers **this process** (and the children it starts), not the
    whole process group: the watchdog must never stop a seat's other work by
    accident.
    """
    path = socket_path_override or socket_path()
    label = label or _default_label()
    argument = _peak_argument(peak)

    try:
        connection = _connect(path, timeout)
    except DaemonNotRunning:
        if not start_daemon or not _start_daemon(path):
            raise
        connection = _connect(path, timeout)

    stream = connection.makefile("rwb")
    lock_fd: int | None = None
    granted: Lease | None = None
    release_exit_code: int | None = None
    try:
        request = {
            "op": "acquire",
            "label": label,
            "peak": argument,
            "priority": priority,
            "tier": tier,
            "target": {"process": {"pid": os.getpid()}},
        }
        stream.write((json.dumps(request) + "\n").encode("utf-8"))
        stream.flush()

        while True:
            line = stream.readline()
            if not line:
                raise LeaseError("the daemon closed the connection while waiting for a lease")
            event = json.loads(line.decode("utf-8"))
            kind = event.get("event")
            if kind == "queued":
                continue
            if kind == "granted":
                granted = Lease(
                    lease_id=int(event["lease"]),
                    label=str(event.get("label", label)),
                    peak_bytes=int(event.get("peak_bytes", 0)),
                    floor_bytes=int(event.get("floor_bytes", 0)),
                    lock_path=Path(event["lock_path"]),
                )
                break
            if kind == "rejected":
                raise LeaseRejected(str(event.get("reason", "the daemon refused the lease")))
            raise LeaseError(f"unexpected answer from the daemon: {event!r}")

        assert granted is not None
        # The lock is what makes the lease real: the kernel drops it when
        # this process dies, whatever killed it.
        lock_fd = os.open(str(granted.lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _send(stream, {"op": "held", "lease": granted.lease_id})

        # The heartbeat: its own connection, its own thread, because the
        # code inside the lease block may be busy — or stuck — and a stuck
        # holder is exactly what the heartbeat is for the daemon to notice.
        stop = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat,
            args=(path, granted.lease_id, stop),
            daemon=True,
        )
        heartbeat.start()

        # Whether the leased block ran to completion. The daemon learns a
        # label's peak only from runs that finished cleanly, so the release
        # says ``exit_code`` 0 when the block completed and says nothing
        # when it raised — a failed run teaches the history nothing.
        completed = False
        try:
            yield granted
            completed = True
        finally:
            stop.set()
            heartbeat.join(timeout=HEARTBEAT_INTERVAL_S + 1.0)
            release_exit_code = 0 if completed else None
    finally:
        if granted is not None and lock_fd is not None:
            with contextlib.suppress(OSError):
                _send(
                    stream,
                    {
                        "op": "release",
                        "lease": granted.lease_id,
                        "peak_rss_bytes": _peak_rss_bytes(),
                        "exit_code": release_exit_code,
                    },
                )
        if lock_fd is not None:
            with contextlib.suppress(OSError):
                os.close(lock_fd)
        with contextlib.suppress(OSError):
            stream.close()
        with contextlib.suppress(OSError):
            connection.close()


def phase(
    lease: int | Lease,
    peak: Any,
    *,
    socket_path_override: Path | None = None,
) -> None:
    """Change a running lease's reservation: the work changed phase.

    A lease that reserved far above what it is using can give the difference
    back while it runs, and the box's queue may use it at once. A lease that
    knows its work grew may ask for more, but only if the box has the room:
    a grow that does not fit is refused and the lease keeps the promise it
    has.

    ``peak`` is a size (``"4G"``) or ``"auto"``, which asks the daemon for
    the larger of the label's learned p95 and its last run.

    The lease's own id is in ``THOR_ADMIT_LEASE`` for a command started by
    ``thor-admit run``; a lease taken through this module knows its id too:

        with lease("40G", "trellis") as held:
            load_weights()                       # the heavy part
            phase(held, "8G")                    # give the rest back

    Raises ``LeaseRejected`` when the daemon refuses (no such lease, or a
    grow the box has no room for).
    """
    lease_id = lease.lease_id if isinstance(lease, Lease) else int(lease)
    argument = _peak_argument(peak)
    path = socket_path_override or socket_path()
    try:
        connection = _connect(path, None)
    except DaemonNotRunning:
        raise
    stream = connection.makefile("rwb")
    try:
        stream.write(
            (
                json.dumps(
                    {"op": "phase", "lease": lease_id, "peak": argument}
                )
                + "\n"
            ).encode("utf-8")
        )
        stream.flush()
        line = stream.readline()
        if not line:
            raise LeaseError("the daemon closed the connection")
        event = json.loads(line.decode("utf-8"))
        kind = event.get("event")
        if kind == "ok":
            return
        if kind == "rejected":
            raise LeaseRejected(str(event.get("reason", "the daemon refused the change")))
        if kind == "error":
            raise LeaseError(str(event.get("message", "the daemon reported an error")))
        raise LeaseError(f"unexpected answer from the daemon: {event!r}")
    finally:
        with contextlib.suppress(OSError):
            stream.close()
        with contextlib.suppress(OSError):
            connection.close()


def register_presence(
    label: str,
    tier: str,
    peak: Any,
    command: list[str],
    *,
    resumable: bool = False,
    socket_path_override: Path | None = None,
    start_daemon: bool = True,
) -> int:
    """Register work that runs when the box has room for it.

    The presence queue is the box's own useful work: it runs when live work
    is not waiting, and it gives way (by stopping, and by starting again
    later) when live work arrives.

    ``tier`` is ``preparation``, ``practice`` or ``study`` — the three tiers
    of background work. ``peak`` is the memory the job is expected to take.
    ``resumable`` says the job may be started again after it was pre-empted.

    Returns the job's id.
    """
    path = socket_path_override or socket_path()
    argument = _peak_argument(peak)
    try:
        connection = _connect(path, None)
    except DaemonNotRunning:
        if not start_daemon or not _start_daemon(path):
            raise
        connection = _connect(path, None)
    stream = connection.makefile("rwb")
    try:
        request = {
            "op": "presence_add",
            "label": label,
            "tier": tier,
            "peak": argument,
            "resumable": resumable,
            "command": list(command),
        }
        stream.write((json.dumps(request) + "\n").encode("utf-8"))
        stream.flush()
        line = stream.readline()
        if not line:
            raise LeaseError("the daemon closed the connection")
        event = json.loads(line.decode("utf-8"))
        kind = event.get("event")
        if kind == "presence_added":
            return int(event["id"])
        if kind == "rejected":
            raise LeaseRejected(str(event.get("reason", "the daemon refused the job")))
        raise LeaseError(f"unexpected answer from the daemon: {event!r}")
    finally:
        with contextlib.suppress(OSError):
            stream.close()
        with contextlib.suppress(OSError):
            connection.close()


def _send(stream: Any, request: dict[str, Any]) -> None:
    stream.write((json.dumps(request) + "\n").encode("utf-8"))
    stream.flush()
    line = stream.readline()
    if not line:
        raise LeaseError("the daemon closed the connection")
    event = json.loads(line.decode("utf-8"))
    if event.get("event") == "error":
        raise LeaseError(str(event.get("message", "the daemon reported an error")))


def _heartbeat(path: Path, lease_id: int, stop: threading.Event) -> None:
    """Say this lease's holder is alive, until it is told to stop.

    A failure to send is not a failure of the lease: the daemon may be
    restarting, and the next round tries a fresh connection. The lock, not
    the heartbeat, is what makes the lease real.
    """
    while not stop.wait(HEARTBEAT_INTERVAL_S):
        try:
            connection = _connect(path, timeout=5.0)
            try:
                stream = connection.makefile("rwb")
                _send(stream, {"op": "heartbeat", "lease": lease_id})
                stream.close()
            finally:
                connection.close()
        except (OSError, LeaseError):
            continue


def _default_label() -> str:
    """The label a lease takes when the caller does not name one."""
    main = sys.modules.get("__main__")
    name = getattr(main, "__file__", None) or "python"
    return Path(name).stem or "python"
