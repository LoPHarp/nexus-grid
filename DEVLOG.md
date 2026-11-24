# Development log

## 2026-11-24 - Stage 0/1: setup and core
- Done: repo + first commit (prompt, task, plan, rules); `tools/log_tokens.sh` for real token counts; server, worker, scheduler, Mandelbrot handler, SQLite history, Dockerfile, 11 tests, `demo/failover.sh`.
- Why: single asyncio loop, one task per worker, so scheduling needs no locks; JSON control + binary tile frames.
- Failures fixed: sync FastAPI handlers ran in a thread pool, where `get_running_loop()` failed (HTTP 500 on `POST /api/jobs`) and the scheduler was not thread-safe -> all handlers are `async`. One unit test wrongly expected a re-queued task to reach a busy worker -> test fixed.
- Result: `pytest` 11 passed; failover demo: killed 1 of 3 workers at 18/32 tiles, job finished 32/32 on the others.
- Tokens: see `TOKEN_LOG.md`. Delegated to free models: nothing (all work was design or test-critical).
- Render free: WebSockets are supported, since 2026-02 WS messages count as activity; community reports of ~5 min drops are unconfirmed, so the worker reconnects regardless. Not yet verified on a real deploy.

## 2026-11-24 - Stage 2: dashboard
- Done: `web/index.html` (mosaic with worker tint, worker graph with pulses and red dead node, 5 charts, HUD, Demo Mode), `POST /api/demo`, `POST /api/workers/{id}/kill`, task latency in `task_done` events, job params normalized so the page knows the tile geometry.
- Why: plain canvas and no JS libraries (nothing to bundle or download); demo workers are server subprocesses so the public demo works without a desktop client.
- Checked: headless Chrome screenshot (`docs/dashboard.png`) after Demo Mode + killing one worker: mosaic filling, dead node red, HUD live. Not checked: Firefox/Safari, phone layout by eye.
- Result: `pytest` 12 passed (new: static page, demo endpoint, kill, binary tile fetch).
- Delegated to free models: nothing.

## 2026-11-24 - Stage 3: API
- Done: `X-API-Key` (env `NEXUS_API_KEY`) on `POST/DELETE /api/jobs` and `/ws/worker`; `GET /api/metrics/history`; typed OpenAPI models, tags, Authorize button; `docs/API.md`; dashboard charts prefilled from history; `/api/demo` limited to 1 call per 3 s.
- Why: only writes and the worker socket are keyed, so the public dashboard and Demo Mode work for viewers while nobody can inject jobs or fake workers. Key unset = open dev mode.
- Public check (Render, Stage 2 build, no key set yet): local worker over `wss://`, 320x240 job = 48 tiles, done in ~14 s; socket stayed connected with no reconnect for the 10+ minutes it was watched.
- Result: `pytest` 14 passed (new: key enforcement, rejected worker, history).
- TODO for Denys: set `NEXUS_API_KEY` in the Render environment, otherwise the public server stays open.
- Delegated to free models: nothing.
