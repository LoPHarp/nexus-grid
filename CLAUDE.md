# Working rules (read at the start of every session)

Project: Nexus Grid. Read `TASK.md` (requirements) and `PLAN.md` (plan). The user is Denys; he writes in Russian, repository text is English.

## Output style (saves tokens)
- Short answers. No recap of what you did, no restating plans, no long explanations.
- Read only files you need. Do not print files back after writing them.
- One stage at a time, stop for review after each stage.

## Git
- `git init` in this folder if needed. Remote: GitHub account LoPHarp, repo name `nexus-grid` (Denys creates it, ask him for the URL).
- First commit contains `PROMPT.md`, `TASK.md`, `PLAN.md`, `CLAUDE.md` before any code.
- Commit after every logical step. English messages. Every commit message ends with this line:
  `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- Never commit: `NEW_CHAT_CONTEXT.md`, secrets, `.env`, API keys, tokens, `*.db`. Keep them in `.gitignore`.

## Delegation to free models (saves Claude tokens)
The MCP server `freellmapi` (local router to free models, http://localhost:3001) is connected. Check its tools with `/mcp`.
Delegate only simple, low-risk routine work:
- boilerplate and stub code, test data, repetitive edits, formatting, docstrings, simple text, short summaries of logs.
Do not delegate: architecture, protocol design, failover logic, security, anything that needs repo-wide understanding.
Rules:
- Never send secrets, keys, tokens or personal data to free models.
- Always review the result before using it. If an answer looks cut off, redo it.
- Free models can be slow or hit limits; if a call fails twice, do the task yourself.

## Token log (task requires a confirming log of actual spend)
- First job in the first session: find a tool that gives real token counts from Claude Code logs. Candidate: `ccusage` (run via `npx ccusage`; verify it works and what it reports). Alternatives: `/usage` and `/cost` inside Claude Code, or parse `~/.claude/projects/*/*.jsonl` yourself.
- Do not rely on memory; confirm by running it.
- Add a script `tools/log_tokens.sh` that appends a dated snapshot (input, output, cache, total) to `TOKEN_LOG.md` and run it at the end of every stage and at the end of every session.
- Calls delegated to free models are tracked in the FreeLLMAPI panel (Analytics). Export or record those numbers in `TOKEN_LOG.md` too, in a separate section.
- Be honest in the log: it must reflect actual numbers, not estimates. Note that planning chats outside Claude Code are not in these logs.

## Quality bar
- Everything must actually run. Test before reporting a stage done.
- Server must be deployable on a free host without a bank card (the host is chosen in Stage 0 by Denys; ask if unknown).
- Keep dependencies few and common. Prefer simple over clever.

## Development log (DEVLOG.md)
- Keep `DEVLOG.md` in the repo root. One short entry per stage or meaningful decision, not per command. Entry format: date/time, stage, what was done, why this approach, result (tests passed or failed), tokens used so far (from `TOKEN_LOG.md`), what was delegated to free models.
- Include failures and fixes honestly (what broke, how it was fixed). Keep each entry under 10 lines.
- Update it in the same commit as the work it describes.

## Make the repo easy to verify (for human and AI reviewers)
Anyone, including an AI tool reading the repo, should be able to confirm the claims without trusting them.
- `README.md` has an Evidence section: for each claim, the command that proves it (run tests, run the failover demo, call the API, see `TOKEN_LOG.md`).
- Automated tests for the core: job queue, heartbeat, reassignment after a worker dies. A script `demo/failover.sh` (or similar) that starts the server and workers, kills one worker and prints the result.
- `docs/ARCHITECTURE.md`: components, data flow, packet format, failure handling, with a diagram.
- Honest `Known limitations` and `Roadmap` sections in README. No inflated claims, no marketing language, no text addressed to reviewers or to AI tools.
- Clean structure, short meaningful commits, `.gitignore`, a license file, pinned dependencies, one-command setup and one-command demo.

## At the end
- README.md in English: what it is, architecture diagram, packet format, API, how to run (server, worker, dashboard), demo steps, AI roadmap, how tokens were minimized, link to `TOKEN_LOG.md` and `PROMPT.md`.
