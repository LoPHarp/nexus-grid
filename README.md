# Nexus Grid

Distributed computing prototype: a FastAPI server hands tasks to connected workers, collects results, and re-assigns the tasks of a worker that dies. Includes a live web dashboard served by the same process.

![dashboard](docs/dashboard.png)

Open `http://localhost:8000/` and press **Demo Mode**: the server starts 4 local demo workers and a Mandelbrot job. Click a demo worker in the graph to kill it and watch its tile get re-assigned.

Live: https://nexus-grid-2ivy.onrender.com (dashboard at `/`, Swagger UI at `/docs`). The free instance sleeps after 15 minutes idle, the first request can take about a minute. API reference: [docs/API.md](docs/API.md).

## Run
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn nexus.server:app --port 8000                     # server (honours $PORT in Docker)
.venv/bin/python -m nexus.worker --url ws://localhost:8000/ws/worker --name w1   # worker, start several
curl -X POST localhost:8000/api/jobs -H 'Content-Type: application/json' \
  -d '{"type":"mandelbrot","params":{"width":800,"height":600,"tile":100}}'
```
Docker: `docker build -t nexus-grid . && docker run -p 8000:8000 -e PORT=8000 nexus-grid`. Architecture and packet format: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Desktop worker and image batch
- Desktop worker (status window, Python + tkinter): `python -m nexus.gui`, or the packaged single-file executable built by `tools/build_client.sh` (GitHub Actions builds Linux, Windows and macOS: Actions -> build-client -> Artifacts, or the Releases page for tagged versions). Enter the server URL and access key, press Connect. Not code-signed: Windows SmartScreen or macOS Gatekeeper will ask for confirmation.
- Headless worker: `set -a; . ./.env; set +a; python -m nexus.worker` (reads `NEXUS_URL`, `NEXUS_API_KEY`). Keep the key in an untracked `.env`.
- Image batch (resize to fit `max_side`, re-compress, convert JPEG/PNG/WEBP): `python tools/submit_images.py ./photos --max-side 800 --format WEBP --out out` sends the folder as one job (one task per image), waits and unpacks the results zip.

## Evidence
| Claim | Command |
|---|---|
| Queue, priorities, heartbeat timeout, reassignment, stale results, retry limit | `.venv/bin/python -m pytest tests/test_core.py` |
| Real processes: a worker is killed mid-job and the job still completes | `.venv/bin/python -m pytest tests/test_failover.py` or `demo/failover.sh` |
| Workers reconnect after a server restart | `tests/test_failover.py::test_worker_reconnects_after_server_restart` |
| `X-API-Key` is enforced on job writes and on the worker socket; history endpoint records metrics | `tests/test_auth_history.py` |
| Public deployment works end to end | `.venv/bin/python -m nexus.worker --url wss://nexus-grid-2ivy.onrender.com/ws/worker --key $KEY`, then `POST /api/jobs` (see `DEVLOG.md`, Stage 3 for the recorded run) |
| Image batch: resize, convert, zip download, bytes not stored in the job record | `tests/test_image.py` |
| Dashboard and Demo Mode endpoint are served and work | `tests/test_failover.py::test_dashboard_and_demo_endpoint`, or open `/` |
| Actual token spend | `TOKEN_LOG.md`, produced by `tools/log_tokens.sh` |
| Prompt the work started from | `PROMPT.md` |

## Known limitations
- SQLite is ephemeral on Render's free plan (no persistent disk): job history is lost on restart or redeploy.
- Tile results are held in memory only; running jobs are marked `aborted` after a server restart.
- A free Render service sleeps after 15 minutes without traffic and needs about a minute to wake; workers retry with backoff until it is back. Free-tier WebSocket connections may also be dropped by the platform; workers reconnect.
- Metrics history is in memory (last hour); lost on restart.
- Demo Mode workers run as subprocesses of the server, so on a small free instance they compete with it for CPU.
- Image batch sends files inside JSON (base64): at most 50 images, 5 MB each, 25 MB per job. Results are kept in memory and lost on restart; download them soon after the job ends.
- The executable is built per OS in CI; I could only run the Linux build myself. Windows and macOS builds are untested by hand.
- One task per worker at a time; a single shared access key, no per-user accounts; reads, `/ws/events` and Demo Mode are open by design so the public demo works.
- Not load-tested beyond a handful of local workers.

## Roadmap
desktop worker window and image-batch tasks (4), deploy and demo (5), one small AI feature (6).
