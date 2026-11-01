#!/usr/bin/env bash
# C2 -- the same model in two places.
#
# The Thor's clef-flash server is queued behind the shared heavy lock
# (flock ~/lm-wt/heavy.lock) and listens on the Thor's loopback port 9931.
# We reach it over an SSH tunnel so nothing is exposed on the LAN and no
# port is bound on the ProArt's side of the world.
#
# When the measurement is done we kill the server, which releases the lock.
set -u
LAB=/home/proart/lm-wt/clef-cascade
THOR_PORT=9931
LOCAL_PORT=8096

echo "waiting for the Thor clef-flash server to come up ..."
for i in $(seq 1 900); do
  if timeout 5 ssh thor-lan "ss -ltn 2>/dev/null | grep -q :$THOR_PORT"; then
    echo "server is listening on the Thor's loopback $THOR_PORT"
    break
  fi
  sleep 10
done

echo "opening the SSH tunnel 127.0.0.1:$LOCAL_PORT -> thor:$THOR_PORT ..."
ssh -f -N -L "$LOCAL_PORT:127.0.0.1:$THOR_PORT" \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 thor-lan
sleep 3

echo "probing the local server through the tunnel ..."
curl -s -m 10 "http://127.0.0.1:$LOCAL_PORT/health" | head -c 200; echo

echo "running C2 ..."
python3 "$LAB/scripts/c2_two_places.py" --seeds "${SEEDS:-24}" --packs "${PACKS:-q1,q64}" \
  --local-url "http://127.0.0.1:$LOCAL_PORT" --out "${OUT_NAME:-c2-two-places.json}"
rc=$?

echo "stopping the tunnel and the Thor server (releases the heavy lock) ..."
pkill -f "ssh -f -N -L $LOCAL_PORT:127.0.0.1:$THOR_PORT" 2>/dev/null
ssh thor-lan 'ps -eo pid,args | grep "[l]lama-server -m /home/caseydigennaro/models/clef-flash" | awk "{print \$1}" | xargs -r kill' 2>/dev/null
sleep 3
ssh thor-lan 'ps -eo pid,args | grep "[l]lama-server" | head -3; fuser -v ~/lm-wt/heavy.lock 2>&1 | grep " F" || echo "heavy lock is free"'
echo "C2 exit=$rc"
