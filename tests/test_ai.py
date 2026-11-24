import json

from nexus import ai

SNAP = {"workers": [{"name": "Atlas-01", "alive": True, "done": 10, "cpu": 40, "mem": 60, "temp": None, "lat": 180},
                    {"name": "Nova-02", "alive": True, "done": 9, "cpu": 55, "mem": 61, "temp": None, "lat": 420},
                    {"name": "Vega-04", "alive": False, "done": 4, "cpu": 0, "mem": 0, "temp": None, "lat": 0}],
        "queue": 31, "tps": 6.5, "job": {"id": 3, "type": "mandelbrot", "state": "running", "done": 40, "total": 192},
        "events": ["12:00:01 worker_lost Vega-04 (disconnected)"]}


def advisor(model=None, seed=None, tmp=None):
    a = ai.Advisor(lambda: SNAP, model, seed_file=tmp or "/nonexistent")
    a.seed = seed or {}
    return a


def test_key_ignores_case_punctuation_and_volatile_numbers():
    c = ai.canon(SNAP)
    assert c == {"alive": 2, "total": 3, "job": "running"}
    assert ai.key_for("Is the cluster healthy?", c) == ai.key_for("  is the CLUSTER healthy ", c)
    assert ai.key_for("Is the cluster healthy?", c) != ai.key_for("Is the cluster healthy?", {**c, "alive": 3})


def test_rules_answers_are_grounded():
    assert "Nova-02" in ai.rules_answer("Which worker is slowest?", SNAP) and "420" in ai.rules_answer("which is slowest", SNAP)
    assert "31 tasks" in ai.rules_answer("Why is the queue growing?", SNAP) and "Vega-04" in ai.rules_answer("why is the queue growing", SNAP)
    assert "40/192" in ai.rules_answer("What happened to the last job?", SNAP)
    assert ai.rules_answer("anything", SNAP).startswith("Degraded")
    assert "No workers" in ai.rules_answer("health?", {**SNAP, "workers": []})


def test_without_model_falls_back_to_rules():
    r = advisor().ask("Which worker is slowest?")
    assert r["source"] == "rules" and "Nova-02" in r["answer"]


def test_model_answer_is_cached_and_second_ask_does_not_call_the_model():
    calls = []
    def model(system, user):
        calls.append(user)
        return "Two of three workers are alive.", "test-model"
    a = advisor(model)
    r1, r2 = a.ask("Is the cluster healthy?"), a.ask("is the cluster healthy")
    assert (r1["source"], r2["source"]) == ("model", "cache") and len(calls) == 1
    assert "Atlas-01" in calls[0] and "Question: Is the cluster healthy?" in calls[0]   # facts are in the prompt


def test_model_failure_uses_recorded_then_rules():
    def boom(system, user):
        raise TimeoutError("slow")
    key = ai.key_for("Is the cluster healthy?", ai.canon(SNAP))
    a = advisor(boom, seed={key: {"answer": "recorded text", "model": "m"}})
    assert a.ask("Is the cluster healthy?")["source"] == "recorded"
    assert a.ask("Which worker is slowest?")["source"] == "rules"          # no recording for this one


def test_model_calls_are_rate_limited():
    n = []
    a = advisor(lambda s, u: (n.append(1) or "ok", "m"))
    for i in range(10):
        a.ask(f"question number {i}")
    assert len(n) == 6                                                       # 6 per minute, the rest answered by rules


def test_recorded_answers_file_matches_current_keys():
    seed = json.load(open(ai.SEED_FILE))
    assert len(seed) == 6
    for k, rec in seed.items():
        assert ai.key_for(rec["question"], rec["state"]) == k and rec["model"] and rec["answer"]
