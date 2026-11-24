# Initial prompt

This is the prompt the development started from (saved as required by the task). It is pasted unchanged as the first message to Claude Code.

---

I am building a client-server prototype called **Nexus Grid** as a practical task for an AI Developer position. The whole project must be built with AI (you), and I must minimize token usage and keep a log of actual token spend.

First read these files in this folder: `TASK.md`, `PLAN.md`, `CLAUDE.md`. They contain the task requirements, the project plan and the working rules. Follow them.

Project in short: a distributed computing platform. A server (Python, FastAPI, WebSocket) distributes tasks to connected workers (desktop clients), collects results, survives a worker crash by reassigning its tasks, and shows everything on a live web dashboard. It has its own documented REST and WebSocket API. Task types: Mandelbrot fractal tiles (visual demo) and image batch processing (practical use).

Rules for this session:
1. Do not write any code before this prompt is saved as `PROMPT.md` in the repository and committed as the first commit.
2. Work in the stages from `PLAN.md`, starting with Stage 1 (core). Do one stage at a time and stop for my review after each stage.
3. Commit after every logical step. Commit messages in English. End every commit message with this trailer on its own line: `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
4. Keep token usage low: short answers, no long explanations, read only the files you need, do not re-print files you wrote, do not repeat plans.
5. Delegate simple routine work (boilerplate, test data, formatting, simple text) to the free models through the `freellmapi` MCP server as described in `CLAUDE.md`. Review their output before using it.
6. Before the first stage, check which tool gives real token counts for this project (see `CLAUDE.md`, section Token log) and set it up. Report to me in two lines what you chose.

7. Keep a short development log in `DEVLOG.md` (one entry per stage or decision, including failures and fixes) and make the repository easy to verify (tests, a failover demo script, an Evidence section in the README), as described in `CLAUDE.md`.

Start now: first confirm you have read the three files (one line), then do rule 1 and rule 6.
