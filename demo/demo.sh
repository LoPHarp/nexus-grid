#!/usr/bin/env bash
# Scenario for the video, against any server (local or public):
#   4 workers connect -> Mandelbrot job renders -> one worker is killed -> tiles are re-assigned -> job completes.
# Usage: demo/demo.sh                       (local server on :8000, start it first)
#        set -a; . ./.env; set +a; demo/demo.sh   (public server: NEXUS_URL and NEXUS_API_KEY from .env)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"; [ -x "$PY" ] || PY=python3
BASE="${NEXUS_URL:-http://localhost:8000}"; BASE="${BASE%/}"
RUN="$(date +%H%M%S)"; N="${WORKERS:-4}"; DELAY="${DELAY:-0.4}"
PIDS=()
trap 'kill "${PIDS[@]}" 2>/dev/null || true' EXIT
H=(-H 'Content-Type: application/json'); [ -n "${NEXUS_API_KEY:-}" ] && H+=(-H "X-API-Key: $NEXUS_API_KEY")
api() { curl -s -m 30 "${H[@]}" "$@"; }
json() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }
workers_alive() { api "$BASE/api/workers" | json 'sum(1 for w in d if w["alive"] and w["id"].startswith("d'$RUN'"))'; }

echo "== waiting for $BASE (a sleeping free host needs up to ~1 min)"
for _ in $(seq 60); do api "$BASE/api/health" | grep -q '"ok"' && break; sleep 2; done
api "$BASE/api/health"; echo

echo "== starting $N workers"
for i in $(seq "$N"); do
  "$PY" -m nexus.worker --url "$BASE" --name "w$i" --id "d$RUN-$i" --delay "$DELAY" >/dev/null & PIDS+=($!)
done
for _ in $(seq 30); do [ "$(workers_alive)" -ge "$N" ] && break; sleep 1; done
echo "workers connected: $(workers_alive)"

echo "== submitting a 192-tile Mandelbrot job"
JOB=$(api -X POST "$BASE/api/jobs" -d '{"type":"mandelbrot","params":{"width":640,"height":480,"tile":40,"max_iter":200,"cx":-0.7436,"cy":0.1318,"view_w":0.02}}' | json 'd["id"]')
state() { api "$BASE/api/jobs/$JOB" | json 'str(d["done"])+"/"+str(d["total"])+" "+d["state"]'; }
for _ in $(seq 120); do [ "$(api "$BASE/api/jobs/$JOB" | json 'd["done"]')" -ge 60 ] && break; sleep 0.5; done
echo "progress: $(state)"
echo "== killing worker w1 (pid ${PIDS[0]})"; kill -9 "${PIDS[0]}"
for _ in $(seq 240); do [ "$(api "$BASE/api/jobs/$JOB" | json 'd["state"]')" != running ] && break; sleep 0.5; done
echo "final: $(state)"
api "$BASE/api/workers" | json '"\n".join("  "+w["name"]+": "+("alive" if w["alive"] else "DEAD ")+"  tiles="+str(w["done"]) for w in d if w["id"].startswith("d'$RUN'"))'
echo "metrics: $(api "$BASE/api/metrics")"
