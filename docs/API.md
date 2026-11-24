# API

Interactive REST docs (OpenAPI / Swagger UI): `/docs`; schema: `/openapi.json`.
Public instance: https://nexus-grid-2ivy.onrender.com

## Access key (optional)
The public demo server runs **open: no key is needed**. Key support is an optional feature: when a server starts with `NEXUS_API_KEY=<secret>`, these need the header `X-API-Key: <secret>`:
`POST /api/jobs`, `DELETE /api/jobs/{id}`, and the worker WebSocket `/ws/worker`. Everything else is read-only or Demo Mode and stays open. Without the variable the server runs open (local development). Wrong or missing key: HTTP 401 (REST) or 403 during the WebSocket handshake.

CORS is open (any origin, no cookies), because the desktop client serves the page from local files.

## REST
| Method, path | Purpose |
|---|---|
| `POST /api/jobs` | submit `{"type":"mandelbrot","params":{...},"priority":0}`; returns the job (201) |
| `GET /api/jobs`, `GET /api/jobs/{id}` | job list (newest first) / one job: `state` is `running`, `done`, `failed` or `aborted` |
| `DELETE /api/jobs/{id}` | cancel and delete |
| `GET /api/jobs/{id}/tiles`, `GET /api/tiles/{task_id}` | finished tiles of a job / one tile as a binary frame ([format](ARCHITECTURE.md#packet-format)); kept in memory only |
| `GET /api/tasks/{id}/result`, `GET /api/jobs/{id}/download` | processed file of an image task / zip of a finished image job (memory only) |
| `GET /api/workers` | workers with `alive`, `busy`, `done`, latest sensors |
| `GET /api/metrics` | now: workers alive/total, queue depth, tasks/s, running jobs, jobs done |
| `GET /api/metrics/history?seconds=300` | one point per second, up to the last hour (in memory) |
| `POST /api/ask` `{"question": "..."}`, `GET /api/ask/suggestions` | ask about the cluster; returns `answer` and `source` (`cache`, `model`, `recorded`, `rules`); 30 questions per minute |
| `GET /api/health` | liveness |
| `POST /api/demo?workers=4`, `POST /api/workers/{id}/kill` | Demo Mode: start local demo workers and a job; kill a demo worker (404 for any worker not started by Demo Mode; the dashboard marks killable workers with `demo: true` in `/api/workers`). `/api/demo` is limited to one call per 3 s |

Image batch params: `images` `[{name, data(base64)}]`, `max_side` 1024 (16..8192), `format` `JPEG|PNG|WEBP`, `quality` 80. Fetch results with `GET /api/tasks/{task_id}/result` or `GET /api/jobs/{id}/download` (zip). Limits: 50 images, 5 MB each, 25 MB total.

Mandelbrot params (defaults): `width` 800, `height` 600 (1..4096), `tile` 100 (8..512), `max_iter` 200 (1..5000), `cx` -0.5, `cy` 0, `view_w` 3.0. One tile = one task.

```bash
curl -X POST $URL/api/jobs -H 'Content-Type: application/json' \   # add -H "X-API-Key: $KEY" only if the server sets a key
  -d '{"type":"mandelbrot","params":{"width":640,"height":480,"tile":80}}'
curl $URL/api/jobs/1
```

## WebSocket `/ws/events` (open, server -> client, JSON)
First message `{"e":"snapshot","workers":[...],"jobs":[...]}`, then events `e`:
`job_created`, `job_done`, `job_failed`, `job_deleted`, `worker_joined`, `worker_lost` (`reason`, `requeued` task ids), `task_assigned` (`task_id`, `worker_id`, `tile`, `attempt`), `task_done` (adds `latency_ms`, `done`, `total`), `metrics` (`worker_id`, `metrics`, `queue`). Slow consumers that fall 1000 events behind are dropped; reconnect to continue.

## WebSocket `/ws/worker`
Worker protocol and the binary result frame: see [ARCHITECTURE.md](ARCHITECTURE.md#packet-format). Start: `python -m nexus.worker --url https://HOST` (add `--key $KEY` only for a keyed server).
