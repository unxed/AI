"""Generation watch: stall detection, fast fail on UI errors, heartbeat, run status, retries.
Everything runs on mocks of the page (no browser, no network, no sleeping)."""
import json
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import genwatch  # noqa: E402
import offload_core as oc  # noqa: E402

CLI = os.path.join(os.path.dirname(__file__), "..", "aistudio.py")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeTab:
    """tab.c.eval returns the next scripted page state (the last one repeats); pump = time passes."""

    def __init__(self, clock, states):
        self.clock, self.states, self.i = clock, list(states), 0
        outer = self

        class C:
            def eval(self, expr, timeout=60):
                s = outer.states[min(outer.i, len(outer.states) - 1)]
                outer.i += 1
                return s

            def pump(self, dt):
                outer.clock.t += dt
        self.c = C()


def page(n=0, busy=False, done=False, err="", alerts=(), url="https://aistudio.google.com/prompts/x"):
    return {"n": n, "turn": 0, "busy": busy, "done": done, "err": err, "alerts": list(alerts), "url": url}


@pytest.fixture
def runs(tmp_path, monkeypatch):
    clock, lines = Clock(), []
    r = genwatch.Runs(str(tmp_path), lines.append, hb=15, prog="aistudio", clock=clock, pid=4242)
    r.lines, r.clk = lines, clock
    monkeypatch.setattr(oc, "RUNS", r)
    return r


# ------------------------------------------------------------------ stall detection

def test_stall_no_growth_no_indicator(runs):
    clk = runs.clk
    tab = FakeTab(clk, [page(n=100)] * 1000)
    with pytest.raises(oc.StallError) as ei:
        oc.wait_generation(tab, timeout=900, stall_s=120, clock=clk)
    assert "no output growth and no generation indicator" in str(ei.value)
    assert 120 <= clk.t - 1000 < 130           # stopped at the stall window, not at the 900 s timeout
    assert oc.classify_failure(ei.value) == "STALLED"


def test_growth_keeps_the_attempt_alive_then_stalls(runs):
    clk = runs.clk
    tab = FakeTab(clk, [page(n=100 * k) for k in range(1, 201)] + [page(n=20000)] * 1000)
    with pytest.raises(oc.StallError):
        oc.wait_generation(tab, timeout=900, stall_s=120, clock=clk)
    assert clk.t - 1000 >= 200 + 119          # 200 s of growth, then a full quiet window


def test_generation_indicator_is_not_a_stall(runs):
    clk = runs.clk
    tab = FakeTab(clk, [page(n=0, busy=True)] * 1000)   # model "thinking": Stop button, no text yet
    with pytest.raises(TimeoutError) as ei:
        oc.wait_generation(tab, timeout=600, stall_s=120, clock=clk)   # only the attempt timeout ends it
    assert "after 6" in str(ei.value)


def test_indicator_gone_without_output_fails_fast(runs):
    clk = runs.clk
    tab = FakeTab(clk, [page(busy=True)] * 3 + [page(busy=False)] * 100)
    with pytest.raises(RuntimeError, match="Empty answer"):
        oc.wait_generation(tab, timeout=900, stall_s=120, clock=clk)
    assert clk.t - 1000 < 40


def test_done(runs):
    tab = FakeTab(runs.clk, [page(n=5, busy=True), page(n=50, done=True)])
    assert oc.wait_generation(tab, timeout=900, clock=runs.clk) == "DONE"


# ------------------------------------------------------------------ UI errors: fast fail

@pytest.mark.parametrize("kw,needle", [
    (dict(alerts=["error\nPermission denied. Please check your account permissions"]), "Permission denied"),
    (dict(alerts=["You've reached your rate limit. Please try again later."]), "rate limit"),
    (dict(err="Something went wrong"), "Something went wrong"),
    (dict(alerts=["Failed to generate content"]), "Failed to generate"),
])
def test_ui_error_fails_fast(runs, kw, needle):
    clk = runs.clk
    tab = FakeTab(clk, [page(n=0, busy=True, **kw)] * 1000)    # even while the page still looks busy
    res = oc.wait_generation(tab, timeout=900, stall_s=120, clock=clk)
    assert res.startswith("ERR:") and needle.lower() in res.lower()
    assert clk.t - 1000 < 5                                     # seconds, not the 900 s timeout


def test_transient_alert_ignored(runs):
    tab = FakeTab(runs.clk, [page(n=1, busy=True, alerts=["Rate limit"]), page(n=2, busy=True), page(n=3, done=True)])
    assert oc.wait_generation(tab, timeout=900, clock=runs.clk) == "DONE"


def test_harmless_banner_is_not_an_error(runs):
    tab = FakeTab(runs.clk, [page(n=1, busy=True, alerts=["Preview models may be unstable"])] * 3 + [page(n=9, done=True)])
    assert oc.wait_generation(tab, timeout=900, clock=runs.clk) == "DONE"


def test_signed_out_page(runs):
    tab = FakeTab(runs.clk, [page(url="https://accounts.google.com/v3/signin")])
    with pytest.raises(RuntimeError, match="login"):
        oc.wait_generation(tab, timeout=900, clock=runs.clk)


def test_ui_error_text():
    assert "Permission denied" in genwatch.ui_error(["x", "error\nPermission denied."])
    assert genwatch.ui_error([" ", "Got it", None]) == ""


# ------------------------------------------------------------------ heartbeat + status file

def test_heartbeat_format_and_delta(runs):
    att = runs.begin("gemini-3.1-pro-preview", 1)
    clk = runs.clk
    runs.progress(att, 0, busy=True)
    clk.t += 10
    runs.tick()
    assert runs.lines == []                       # not due yet (15 s)
    clk.t += 10
    runs.progress(att, 1200, busy=True)
    runs.tick()
    assert re.fullmatch(r"waiting: model=gemini-3\.1-pro-preview, elapsed=20s, answer_chars=1200 \(\+1200\), "
                        r"state=generating", runs.lines[0])
    clk.t += 16
    runs.progress(att, 1500, busy=True)
    runs.tick()
    assert "answer_chars=1500 (+300), state=generating" in runs.lines[1]
    clk.t += 30
    runs.progress(att, 1500, busy=False)
    clk.t += 1
    runs.tick()
    assert "answer_chars=1500 (+0), state=idle" in runs.lines[2]
    runs.progress(att, 1500, error="Permission denied")
    clk.t += 16
    runs.tick()
    assert "state=error" in runs.lines[3] and "Permission denied" in runs.lines[3]


def test_heartbeat_before_page_probe(runs):
    att = runs.begin("m", 1)
    runs.phase("typing prompt", att)
    runs.clk.t += 16
    runs.tick()
    assert re.fullmatch(r"waiting: model=m, elapsed=16s, state=preparing, phase=typing prompt", runs.lines[0])


def test_wait_generation_feeds_heartbeat(runs):
    att = runs.begin("m", 2)
    clk = runs.clk
    states = [page(n=40 * k, busy=True) for k in range(1, 41)] + [page(n=1600, done=True)]
    oc.wait_generation(FakeTab(clk, states), timeout=900, att=att, clock=clk)
    runs.tick()
    assert re.search(r"waiting: model=m, elapsed=\d+s, answer_chars=1\d+ \(\+\d+\), state=generating", runs.lines[0])


def test_status_file_content(runs):
    att = runs.begin("m", 2)
    runs.progress(att, 700, busy=True)
    runs.write()
    d = json.load(open(runs.path))
    assert os.path.basename(runs.path) == "run-4242.json"
    assert (d["pid"], d["model"], d["attempt"], d["state"], d["answer_chars"]) == (4242, "m", 2, "generating", 700)
    assert d["last_progress_ts"] == runs.clk.t and d["active"] is True
    assert oct(os.stat(runs.path).st_mode & 0o777) == "0o600"
    runs.end(att, "failed", "Permission denied")
    d = json.load(open(runs.path))
    assert d["state"] == "between" and d["jobs"][0]["state"] == "failed"      # process still alive
    runs.stop()
    d = json.load(open(runs.path))
    assert d["active"] is False and d["state"] == "failed" and "Permission denied" in d["error"]


def test_list_runs_health(runs):
    clk = runs.clk
    att = runs.begin("m", 1)
    runs.progress(att, 10, busy=True)
    runs.write()

    def health(dt=0, alive=True):
        return genwatch.list_runs(runs.home, now=clk.t + dt, stall=120, alive=lambda pid: alive)[0]

    assert health()["health"] == "ok"
    assert health(alive=False)["health"] == "DEAD"            # process gone while the run is active
    assert health(dt=60)["health"] == "HUNG"                  # file not refreshed: the process is frozen
    runs.progress(att, 10, busy=False)                        # indicator gone, no growth
    clk.t += 200
    runs.write()                                              # status refreshed, but no progress for 200 s
    run = health()
    assert run["health"] == "SILENT" and run["silent_for"] >= 200
    line = genwatch.format_run(run)
    assert "health=SILENT" in line and "pid=4242" in line and "answer_chars=10" in line
    runs.progress(att, 99, busy=False)                        # growth = progress again
    runs.write()
    assert health()["health"] == "ok"


def test_status_runs_cli(tmp_path):
    home = tmp_path
    now = __import__("time").time()
    base = {"prog": "aistudio", "model": "m", "attempt": 1, "answer_chars": 5, "elapsed": 9,
            "last_progress_ts": now, "updated": now, "error": "", "jobs": []}
    json.dump(dict(base, pid=os.getpid(), state="generating", active=True), open(home / "run-1.json", "w"))
    env = {**os.environ, "AISTUDIO_HOME": str(home), "OFFLOAD_CALLER": "claude"}
    r = subprocess.run([sys.executable, CLI, "status", "--runs"], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "state=generating" in r.stdout and "health=ok" in r.stdout
    json.dump(dict(base, pid=2 ** 22 + 12345, state="generating", active=True), open(home / "run-2.json", "w"))
    r = subprocess.run([sys.executable, CLI, "status", "--runs", "--json"], env=env, capture_output=True, text=True)
    assert r.returncode == 2 and {x["health"] for x in json.loads(r.stdout)} == {"ok", "DEAD"}
    r = subprocess.run([sys.executable, CLI, "watch", "-i", "0.1"], env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 2 and "health=DEAD" in r.stdout    # watch stops at once on a dead run


def test_router_may_watch():
    assert oc.check_router_command("aistudio watch") is None
    assert oc.check_router_command("aistudio status --runs") is None


# ------------------------------------------------------------------ retries in ask_many

class FakeChrome:
    proc = None

    def new_tab(self, url=""):
        raise AssertionError("ask_tab is mocked")

    def quit(self):
        pass


@pytest.fixture
def many(tmp_path, monkeypatch):
    sleeps, lines = [], []
    monkeypatch.setattr(oc, "HOME", str(tmp_path))
    monkeypatch.setattr(oc, "RUNS", oc._NoRuns())
    monkeypatch.setattr(oc, "open_chrome", FakeChrome)
    monkeypatch.setattr(oc.time, "sleep", sleeps.append)
    monkeypatch.setattr(oc, "log", lambda *a: lines.append(" ".join(map(str, a))))
    monkeypatch.setattr(oc, "write_diag", lambda *a, **k: ("UNKNOWN", str(tmp_path)))
    monkeypatch.setattr(oc, "is_gemini", lambda: False)
    yield sleeps, lines
    if isinstance(oc.RUNS, genwatch.Runs):
        oc.RUNS.stop()


def script(monkeypatch, outcomes):
    calls = []

    def fake(ch, prompt, model="m", system=None, timeout=None):
        calls.append(model)
        o = outcomes[len(calls) - 1]
        if isinstance(o, Exception):
            raise o
        return o
    monkeypatch.setattr(oc, "ask_tab", fake)
    return calls


def test_permission_denied_switches_model_and_logs_pause(many, monkeypatch):
    sleeps, lines = many
    calls = script(monkeypatch, [RuntimeError("AI Studio error: Permission denied."), "answer"])
    assert oc.ask_many([("p", "gemini-3.1-pro-preview", None)])[0] == "answer"
    assert calls == ["gemini-3.1-pro-preview", "gemini-pro-latest"]
    assert sleeps == [30]
    assert any("retrying in 30s with gemini-pro-latest" in ln for ln in lines)


def test_permission_denied_retries_the_same_model_once_after_a_pause(many, monkeypatch):
    # live AI Studio: "Permission denied" came and went; the same model answered a minute later
    sleeps, lines = many
    pd = RuntimeError("AI Studio error: Permission denied.")
    calls = script(monkeypatch, [pd, pd, "never"])
    r = oc.ask_many([("p", "model-without-fallbacks", None)])[0]
    assert isinstance(r, Exception) and calls == ["model-without-fallbacks"] * 2 and sleeps == [60]
    assert "Permission denied" in r.diag_line
    assert "attempts: model-without-fallbacks: permission denied; model-without-fallbacks: permission denied" in r.diag_line


def test_permission_denied_then_success(many, monkeypatch):
    sleeps, lines = many
    calls = script(monkeypatch, [RuntimeError("AI Studio error: Permission denied."), "ok"])
    assert oc.ask_many([("p", "model-without-fallbacks", None)])[0] == "ok"
    assert calls == ["model-without-fallbacks"] * 2 and sleeps == [60]


def test_rate_limit_pause_and_final_reason(many, monkeypatch):
    sleeps, lines = many
    rl = RuntimeError("AI Studio error: You've reached your rate limit.")
    calls = script(monkeypatch, [rl, rl, oc.StallError("STALLED: no output growth and no generation indicator for 121s")])
    r = oc.ask_many([("p", "gemini-3.1-pro-preview", None)])[0]
    assert calls == ["gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-3.8-flash"]
    assert sleeps == [20, 40]
    assert isinstance(r, oc.StallError)
    assert r.diag_line.endswith("[attempts: gemini-3.1-pro-preview: rate limit; gemini-pro-latest: rate limit; "
                                "gemini-3.8-flash: stalled]")


def test_run_file_says_between_attempts_and_final_state(many, monkeypatch, tmp_path):
    seen = []

    def fake(ch, prompt, model="m", system=None, timeout=None):
        seen.append(json.load(open(oc.RUNS.path)))
        return "ok"
    monkeypatch.setattr(oc, "ask_tab", fake)
    assert oc.ask_many([("p", "gemini-3.8-flash", None)])[0] == "ok"
    assert seen[0]["model"] == "gemini-3.8-flash" and seen[0]["attempt"] == 1 and seen[0]["active"]
    d = json.load(open(oc.RUNS.path))
    assert d["jobs"][0]["state"] == "done" and d["state"] == "between"      # alive until the process exits


def test_every_failure_leaves_a_last_line(many, monkeypatch, capsys):
    script(monkeypatch, [RuntimeError("boom")] * 3)
    r = oc.ask_many([("p", "gemini-3.8-flash", None)])[0]
    with pytest.raises(SystemExit) as ei:
        oc.fail_exit(r)
    assert ei.value.code == 1
    assert capsys.readouterr().err.strip().splitlines()[-1].startswith("DIAG ")


def test_ticker_thread_emits_heartbeat_while_engine_is_blocked(tmp_path, monkeypatch):
    """Real thread, real clock: the heartbeat does not depend on the engine loop being responsive."""
    import time
    lines = []
    monkeypatch.setattr(oc, "HOME", str(tmp_path))
    monkeypatch.setattr(oc, "RUNS", oc._NoRuns())
    monkeypatch.setattr(oc, "HEARTBEAT_SECONDS", 0.3)
    monkeypatch.setattr(oc, "open_chrome", FakeChrome)
    monkeypatch.setattr(oc, "is_gemini", lambda: False)
    monkeypatch.setattr(oc, "log", lambda *a: lines.append(" ".join(map(str, a))))

    def blocked(ch, prompt, model="m", system=None, timeout=None):
        time.sleep(1.2)
        return "ok"
    monkeypatch.setattr(oc, "ask_tab", blocked)
    assert oc.ask_many([("p", "some-model", None)])[0] == "ok"
    oc.RUNS.stop()
    hb = [ln for ln in lines if ln.startswith("waiting: model=some-model")]
    assert len(hb) >= 2 and "state=preparing" in hb[0]


def test_model_not_in_ui_is_not_retried(many, monkeypatch):
    # live VM run: gemini-2.5-flash vanished from the chat UI and was retried for 2.5 minutes
    sleeps, lines = many
    calls = script(monkeypatch, [oc.ModelUnavailable("model 'old' is not available in the AI Studio chat UI"), "never"])
    r = oc.ask_many([("p", "model-without-fallbacks", None)])[0]
    assert isinstance(r, oc.ModelUnavailable) and calls == ["model-without-fallbacks"] and sleeps == []


def test_model_not_in_ui_goes_straight_to_fallback(many, monkeypatch):
    sleeps, lines = many
    calls = script(monkeypatch, [oc.ModelUnavailable("not available"), "answer"])
    assert oc.ask_many([("p", "gemini-3.1-pro-preview", None)])[0] == "answer"
    assert calls == ["gemini-3.1-pro-preview", "gemini-pro-latest"] and sleeps == [0]
