#!/usr/bin/env bash
# Append a dated snapshot of real Claude Code token usage for THIS project to TOKEN_LOG.md.
# Source: ~/.claude/projects/<project>/*.jsonl (usage fields written by Claude Code), de-duplicated by message id.
# Usage: tools/log_tokens.sh "<stage label>"
set -euo pipefail
cd "$(dirname "$0")/.."
STAGE="${1:-snapshot}"
DIR="$HOME/.claude/projects/$(pwd | sed 's#[^A-Za-z0-9]#-#g')"
python3 -I - "$DIR" "$STAGE" <<'PY'
import json, glob, sys, datetime
d, stage = sys.argv[1], sys.argv[2]
best = {}
for p in glob.glob(d + "/**/*.jsonl", recursive=True):
    for line in open(p, encoding="utf-8"):
        try: o = json.loads(line)
        except ValueError: continue
        m = o.get("message") or {}
        u = m.get("usage")
        if not u or o.get("type") != "assistant": continue
        k = m.get("id") or o.get("uuid")
        if k not in best or u.get("output_tokens", 0) >= best[k].get("output_tokens", 0):
            best[k] = u
inp = sum(u.get("input_tokens", 0) for u in best.values())
out = sum(u.get("output_tokens", 0) for u in best.values())
cw = sum(u.get("cache_creation_input_tokens", 0) for u in best.values())
cr = sum(u.get("cache_read_input_tokens", 0) for u in best.values())
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
row = f"| {now} | {stage} | {inp:,} | {out:,} | {cw:,} write / {cr:,} read | {inp+out+cw+cr:,} | project jsonl, {len(best)} msgs |\n"
lines = open("TOKEN_LOG.md", encoding="utf-8").read().split("\n")
i = next(n for n, l in enumerate(lines) if l.startswith("|---|---|---|---|---|---|---|"))
lines.insert(i + 1, row.rstrip("\n"))
open("TOKEN_LOG.md", "w", encoding="utf-8").write("\n".join(lines))
print(row, end="")
PY
