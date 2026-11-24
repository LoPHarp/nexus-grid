"""Ask the cluster: natural-language questions about the current cluster state.

Answer order: response cache -> model (FreeLLMAPI, OpenAI-compatible, only if FREELLMAPI_URL is set)
-> recorded answers (data/ai_seed.json) -> rule-based answer. The demo therefore keeps working when the
free model is slow, rate-limited or not reachable (for example on the public host)."""
import hashlib
import json
import os
import re
import time
import urllib.request
from pathlib import Path

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "ai_seed.json"
CACHE_TTL = 60.0
MAX_Q = 300
SYSTEM = ("You are the operations assistant of Nexus Grid, a distributed compute cluster. "
          "Answer in at most 3 short plain-text sentences, using only the facts given. "
          "If the facts do not contain the answer, say so. Do not invent numbers or worker names.")
SUGGESTIONS = ["Is the cluster healthy?", "Which worker is slowest?", "Why is the queue growing?", "What happened to the last job?"]


def normalize(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", q.lower())).strip()


def snapshot(sched, events) -> dict:
    """Compact facts from the live scheduler (no secrets, no file contents)."""
    ws = list(sched.workers.values())
    job = max(sched.jobs.values(), key=lambda j: j["id"], default=None)
    return {
        "workers": [{"name": w.name, "alive": w.alive, "done": w.done, "cpu": w.metrics.get("cpu"), "mem": w.metrics.get("mem"),
                     "temp": w.metrics.get("temp"), "lat": w.last_latency_ms} for w in ws],
        "queue": sched.queue_depth(), "tps": round(sched.throughput(), 1),
        "job": job and {"id": job["id"], "type": job["type"], "state": job["state"], "done": job["done"], "total": job["total"]},
        "events": list(events)[-8:]}


def canon(s: dict) -> dict:
    """The part of the state that decides whether a cached/recorded answer still applies."""
    alive = sum(1 for w in s["workers"] if w["alive"])
    return {"alive": alive, "total": len(s["workers"]), "job": s["job"]["state"] if s["job"] else None}


def key_for(question: str, c: dict) -> str:
    return hashlib.sha256((normalize(question) + "|" + json.dumps(c, sort_keys=True)).encode()).hexdigest()[:24]


def facts_min(c: dict) -> str:
    lost = c["total"] - c["alive"]
    return (f"Workers: {c['alive']} of {c['total']} alive" + (f" ({lost} lost)" if lost else "") + ". "
            f"Latest job: {c['job'] or 'none'}. Per-worker figures are not part of these facts.")


def facts_full(s: dict) -> str:
    c = canon(s)
    lines = [facts_min(c).replace(" Per-worker figures are not part of these facts.", "")]
    for w in s["workers"]:
        lines.append(f"- {w['name']}: {'alive' if w['alive'] else 'LOST'}, tasks done {w['done']}, cpu {w['cpu']}%, mem {w['mem']}%"
                     + (f", temp {w['temp']}C" if w["temp"] is not None else "") + f", last task latency {w['lat']}ms")
    lines.append(f"Queue depth {s['queue']}, throughput {s['tps']} tasks/s.")
    if s["job"]:
        j = s["job"]
        lines.append(f"Latest job #{j['id']} ({j['type']}): {j['state']}, {j['done']}/{j['total']} tasks.")
    if s["events"]:
        lines.append("Recent events: " + "; ".join(s["events"]))
    return "\n".join(lines)


def rules_answer(question: str, s: dict) -> str:
    q, c, ws = normalize(question), canon(s), s["workers"]
    alive = [w for w in ws if w["alive"]]
    lost = [w["name"] for w in ws if not w["alive"]]
    if not ws:
        return "No workers are connected, so nothing can be computed. Start a worker or press Demo Mode."
    if re.search(r"slow|latenc|laggi", q):
        w = max(alive, key=lambda x: x["lat"], default=None)
        return f"{w['name']} has the highest last-task latency ({w['lat']} ms)." if w and w["lat"] else "No task latencies have been recorded yet."
    if re.search(r"queue|backlog|pending", q):
        return (f"{s['queue']} tasks are waiting; {len(alive)} workers are processing about {s['tps']} tasks/s"
                + (f", and {', '.join(lost)} is lost, which lowers throughput." if lost else "."))
    if re.search(r"job|progress|finish|done|last", q):
        j = s["job"]
        return f"Job #{j['id']} ({j['type']}) is {j['state']}: {j['done']}/{j['total']} tasks done." if j else "No job has been submitted yet."
    if re.search(r"dead|lost|fail|offline|crash|down", q):
        return f"Lost workers: {', '.join(lost)}." if lost else "No workers are lost."
    base = f"{c['alive']} of {c['total']} workers alive" + (f"; lost: {', '.join(lost)}" if lost else "") + f". Queue {s['queue']}, {s['tps']} tasks/s."
    return ("Degraded. " if lost else "Healthy. ") + base


class Advisor:
    def __init__(self, get_snapshot, model_call=None, seed_file=SEED_FILE):
        self.get_snapshot, self.model_call = get_snapshot, model_call
        self.cache: dict[str, tuple[float, dict]] = {}
        self.calls: list[float] = []
        try:
            self.seed = json.loads(Path(seed_file).read_text())
        except (OSError, ValueError):
            self.seed = {}

    def _rate_ok(self, limit=6, window=60.0) -> bool:
        now = time.monotonic()
        self.calls = [t for t in self.calls if now - t < window]
        if len(self.calls) >= limit:
            return False
        self.calls.append(now)
        return True

    def ask(self, question: str) -> dict:
        question = question.strip()[:MAX_Q]
        s = self.get_snapshot(); c = canon(s); k = key_for(question, c)
        hit = self.cache.get(k)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return {**hit[1], "source": "cache"}
        if self.model_call and self._rate_ok():
            try:
                text, model = self.model_call(SYSTEM, f"Facts:\n{facts_full(s)}\n\nQuestion: {question}")
                res = {"answer": text.strip(), "source": "model", "model": model}
                self.cache[k] = (time.monotonic(), {"answer": res["answer"], "model": model})
                return res
            except Exception as e:                                   # slow, rate limited, unreachable: fall through
                fallback_note = type(e).__name__
        else:
            fallback_note = "model not available"
        rec = self.seed.get(k)
        if rec:
            return {"answer": rec["answer"], "source": "recorded", "model": rec.get("model")}
        return {"answer": rules_answer(question, s), "source": "rules", "note": fallback_note}


def freellmapi_call(url: str, key: str, model: str = "auto", timeout: float = 25.0):
    """Returns a model_call(system, user) -> (text, model_name) for an OpenAI-compatible endpoint."""
    def call(system: str, user: str):
        body = json.dumps({"model": model, "temperature": 0.2, "max_tokens": 220,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return d["choices"][0]["message"]["content"], d.get("model", model)
    return call


def from_env(get_snapshot) -> Advisor:
    url, key = os.environ.get("FREELLMAPI_URL", ""), os.environ.get("FREELLMAPI_KEY", "")
    call = freellmapi_call(url, key, os.environ.get("FREELLMAPI_MODEL", "auto")) if url and key else None
    return Advisor(get_snapshot, call)
