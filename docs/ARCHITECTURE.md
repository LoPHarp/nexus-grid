# Architecture

```
 browser (dashboard, web/index.html) --WS /ws/events--+
 curl / API clients ---------- REST /api/* ----+--> [ FastAPI server ] --- SQLite (job history)
                                                      |  Scheduler: priority queue, worker registry,
                                                      |  heartbeat reaper, reassignment
                                       WS /ws/worker  |
                          +---------------------------+-----------------+
                       worker w1                   worker w2          worker w3
                  (computes tiles, 1 Hz heartbeat + sensors, auto-reconnect)
```

## Components
- `nexus/server.py` - REST API, `/ws/worker`, `/ws/events`. All handlers are `async` so the scheduler only ever runs on the event-loop thread (no locks).
- `nexus/scheduler.py` - jobs, tasks, workers. One task per worker at a time. Queue ordered by priority, then FIFO; re-queued tasks go to the front of their priority level.
- `nexus/tasks/` - task handlers. `split(params)` (server) turns a job into tasks, `compute(params)` (worker) runs one. A new task type is one module registered in `HANDLERS`.
- `nexus/worker.py` - connects, computes in a thread (so heartbeats continue during computation), reconnects with exponential backoff (1 s to 30 s, jittered).
- `web/` (`index.html`, `app.css`, `app.js`) - dashboard, no framework: HUD with odometer counters and sparklines, tile mosaic (DOM tiles with CSS animation), worker graph (HTML nodes, SVG links, Web Animations pulses), per-worker charts, event feed, My Worker view, connection states (sleeping, reconnecting, error). It reads `/ws/events`, fetches tile frames from `/api/tiles/{id}` and decodes them with `DecompressionStream`.
- `POST /api/demo`, `POST /api/workers/{id}/kill` - Demo Mode: the server spawns local worker processes and can kill them.
- `nexus/tasks/image.py` - image batch handler (Pillow). File results use binary frame type 2 (same header, payload = encoded image); `GET /api/jobs/{id}/download` zips them.
- `nexus/desktop.py`, `client.py` - desktop client: pywebview window (frameless, page loaded from `web/`) with a `LocalWorker` JS API (connect, disconnect, state, window controls) over the worker; `client.py` is the PyInstaller entry point. The page calls the server cross-origin (CORS is open, auth is a header).
- `nexus/ai.py` - Ask the cluster: state snapshot, cache key from a coarse state, FreeLLMAPI client (urllib), recorded answers `data/ai_seed.json`, rule-based fallback.
- `nexus/db.py` - job history in SQLite. Tile results are kept in memory only.

## Data flow
1. `POST /api/jobs` -> `split()` -> one task per tile -> queue.
2. A free worker is sent `{"t":"task",...}` (JSON). It computes and replies with one binary result frame.
3. The server stores the frame, updates the job, emits events, dispatches the next task.
4. When all tasks of a job are done the job becomes `done`.

## Packet format
JSON control messages `{"t": type, ...}`:
- worker -> server: `hello {worker_id, name, cpus}`, `heartbeat {metrics:{cpu,mem,temp?}}`, `error {task_id,msg}`
- server -> worker: `welcome {heartbeat_timeout}`, `task {task_id,type,params}`

Binary result frame (big endian header, then payload):

| offset | size | field |
|---|---|---|
| 0 | u8 | frame type (1 = result) |
| 1 | u32 | task id |
| 5 | u16 | width (px) |
| 7 | u16 | height (px) |
| 9 | n | type 1: zlib(uint16 little-endian iteration counts, row-major); type 2: encoded image file (JPEG/PNG/WEBP), width/height are then the output size |

## Failure handling
- A worker that disconnects, or sends nothing for `HEARTBEAT_TIMEOUT` seconds (default 5), is marked dead; its running task is re-queued at the front.
- A task is retried up to 5 times, then the job is marked `failed`.
- A result from a worker that no longer owns the task is ignored.
- Server restart (including a free-host sleep): workers reconnect by themselves. Jobs that were running are marked `aborted` on startup; they are not resumed.
