#!/usr/bin/env python3
"""Does the listen backlog matter for a tick of 64 requests at once?

A tick is 64 HTTP requests arriving at the same moment. socketserver's
default backlog is 5, which is nowhere near enough: when the accept
loop cannot keep up — and on a busy box it cannot, because the worker
thread holds the GIL between its GPU calls — the kernel refuses the
connections and the clients see errors.

This measures it on the same machine: the same handler, the same
burst, once with the default backlog and once with the 256 the server
uses. The point is not that the small number always fails — it does
not, when the box is quiet — but that the large one is the one to
rely on.
"""

from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        # the work of a decision: take a moment, so that the next
        # burst arrives while this one is still being served
        time.sleep(0.05)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:
        pass


def burst(port: int, n: int) -> tuple[int, list[str]]:
    """``n`` connections opened at the same moment."""
    errors: list[str] = []
    lock = threading.Lock()

    def one() -> None:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=10)
            s.sendall(
                b"POST /v1/systemone HTTP/1.0\r\nHost: x\r\nContent-Length: 2\r\n\r\nhi"
            )
            data = s.recv(64)
            s.close()
            if not data.startswith(b"HTTP/1"):
                with lock:
                    errors.append("no response")
        except Exception as exc:
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=one) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return n - len(errors), errors


def main() -> None:
    n = 64
    results = {}
    for backlog in (5, 256):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        httpd.request_queue_size = backlog
        httpd.daemon_threads = True
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.2)
        ok, errors = burst(port, n)
        httpd.shutdown()
        results[backlog] = ok
        kinds: dict[str, int] = {}
        for e in errors:
            kinds[e] = kinds.get(e, 0) + 1
        print(f"backlog {backlog:4d}: {ok}/{n} answered, errors: {kinds or 'none'}")

    assert results[256] == n, f"a tick's burst was refused with the server's backlog: {results}"
    print("OK")


if __name__ == "__main__":
    main()
