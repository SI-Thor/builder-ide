"""serve.py — the return screen, served from the Thor on the LAN (port 8131).

One page, five beats (docs/research/dsmc.md, in the order the brief gives):
what changed, what matters, what is waiting on you, what was undone, what
next — with the Biographer's letter on top. Everything the page shows is
read from the world's ledger **read-only**; the only writes this server
makes are to its own state directory (visit markers and the precedent
stub's events), never to the world.

    PYTHONPATH=$REPO_ROOT tools/return_screen/.venv/bin/python \
        tools/return_screen/serve.py --port 8131

Endpoints (JSON unless said):

    GET  /                       the page (public/)
    GET  /api/overview?human=    the whole fold: letter, threshold, lanes,
                                 marks, drift, thread
    POST /api/visit              {human} — mark "I was here, at this time"
    GET  /api/ask?q=&human=      the active-perception box
    POST /api/rewind/preview     {at_epoch|seq, actors, kinds} — the fork it
                                 would make (core.rewind; never deletes)
    GET  /api/precedent?human=   pending questions + recent rulings
    POST /api/precedent          {id, ruling, note, human} — write the
                                 precedent event
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # the repo root, for core.*

from letter import render  # noqa: E402
from ask import answer as ask_answer  # noqa: E402
from rewind_api import preview as rewind_preview  # noqa: E402
from worldview import WorldView  # noqa: E402
import precedent_stub as precedent_mod  # noqa: E402

# core.precedent is the plan; the stub is what exists until that lane lands
try:
    from core.precedent import PrecedentStore  # type: ignore  # noqa: F401
    PRECEDENT_SOURCE = "core.precedent"
except Exception:  # pragma: no cover - the state of main today
    PrecedentStore = precedent_mod.PrecedentStore  # type: ignore
    PRECEDENT_SOURCE = "stub (core.precedent not landed on main)"

MAX_BODY = 64 * 1024


class ScreenState:
    def __init__(self, args: argparse.Namespace) -> None:
        self.view = WorldView(db=args.db, player_log=args.player_log,
                              state_dir=args.state_dir, ttl=args.ttl)
        self.state_dir = Path(args.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = PrecedentStore(self.state_dir / "precedents.jsonl")

    def record_visit(self, human: str) -> dict:
        event = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "human": human, "page": "return screen"}
        with (self.state_dir / "visits.jsonl").open("a") as fh:
            fh.write(json.dumps(event) + "\n")
        return event

    def overview(self, human: str | None) -> dict:
        facts = self.view.snapshot(human)
        facts["letter"] = render(facts)
        facts["pause"] = {
            "note": ("no pause file is live: the running reflex predates build #3's "
                     "pause seam (docs/lab/exp-drift-pause.md) — the ladder is wired, "
                     "dry-run by default, and nothing has fired"),
        }
        return facts


STATE: ScreenState | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "return-screen/1"

    def log_message(self, fmt: str, *args) -> None:  # one line per request
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------- helpers

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name: str, content_type: str) -> None:
        path = HERE / "public" / name
        if not path.exists():
            self._json({"error": f"no {name}"}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    # --------------------------------------------------------------- verbs

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                self._static("index.html", "text/html; charset=utf-8")
            elif url.path == "/app.js":
                self._static("app.js", "text/javascript; charset=utf-8")
            elif url.path == "/style.css":
                self._static("style.css", "text/css; charset=utf-8")
            elif url.path == "/api/overview":
                self._json(STATE.overview(qs.get("human")))
            elif url.path == "/api/ask":
                q = qs.get("q", "").strip()
                if not q:
                    self._json({"error": "empty question"}, 400)
                    return
                self._json(ask_answer(q, STATE.view, qs.get("human")))
            elif url.path == "/api/precedent":
                snapshot = STATE.view.snapshot(qs.get("human"))
                precedent_mod.seed_questions(STATE.store, snapshot)
                pending = [p.as_dict() for p in STATE.store.pending()]
                recent = [p.as_dict() for p in STATE.store.all()][-8:]
                self._json({"source": PRECEDENT_SOURCE, "pending": pending,
                            "recent": recent})
            else:
                self._json({"error": f"no route {url.path}"}, 404)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            body = self._body()
            if url.path == "/api/visit":
                human = (body.get("human") or "").strip() or "Casey"
                self._json({"ok": True, "visit": STATE.record_visit(human),
                            "humans": STATE.view.humans()})
            elif url.path == "/api/rewind/preview":
                self._json(rewind_preview(
                    STATE.view.rows(),
                    at_epoch=body.get("at_epoch"), seq=body.get("seq"),
                    actors=body.get("actors") or [], kinds=body.get("kinds") or []))
            elif url.path == "/api/precedent":
                ruled = STATE.store.adjudicate(
                    body.get("id", ""), body.get("ruling", ""),
                    body.get("human") or "Casey", body.get("note", ""))
                if ruled is None:
                    self._json({"error": "no such pending question"}, 404)
                    return
                self._json({"ok": True, "precedent": ruled.as_dict(),
                            "source": PRECEDENT_SOURCE})
            else:
                self._json({"error": f"no route {url.path}"}, 404)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",
                        default="/home/caseydigennaro/lm-wt/agent-world/runtime/world-ledger.sqlite3")
    parser.add_argument("--player-log", default="/home/caseydigennaro/lm-wt/agent-world/"
                                                "runtime/logs/player-builds.jsonl")
    parser.add_argument("--state-dir", default=str(HERE / "state"))
    parser.add_argument("--host", default="0.0.0.0", help="LAN only; the Thor's address")
    parser.add_argument("--port", type=int, default=8131)
    parser.add_argument("--ttl", type=float, default=60.0,
                        help="seconds the ledger fold is cached")
    args = parser.parse_args()

    global STATE
    STATE = ScreenState(args)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"return screen on http://{args.host}:{args.port}/ — ledger {args.db}",
          flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
