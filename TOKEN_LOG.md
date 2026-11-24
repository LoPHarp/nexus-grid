# Token log

Actual token spend for building Nexus Grid with Claude Code. Numbers are taken from tool output, not estimated.

## How it is measured
- Claude Code usage: `tools/log_tokens.sh "<stage>"` sums the `usage` fields that Claude Code writes to `~/.claude/projects/<this project>/*.jsonl` (de-duplicated by message id). Total = input + output + cache write + cache read. Verified against `npx ccusage` (v20.1.1): same source files, but ccusage has no per-project filter, so it mixes all projects on this machine and is used only as a cross-check.
- Cache reads dominate the total; they are billed at a fraction of normal input price, so the Total column overstates cost. Input/Output are the uncached counts.
- Delegated calls to free models: FreeLLMAPI panel, Analytics (numbers recorded below)

## Snapshots
| Date/time | Stage | Input | Output | Cache | Total | Source |
|---|---|---|---|---|---|---|
| 2026-11-24 12:23 | Stage 5 (deploy, demo, release) | 132 | 88,891 | 127,948 write / 6,163,501 read | 6,380,472 | project jsonl, 61 msgs |
| 2026-11-24 12:04 | Stage 4 end (public check, CI) | 116 | 81,270 | 118,012 write / 5,132,812 read | 5,332,210 | project jsonl, 54 msgs |
| 2026-11-24 12:01 | Stage 4 (desktop worker, image batch) | 106 | 79,889 | 113,290 write / 4,423,861 read | 4,617,146 | project jsonl, 49 msgs |
| 2026-11-24 11:49 | Stage 3 (API) | 78 | 57,251 | 90,170 write / 2,770,002 read | 2,917,501 | project jsonl, 36 msgs |
| 2026-11-24 11:42 | Stage 2 (dashboard) | 62 | 44,106 | 77,092 write / 2,024,567 read | 2,145,827 | project jsonl, 29 msgs |
| 2026-11-24 11:25 | Stage 1 (core) | 40 | 23,431 | 53,941 write / 1,115,366 read | 1,192,778 | project jsonl, 19 msgs |
| 2026-11-24 11:13 | Stage 0 (setup) | 14 | 1,988 | 29,121 write / 332,198 read | 363,321 | project jsonl, 7 msgs |

## Free-model (FreeLLMAPI) usage
| Date/time | Tasks delegated | Requests | Tokens | Models |
|---|---|---|---|---|

## Notes
- Planning conversations with Claude in the chat app (choosing the idea, setting up the free-model router) happened outside Claude Code and are not included in the Claude Code numbers.
