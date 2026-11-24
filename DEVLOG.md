# Development log

## 2026-11-24 - Stage 0/1: setup and core
- Done: repo + first commit (prompt, task, plan, rules); `tools/log_tokens.sh` for real token counts; server, worker, scheduler, Mandelbrot handler, SQLite history, Dockerfile, 11 tests, `demo/failover.sh`.
- Why: single asyncio loop, one task per worker, so scheduling needs no locks; JSON control + binary tile frames.
- Failures fixed: sync FastAPI handlers ran in a thread pool, where `get_running_loop()` failed (HTTP 500 on `POST /api/jobs`) and the scheduler was not thread-safe -> all handlers are `async`. One unit test wrongly expected a re-queued task to reach a busy worker -> test fixed.
- Result: `pytest` 11 passed; failover demo: killed 1 of 3 workers at 18/32 tiles, job finished 32/32 on the others.
- Tokens: see `TOKEN_LOG.md`. Delegated to free models: nothing (all work was design or test-critical).
- Render free: WebSockets are supported, since 2026-02 WS messages count as activity; community reports of ~5 min drops are unconfirmed, so the worker reconnects regardless. Not yet verified on a real deploy.
