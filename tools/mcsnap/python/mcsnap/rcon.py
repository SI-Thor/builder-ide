"""A small RCON client — the Paper server's own remote console.

Minecraft's RCON is a length-prefixed packet protocol over TCP:

* a packet is a little-endian ``int32`` length, then that many bytes:
  an ``int32`` request id, an ``int32`` packet type, and the payload as a
  null-terminated string;
* ``3`` is the authentication packet and ``2`` the command packet;
* the server answers an authentication with type ``2`` and a request id of
  ``-1`` when the password is wrong.

The vanilla server closes the connection after it has answered one
command, so this client opens a connection per command. That costs one
round trip on loopback and removes every question about keeping a socket
alive across a long snapshot.

The snapshot uses three commands, and they are the whole of the trick:

``save-off``
    stop the server's automatic saving, so the files do not change under
    the copy;
``save-all flush``
    write every chunk to disk **now** and wait for it;
``save-on``
    give the automatic saving back.

Nothing here needs a package: the protocol is a handful of struct
unpacks.
"""

from __future__ import annotations

import socket
import struct
from typing import Any

__all__ = ["RconClient", "RconError"]


SERVERDATA_RESPONSE_VALUE = 0
SERVERDATA_COMMAND = 2
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_AUTH = 3

#: The request id the protocol uses for "no particular request".
AUTH_FAILED_ID = -1


class RconError(RuntimeError):
    """The server refused, or the connection went away."""


def _pack(request_id: int, packet_type: int, payload: bytes) -> bytes:
    """One RCON packet: the length, then the id, the type and the payload."""
    body = struct.pack("<ii", request_id, packet_type) + payload + b"\x00\x00"
    return struct.pack("<i", len(body)) + body


def _recv_exactly(sock: socket.socket, count: int) -> bytes:
    """Read exactly ``count`` bytes, or raise."""
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        block = sock.recv(remaining)
        if not block:
            raise RconError("the server closed the connection")
        chunks.append(block)
        remaining -= len(block)
    return b"".join(chunks)


class RconClient:
    """One RCON connection, used for one command."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 25575,
        password: str = "",
        timeout: float = 15.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = float(timeout)
        self._socket: socket.socket | None = None

    # -- connection ----------------------------------------------------------

    def connect(self) -> "RconClient":
        """Open the socket and authenticate."""
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._socket = sock
        try:
            sock.sendall(_pack(1, SERVERDATA_AUTH, self.password.encode("utf-8")))
            request_id, payload = self._read_packet()
            if request_id == AUTH_FAILED_ID:
                raise RconError("the server refused the RCON password")
            del payload
        except Exception:
            self.close()
            raise
        return self

    def close(self) -> None:
        """Close the socket, if it is open."""
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def __enter__(self) -> "RconClient":
        return self.connect()

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- packets -------------------------------------------------------------

    def _read_packet(self) -> tuple[int, str]:
        """Read one packet: its request id and its payload.

        The **response** packet carries a type field as well as the id:

        ==============  ==================================================
        length          int32, little endian
        request id      int32, little endian
        type            int32, little endian
        payload         a null-terminated string
        ==============  ==================================================

        The protocol's own description leaves the type out of the
        response, and a reader that believes it reads the *type* as the
        payload and gets an empty string back for every command. That is
        what this reader did at first; Paper's own ``version`` answer
        ("This server is running Paper version ...") is what showed it.
        """
        if self._socket is None:
            raise RconError("not connected")
        (length,) = struct.unpack("<i", _recv_exactly(self._socket, 4))
        if length < 8 or length > 1 << 20:
            raise RconError(f"the server sent a packet of {length} bytes")
        body = _recv_exactly(self._socket, length)
        (request_id,) = struct.unpack_from("<i", body, 0)
        payload = body[8:].split(b"\x00", 1)[0]
        return request_id, payload.decode("utf-8", errors="replace")

    def command(self, command: str) -> str:
        """Run one command and return the server's answer."""
        if self._socket is None:
            raise RconError("not connected")
        self._socket.sendall(_pack(2, SERVERDATA_COMMAND, command.encode("utf-8")))
        request_id, payload = self._read_packet()
        if request_id == AUTH_FAILED_ID:
            raise RconError("the server refused the command")
        return payload

    def run(self, command: str) -> str:
        """Open a connection, run one command, close it."""
        with self.connect():
            return self.command(command)


def run_command(
    host: str,
    port: int,
    password: str,
    command: str,
    *,
    timeout: float = 15.0,
) -> str:
    """Run one RCON command on a fresh connection."""
    return RconClient(host, port, password, timeout).run(command)
