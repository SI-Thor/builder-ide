#!/usr/bin/env bash
# run.sh — start the return screen detached on the Thor (LAN, port 8131).
#   tools/return_screen/run.sh            # start if not running
#   tools/return_screen/run.sh stop       # stop it
# The server is stdlib Python + core.* (pydantic comes with the tool venv).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$(dirname "$HERE")")"
LOG="$HERE/server.log"
PIDFILE="$HERE/server.pid"

if [ "${1:-}" = "stop" ]; then
  if [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "stopped $(cat "$PIDFILE")"
  else
    echo "not running"
  fi
  rm -f "$PIDFILE"
  exit 0
fi

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "already running: pid $(cat "$PIDFILE") (http://$(hostname -I | awk '{print $1}'):8131/)"
  exit 0
fi

cd "$REPO"
PYTHONPATH="$REPO" setsid nohup "$HERE/.venv/bin/python" "$HERE/serve.py" \
  --port 8131 --state-dir "$HERE/state" > "$LOG" 2>&1 < /dev/null &
echo $! > "$PIDFILE"
sleep 1.5
if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "failed to start — tail of $LOG:"; tail -5 "$LOG"; rm -f "$PIDFILE"; exit 1
fi
echo "return screen: pid $(cat "$PIDFILE") on http://$(hostname -I | awk '{print $1}'):8131/ (log: $LOG)"
