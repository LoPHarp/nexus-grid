#!/usr/bin/env bash
# Starts a server and 3 workers, submits a Mandelbrot job, kills one worker mid-job, prints the outcome.
# Usage: demo/failover.sh   (needs .venv from `pip install -r requirements.txt`, or python3 with deps)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"; [ -x "$PY" ] || PY=python3
PORT="${PORT:-8765}"; BASE="http://127.0.0.1:$PORT"
export NEXUS_DB="$(mktemp -u).db" HEARTBEAT_TIMEOUT=2
PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null || true; rm -f "$NEXUS_DB"; }
trap cleanup EXIT
json() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

"$PY" -m uvicorn nexus.server:app --port "$PORT" --log-level warning & PIDS+=($!)
for _ in $(seq 50); do curl -sf "$BASE/api/health" >/dev/null && break; sleep 0.2; done
for i in 1 2 3; do
  "$PY" -m nexus.worker --url "ws://127.0.0.1:$PORT/ws/worker" --name "w$i" --id "w$i" --delay 0.3 >/dev/null & PIDS+=($!)
done
sleep 2
echo "workers connected: $(curl -s $BASE/api/workers | json 'len(d)')"
JOB=$(curl -s -X POST $BASE/api/jobs -H 'Content-Type: application/json' \
  -d '{"type":"mandelbrot","params":{"width":160,"height":80,"tile":20,"max_iter":50}}' | json 'd["id"]')
sleep 2
echo "progress before kill: $(curl -s $BASE/api/jobs/$JOB | json 'str(d["done"])+"/"+str(d["total"])')"
echo ">>> killing worker w1 (pid ${PIDS[1]})"; kill -9 "${PIDS[1]}"
for _ in $(seq 120); do
  [ "$(curl -s $BASE/api/jobs/$JOB | json 'd["state"]')" = done ] && break; sleep 0.5
done
echo "final job: $(curl -s $BASE/api/jobs/$JOB | json 'd["state"]+" "+str(d["done"])+"/"+str(d["total"])')"
echo "workers: $(curl -s $BASE/api/workers | json '", ".join(w["id"]+("=alive" if w["alive"] else "=dead")+"("+str(w["done"])+" tiles)" for w in d)')"
