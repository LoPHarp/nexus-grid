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

## 2026-11-24 - Stage 4: desktop worker and image batch
- Done: `nexus/tasks/image.py` (Pillow), binary frame type 2, zip download, `tools/submit_images.py`, `nexus/gui.py` (tkinter window), `tools/build_client.sh` (PyInstaller, 36 MB Linux binary), CI workflow for Linux/Windows/macOS. Access key moved to untracked `.env` (verified: not in tracked files or git history).
- Why: tkinter is in the standard library (no extra dependency); images travel as base64 JSON because it needs no multipart dependency; handler interface gained `summary()` and `pack()` so job records never hold image bytes.
- Failures fixed: worker CLI did not turn `https://` into `wss://` (found when testing against the public URL, reconnect loop with InvalidURI) -> shared `to_ws()`. The public server still ran the Stage 3 build, so the public image test waits for the redeploy.
- Tested: `pytest` 22 passed; GUI and the packed Linux binary connected to a local server and the binary's worker took part in a job; local image job 3 files 9.3 MB -> 0.29 MB. No screenshot tool on this machine, so the window was checked by behaviour, not by eye. Windows/macOS builds not run yet.
- Delegated to free models: nothing.
- After push: Render redeployed; public image job (3 files, 9.3 MB -> 0.47 MB) through `wss://` worker + `tools/submit_images.py` with the key from `.env`: done. CI `build-client` run: Linux, Windows, macOS builds all succeeded (artifacts ~50/31/20 MB).

## 2026-11-24 - Stage 5: deploy and demo
- Done: `demo/demo.sh` (scenario for the video against any server, waits for a sleeping host), `docs/DEMO.md` (shot list), `worker_removed` event so dead nodes disappear from the dashboard after 60 s, release `v0.1.0` with Linux, Windows and macOS clients built by CI (tag push), README download links and run instructions.
- Public run (Render free): `demo/demo.sh` 4 workers, killed w1 at 64/192, finished 192/192 on the others (w2 59, w3 58, w4 58 tiles, w1 17). Dashboard Demo Mode button (4 server-side workers) also worked: the 512 MB instance stayed healthy. Screenshot of the public dashboard checked by eye.
- Fixed: CI release step needed `contents: write` and unique asset names per OS (added before tagging).
- Verified: the downloaded Linux release binary starts. Windows and macOS assets exist but were not run by hand.
- Not done yet: the video itself (Denys records it with docs/DEMO.md), the submission form.
- Delegated to free models: nothing.
