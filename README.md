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
- The desktop client is the dashboard page in a native window ([pywebview](https://pywebview.flowrl.com/)) with the Python worker running beside it. The **My Worker** view (load gauge, current task with live tile preview, stats, connection settings, activity log) talks to that local worker; **Observer** shows the whole cluster. The page is bundled in the executable, so it opens even while a free host is asleep (the window then shows the "waking up" screen). Run from source: `pip install -r requirements-client.txt && python -m nexus.desktop`.
- Packaged single-file clients, [v0.1.0 release](https://github.com/LoPHarp/nexus-grid/releases/tag/v0.1.0) (built by CI; the release currently holds the first, Tk-based build, see Known limitations):
  - [Windows](https://github.com/LoPHarp/nexus-grid/releases/download/v0.1.0/nexus-worker-Windows.exe)
  - [macOS, Apple silicon](https://github.com/LoPHarp/nexus-grid/releases/download/v0.1.0/nexus-worker-macOS)
  - [Linux x86-64](https://github.com/LoPHarp/nexus-grid/releases/download/v0.1.0/nexus-worker-Linux)

  **Build status:** the Linux binary was built by CI and I ran it by hand. **The Windows and macOS binaries were produced by CI (GitHub Actions) and have not been run manually.** None are code-signed.
- Run the client: start it, open **My Worker**, enter the server URL (`https://nexus-grid-2ivy.onrender.com`) press Connect (the public demo server needs no key; a key field is there only for servers started with `NEXUS_API_KEY`). Flags: `--url`, `--key`, `--name`, `--autoconnect`.
  - Windows: double-click; SmartScreen shows "unknown publisher": More info -> Run anyway.
  - macOS: `chmod +x nexus-worker-macOS && xattr -d com.apple.quarantine nexus-worker-macOS && ./nexus-worker-macOS`.
  - Linux: `chmod +x nexus-worker-Linux && ./nexus-worker-Linux` (needs a desktop session).
- Rebuild locally: `tools/build_client.sh` (current OS only). CI: `.github/workflows/build-client.yml`, runs on `v*` tags and manually.
- Headless worker: `python -m nexus.worker --url https://nexus-grid-2ivy.onrender.com` (no key needed on the public server; for a keyed server set `NEXUS_API_KEY` in the environment or an untracked `.env`, never commit it).
- Image batch (resize to fit `max_side`, re-compress, convert JPEG/PNG/WEBP): `python tools/submit_images.py ./photos --max-side 800 --format WEBP --out out`, or choose **Image Batch** in the dashboard's Active Job panel and press **+ New**.

## UI
Implements `docs/design/DESIGN.md` (layout, tokens, motion, states, compact layout, reduced motion) in `web/` (plain HTML, CSS, JS; Inter and JetBrains Mono bundled, OFL). Screenshots taken with headless Chrome from this build, next to the reference screens: [observer](docs/ui-check/observer.png), [failover](docs/ui-check/failover.png), [my-worker](docs/ui-check/my-worker.png) (rendered with a stub of the desktop API, since a browser has no local worker), [compact](docs/ui-check/compact.png). Differences from the concept art are listed under Known limitations.

## Demo
`set -a; . ./.env; set +a; demo/demo.sh` runs the whole scenario against `NEXUS_URL` (default: local server): 4 workers connect, a 192-tile Mandelbrot job renders, one worker is killed, its tiles are re-assigned, the job completes and a worker table is printed. Or press **Demo Mode** on the dashboard. Recording script: [docs/DEMO.md](docs/DEMO.md).

## AI features and roadmap
**Implemented: Ask the cluster** (sparkle button in the top bar, or `POST /api/ask`). Questions about the live cluster are answered in this order: response cache (60 s, keyed by question + coarse state) -> a free model through FreeLLMAPI, a local router to free models (OpenAI-compatible; enabled with `FREELLMAPI_URL`, `FREELLMAPI_KEY`, optional `FREELLMAPI_MODEL`) -> answers recorded from a free model in `data/ai_seed.json` -> rule-based answer from the same facts. The `source` field and the UI label say which one answered, so a slow or rate-limited model never breaks the demo. Model calls are limited to 6 per minute, the endpoint to 30. Only counts, worker names, sensor values and event names are sent to the model, never keys or file contents.

Roadmap (not built):
1. Smart scheduler: predict task duration per worker from past latencies and assign by expected finish time.
2. Anomaly detection on worker metrics (overheating, rising latency before a crash) with an alert in the event feed.
3. Richer questions: pass metric history to the model instead of a snapshot, and let it reference tiles and jobs.

## Evidence
| Claim | Command |
|---|---|
| Queue, priorities, heartbeat timeout, reassignment, stale results, retry limit | `.venv/bin/python -m pytest tests/test_core.py` |
| Same scenario against the public server (4 workers, kill 1, 192/192 done) | `NEXUS_URL=https://nexus-grid-2ivy.onrender.com demo/demo.sh` (no key) |
| Real processes: a worker is killed mid-job and the job still completes | `.venv/bin/python -m pytest tests/test_failover.py` or `demo/failover.sh` |
| Workers reconnect after a server restart | `tests/test_failover.py::test_worker_reconnects_after_server_restart` |
| Optional `X-API-Key` (only when the server sets `NEXUS_API_KEY`) is enforced on job writes and on the worker socket; history endpoint records metrics | `tests/test_auth_history.py` |
| Public deployment works end to end | `.venv/bin/python -m nexus.worker --url https://nexus-grid-2ivy.onrender.com`, then `POST /api/jobs` (no key) (see `DEVLOG.md`, Stage 3 for the recorded run) |
| Image batch: resize, convert, zip download, bytes not stored in the job record | `tests/test_image.py` |
| The desktop window loads the bundled page, connects and appears as a worker | `python -m nexus.desktop --url http://localhost:8000 --autoconnect --selftest 7` prints a DOM probe |
| Ask the cluster: cache, model failure fallback, rate limit, recorded answers | `tests/test_ai.py`, `tests/test_failover.py::test_ask_endpoint_without_model_uses_recorded_or_rules` |
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
- Ask the cluster: the live model path (HTTP to FreeLLMAPI) is covered by unit tests with a fake model only; I had no FreeLLMAPI HTTP key in this environment. The recorded answers (6, for 3 cluster states x 2 questions) came from real free-model calls through the MCP server. The public Render server has no model, so it answers from recorded answers or rules. Free reasoning models often truncated their output; only complete replies were kept.
- UI vs concept art: the mosaic shows the real 192 tiles (16x12), not the 36 large tiles of the mockup; event times are 24 h `HH:MM:SS`; job priority is shown, not editable; the key is the only credential and lives in browser/desktop storage. Server-sleep and error screens were checked by simulating an unreachable server; the 60 s Render cold start itself was not timed against the new screen.
- The Linux client bundles Qt WebEngine and is about 250 MB; Windows and macOS use the system web view. The `v0.1.0` release assets are the earlier Tk build until a new tag is cut.
- The executable is built per OS in CI; I could only run the Linux build myself. The CI run (build-client, `workflow_dispatch`) built all three; Windows and macOS executables have not been launched by hand.
- One task per worker at a time; the public demo server runs open (no key), so anyone can submit jobs and connect workers; the optional single shared key (`NEXUS_API_KEY`) is the only access control and there are no per-user accounts.
- Not load-tested beyond a handful of local workers.

## Roadmap
desktop worker window and image-batch tasks (4), deploy and demo (5), one small AI feature (6).
