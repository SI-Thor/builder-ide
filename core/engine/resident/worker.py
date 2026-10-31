#!/usr/bin/env python3
"""The resident process — the long-lived side of the warm scene server.

Run **by path**, never with ``-m``:

    python /path/to/worker.py --backend fake --root /path/to/state

The reason is the interpreter split. The real engine pins ``bpy==4.2.0``,
which is Python 3.11; this core is 3.12. The resident therefore cannot
import the ``core`` package — it would drag in pydantic and the rest — so
this file and the two it loads (``protocol.py`` and the backend) are
standalone: standard library only, and 3.9-compatible syntax.

Three things are load-bearing here, all of them measured:

* **the protocol channel is kept pristine** (WS §5.5). The child's stdout is
  the RPC channel; its stderr is a log *file*. Before anything else is
  imported, stdout is pointed at stderr, so an engine that chats on stdout
  (Blender's render progress does) cannot corrupt a frame. A resident that
  blocks forever on a full pipe is a resident that stops answering.
* **everything runs on this thread** (WS §5.1). ``bpy`` is not thread-safe;
  a threaded server segfaults the process the moment a request touches the
  window manager. So there is exactly one thread here, reading frames in a
  loop, and the adapter talks to it one request at a time.
* **the recipe document is ours** (§1.1). The document crosses as JSON and
  the ops are applied with the same path grammar the core uses; the parent
  checks the two implementations agree by comparing digests.
"""
from __future__ import annotations

import base64
import os
import sys

# ---------------------------------------------------------------------------
# The channel, before anything can chat on it.

_PROTOCOL_FD = os.dup(1)          # a private copy of the RPC channel
os.dup2(2, 1)                     # stdout now goes to the log file
sys.stdout = sys.stderr           # and so does anything that prints

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import protocol  # noqa: E402  (standalone: standard library only)

__all__ = ["main"]


def _load_backend(name: str, pin: dict):
    """The backend module for a name, imported standalone.

    ``fake`` is the deterministic scene the tests and the benchmark run on;
    ``blender`` is the real engine, which needs its own interpreter (bpy).
    """
    if name == "fake":
        import fake_backend

        return fake_backend.FakeSceneBackend(pin)
    if name == "blender":
        import blender_backend

        return blender_backend.BlenderBackend(pin)
    raise SystemExit(
        f"unknown backend {name!r}; the backends are 'fake' and 'blender'"
    )


class Resident:
    """The frames this process answers."""

    def __init__(self, backend, pin: dict) -> None:
        self.backend = backend
        self.pin = pin
        self.document: dict = {"entries": {}}
        self.applied_ops = 0
        self.started_at = None

    # -- the methods --------------------------------------------------------

    def handle(self, frame: dict) -> dict:
        method = frame.get("method")
        params = frame.get("params") or {}
        if method not in protocol.METHODS:
            raise protocol.ProtocolError(
                f"unknown method {method!r}; this resident answers "
                f"{list(protocol.METHODS)}"
            )
        return getattr(self, f"_on_{method.replace('.', '_')}")(params)

    def _on_ping(self, params: dict) -> dict:
        return {"pong": True, "protocol": protocol.PROTOCOL_VERSION}

    def _on_describe(self, params: dict) -> dict:
        described = dict(self.backend.describe())
        described.setdefault("pin", self.pin)
        described["protocol"] = protocol.PROTOCOL_VERSION
        return described

    def _on_sync(self, params: dict) -> dict:
        """Bring the resident up to a recipe document.

        Three shapes: a *replace* (the first load of a fresh resident —
        there is nothing to be incremental about), *ops* (the ordinary case:
        the document moves by a typed diff, and the scene is updated in
        place for the entries the diff touched), and the **no-op** (neither)
        — the adapter asking where the resident stands, which is how the
        recovery's digest check is phrased.
        """
        document = params.get("document")
        ops = params.get("ops") or []
        if params.get("replace"):
            if not isinstance(document, dict):
                raise protocol.ProtocolError("sync (replace) needs a document")
            self.document = document
            touched = sorted(document.get("entries", {}))
        elif ops:
            # The dirty set is computed against the **base** document, as the
            # core computes it: a removed entry is gone from the new
            # document, so asking the new one would miss it and its objects
            # would linger in the scene.
            touched = protocol.touched_entries(self.document, ops)
            self.document = protocol.apply_ops(self.document, ops)
        else:
            touched = []
        self.backend.on_document(self.document, touched)
        self.applied_ops += len(ops)
        return {
            "document_digest": protocol.content_hash(self.document),
            "touched": touched,
            "applied_ops": self.applied_ops,
        }

    def _on_state(self, params: dict) -> dict:
        return {"state": self.backend.state()}

    def _on_stats(self, params: dict) -> dict:
        stats = dict(self.backend.stats())
        stats["applied_ops"] = self.applied_ops
        return stats

    def _on_stage(self, params: dict) -> dict:
        data = self.backend.stage(
            stage=str(params.get("stage", "")),
            dep_keys=list(params.get("dep_keys") or []),
            version_hash=str(params.get("version_hash", "")),
        )
        return {"data": base64.b64encode(data).decode("ascii")}

    def _on_preview(self, params: dict) -> dict:
        data = self.backend.preview(
            subject=str(params.get("subject", "")),
            rung=int(params.get("rung", 1)),
            resolution=str(params.get("resolution", "480p")),
            seed=int(params.get("seed", 0)),
        )
        return {"data": base64.b64encode(data).decode("ascii")}

    def _on_export(self, params: dict) -> dict:
        data = self.backend.export(
            format=str(params.get("format", "")),
            profile=str(params.get("profile", "preview")),
        )
        return {"data": base64.b64encode(data).decode("ascii")}

    def _on_shutdown(self, params: dict) -> dict:
        return {"bye": True}


def main(argv: list | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="The resident scene process")
    parser.add_argument("--backend", default="fake")
    parser.add_argument("--root", default=".")
    parser.add_argument("--pin", default="{}", help="the engine pin, as JSON")
    args = parser.parse_args(argv)

    try:
        pin = json.loads(args.pin)
    except json.JSONDecodeError as exc:
        print(f"--pin is not JSON: {exc}", file=sys.stderr)
        return 2

    try:
        backend = _load_backend(args.backend, pin)
    except Exception as exc:  # the missing piece, named
        print(f"the backend {args.backend!r} could not be loaded: {exc}", file=sys.stderr)
        return 3

    resident = Resident(backend, pin)
    out = os.fdopen(_PROTOCOL_FD, "wb", buffering=0)
    stdin = sys.stdin.buffer

    for line in stdin:
        if not line.strip():
            continue
        request_id = 0
        try:
            frame = protocol.decode(line)
            request_id = int(frame.get("id", 0))
            result = resident.handle(frame)
        except Exception as exc:
            out.write(
                protocol.encode(
                    protocol.error_frame(
                        request_id, "resident_error", f"{type(exc).__name__}: {exc}"
                    )
                )
            )
            continue
        out.write(protocol.encode(protocol.ok_frame(request_id, result)))
        if frame.get("method") == "shutdown":
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
