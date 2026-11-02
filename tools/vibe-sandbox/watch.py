"""The inbox watcher: a prompt JSON dropped in artifacts/vibe-sandbox/inbox/
starts the runner for it, one room at a time.

This is the spec's phase-2 watchdog seam, on our terms: a local inbox
directory reached over ssh/scp, not a guest-writable share. Run it detached:

    setsid nohup .venv/bin/python watch.py > ../../artifacts/vibe-sandbox/watch.log 2>&1 &
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from common import INBOX, LANE, ensure_dirs
import subprocess
import sys


class PromptHandler(FileSystemEventHandler):
    def on_created(self, ev) -> None:
        self.handle(ev.src_path)

    def on_moved(self, ev) -> None:
        self.handle(ev.dest_path)

    def handle(self, path: str) -> None:
        p = Path(path)
        if p.suffix != ".json" or not p.is_file() or p.parent.name == "done":
            return
        # let the writer finish before reading
        last = -1
        for _ in range(50):
            size = p.stat().st_size
            if size == last:
                break
            last = size
            time.sleep(0.2)
        dest = p.parent / "done" / p.name
        dest.parent.mkdir(exist_ok=True)
        shutil.move(str(p), dest)
        spec = json.loads(dest.read_text())
        print(f"[watch] {p.name} -> room {spec.get('room_id')}", flush=True)
        subprocess.run(
            [sys.executable, str(LANE / "runner.py"), "--spec", str(dest), "--commit-on-pass"],
            check=False,
        )


def main() -> int:
    ensure_dirs()
    (INBOX / "done").mkdir(exist_ok=True)
    obs = Observer()
    obs.schedule(PromptHandler(), str(INBOX), recursive=False)
    obs.start()
    print(f"[watch] watching {INBOX}", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
