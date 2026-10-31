"""Visible model fallback / --no-fallback, saved ap rounds + --dry-run, whoami/diag, heartbeat in pauses."""
import argparse
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import genwatch  # noqa: E402
import offload_core as oc  # noqa: E402
from test_genwatch import Clock, FakeChrome, script  # noqa: E402,F401

CLI = os.path.join(os.path.dirname(__file__), "..", "aistudio.py")
PD = RuntimeError("AI Studio error: Permission denied.")
RL = RuntimeError("AI Studio error: You've reached your rate limit.")


@pytest.fixture
def many(tmp_path, monkeypatch):
    sleeps, lines = [], []
    monkeypatch.setattr(oc, "HOME", str(tmp_path))
    monkeypatch.setattr(oc, "RUNS", oc._NoRuns())
    monkeypatch.setattr(oc, "NO_FALLBACK", False)
    monkeypatch.setattr(oc, "open_chrome", FakeChrome)
    monkeypatch.setattr(oc.time, "sleep", sleeps.append)
    monkeypatch.setattr(oc, "log", lambda *a: lines.append(" ".join(map(str, a))))
    monkeypatch.setattr(oc, "write_diag", lambda *a, **k: ("UNKNOWN", str(tmp_path)))
    monkeypatch.setattr(oc, "is_gemini", lambda: False)
    yield sleeps, lines
    if isinstance(oc.RUNS, genwatch.Runs):
        oc.RUNS.stop()


# ------------------------------------------------------------------ 1. no silent substitution

def test_fallback_is_loud_and_recorded(many, monkeypatch):
    sleeps, lines = many
    script(monkeypatch, [PD, RL, "answer"])
    assert oc.ask_many([("p", "gemini-3.1-pro-preview", None)])[0] == "answer"
    text = "\n".join(lines)
    assert "MODEL FALLBACK: gemini-3.1-pro-preview unavailable (permission denied); switching to gemini-pro-latest" in text
    assert "WARNING: answered by gemini-3.8-flash INSTEAD OF the requested gemini-3.1-pro-preview" in text
    assert lines[-1] == ("result: requested_model=gemini-3.1-pro-preview actual_model=gemini-3.8-flash fallback=yes")
    d = json.load(open(oc.RUNS.path))
    assert (d["requested_model"], d["actual_model"]) == ("gemini-3.1-pro-preview", "gemini-3.8-flash")
    assert oc.RESULTS[0] == {"requested": "gemini-3.1-pro-preview", "actual": "gemini-3.8-flash", "fallback": True}


def test_no_fallback_flag_is_quiet_when_requested_model_answers(many, monkeypatch):
    sleeps, lines = many
    script(monkeypatch, ["answer"])
    oc.ask_many([("p", "gemini-3.8-flash", None)])
    assert lines[-1].endswith("fallback=no") and not any("WARNING" in ln for ln in lines)


def test_no_fallback_permission_denied_fails(many, monkeypatch):
    monkeypatch.setattr(oc, "NO_FALLBACK", True)
    sleeps, lines = many
    calls = script(monkeypatch, [PD, PD, "never"])        # Permission denied: one more try after 60 s, then fail
    r = oc.ask_many([("p", "gemini-3.1-pro-preview", None)])[0]
    assert sleeps == [60]
    assert isinstance(r, Exception) and calls == ["gemini-3.1-pro-preview"] * 2
    assert "requested model gemini-3.1-pro-preview unavailable (--no-fallback)" in str(r)
    assert "--no-fallback" in r.diag_line and not any("MODEL FALLBACK" in ln for ln in lines)


def test_no_fallback_rate_limit_retries_same_model_then_fails(many, monkeypatch):
    monkeypatch.setattr(oc, "NO_FALLBACK", True)
    sleeps, lines = many
    calls = script(monkeypatch, [RL, RL, RL])
    r = oc.ask_many([("p", "gemini-3.1-pro-preview", None)])[0]
    assert calls == ["gemini-3.1-pro-preview"] * 3 and isinstance(r, Exception)
    assert "--no-fallback" in str(r)


def test_no_fallback_option_parsed():
    a = argparse.Namespace(no_fallback=True)
    old = oc.NO_FALLBACK
    try:
        oc.set_stall(a)
        assert oc.NO_FALLBACK is True
    finally:
        oc.NO_FALLBACK = old
    r = subprocess.run([sys.executable, CLI, "ask", "--help"], capture_output=True, text=True)
    assert "--no-fallback" in r.stdout


# ------------------------------------------------------------------ 4. heartbeat in pauses

def test_heartbeat_during_retry_pause(many, monkeypatch):
    sleeps, lines = many
    seen = []

    def sleeper(sec):  # the 30 s pause of the retry: the ticker must speak during it
        runs = oc.RUNS
        runs.tick(now=runs.between_hb + 20)
        seen.append(runs.snapshot())
    monkeypatch.setattr(oc.time, "sleep", sleeper)
    script(monkeypatch, [PD, "answer"])
    oc.ask_many([("p", "gemini-3.1-pro-preview", None)])
    assert seen[0]["state"] == "between" and "retrying in 30s with gemini-pro-latest" in seen[0]["phase"]
    hb = [ln for ln in lines if ln.startswith("waiting: state=between")]
    assert hb and "phase=pause before attempt 2: retrying in 30s with gemini-pro-latest" in hb[0]


def test_between_heartbeat_unit():
    clk, lines = Clock(), []
    r = genwatch.Runs("/nonexistent-genwatch", lines.append, hb=15, clock=clk, pid=1)
    a = r.begin("m", 1, requested="m")
    r.end(a, "failed", "boom")
    clk.t += 10
    r.tick()
    assert lines == []
    r.note("running tests: make")
    clk.t += 16
    r.tick()
    assert lines == ["waiting: state=between, phase=running tests: make"]
    r.begin("m", 2)
    clk.t += 16
    r.tick()
    assert lines[-1].startswith("waiting: model=m, elapsed=")


# ------------------------------------------------------------------ 2. saved rounds + --dry-run

def ap_patch(a, b):
    return ("```ap\nf0cacc1a AP 3.2\n\nf0cacc1a FILE\nm.py\n\nf0cacc1a REPLACE\n\nf0cacc1a snippet\n"
            f"{a}\n\nf0cacc1a content\n{b}\n\n```")


def code_args(repo, task_file, **kw):
    d = dict(dir=str(repo), task="t", task_file=str(task_file), test=None, ci=False, ci_branch=None,
             ci_base="main", ci_body=None, paths=None, rounds=3, model="m", test_timeout=60, dry_run=False)
    d.update(kw)
    return argparse.Namespace(**d)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    (r / "m.py").write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")
    subprocess.run(["git", "init", "-q"], cwd=r)
    subprocess.run(["git", "add", "."], cwd=r)
    monkeypatch.setattr(oc, "HOME", str(tmp_path / "home"))
    monkeypatch.setattr(oc, "RUNS", oc._NoRuns())
    work = tmp_path / "work"
    work.mkdir()
    yield r, work / "task.md"
    if isinstance(oc.RUNS, genwatch.Runs):
        oc.RUNS.stop()


def test_rounds_saved_next_to_task_file(repo, monkeypatch, capsys):
    r, task = repo
    task.write_text("do it")
    answers = [None, ap_patch("    return 2", "    return 20")]
    # round 1: the second modification cannot be located -> partial apply + afailed.md briefing
    answers[0] = ("```ap\nf0cacc1a AP 3.2\n\n"
                  "f0cacc1a FILE\nm.py\n\nf0cacc1a REPLACE\n\nf0cacc1a snippet\n    return 1\n\nf0cacc1a content\n    return 10\n\n"
                  "f0cacc1a FILE\nm.py\n\nf0cacc1a REPLACE\n\nf0cacc1a snippet\n    return 999\n\nf0cacc1a content\n    return 0\n\n```")
    it = iter(answers)
    monkeypatch.setattr(oc, "ask_many", lambda reqs: [next(it)])
    oc.cmd_code(code_args(r, task))
    assert open(f"{task}.round1.ap").read() == answers[0]          # raw answer, every round
    assert open(f"{task}.round2.ap").read() == answers[1]
    assert os.path.getsize(f"{task}.round1.afailed.md") > 0         # the repair briefing is kept too
    err = capsys.readouterr().err
    assert f"raw model answer saved to {task}.round1.ap" in err and f"{task}.round1.afailed.md" in err
    assert "return 20" in (r / "m.py").read_text()


def test_rounds_not_written_into_the_repo(repo, monkeypatch):
    r, _ = repo
    task_in_repo = r / "task.md"
    task_in_repo.write_text("x")
    monkeypatch.setattr(oc, "ask_many", lambda reqs: [ap_patch("    return 1", "    return 10")])
    oc.cmd_code(code_args(r, task_in_repo))
    assert not list(r.glob("*.round*"))
    assert __import__("glob").glob(os.path.join(oc.HOME, "rounds", "*", "round1.ap"))


def test_dry_run_valid_patch_applies_nothing(repo, monkeypatch, capsys):
    r, task = repo
    task.write_text("do it")
    ans = ap_patch("    return 1", "    return 10")
    monkeypatch.setattr(oc, "ask_many", lambda reqs: [ans])
    with pytest.raises(SystemExit) as ei:
        oc.cmd_code(code_args(r, task, dry_run=True))
    assert ei.value.code == 0
    assert (r / "m.py").read_text().count("return 1\n") == 1          # untouched
    assert open(f"{task}.round1.ap").read() == ans and os.path.exists(f"{task}.round1.patch.ap")
    cap = capsys.readouterr()
    assert "dry-run of the patch" in cap.err and "OK" in cap.err and "return 10" in cap.out
    assert not (r / "afailed.ap").exists() and not (r / ".afix.ap").exists()


def test_dry_run_bad_patch_fails_and_applies_nothing(repo, monkeypatch, capsys):
    r, task = repo
    task.write_text("do it")
    monkeypatch.setattr(oc, "ask_many", lambda reqs: [ap_patch("    return 999", "    return 0")])
    before = (r / "m.py").read_text()
    with pytest.raises(SystemExit) as ei:
        oc.cmd_code(code_args(r, task, dry_run=True))
    assert ei.value.code not in (0, None)
    assert (r / "m.py").read_text() == before
    assert not (r / "afailed.ap").exists() and not (r / "afailed.md").exists()
    assert "DIAG PATCH_FAILED" in capsys.readouterr().err


def test_dry_run_option_exists():
    r = subprocess.run([sys.executable, CLI, "code", "--help"], capture_output=True, text=True)
    assert "--dry-run" in r.stdout


# ------------------------------------------------------------------ 3. whoami / diag

class AccTab:
    def __init__(self, url, email):
        self._url, self.email = url, email

        class C:
            def eval(s, expr, timeout=60):
                return True if "textarea" in expr else self.email

            def pump(s, dt):
                pass
        self.c = C()
        self.closed = False

    def url(self):
        return self._url

    def wait_js(self, expr, timeout=60, interval=0.25):
        return self.c.eval(expr)

    def close(self):
        self.closed = True


class AccChrome(FakeChrome):
    def __init__(self, url="https://aistudio.google.com/prompts/new_chat", email="me@example.com"):
        self.url, self.email = url, email

    def new_tab(self, url=""):
        self.tab = AccTab(self.url, self.email)
        return self.tab


def test_fetch_account():
    ch = AccChrome()
    assert oc.fetch_account(ch) == "me@example.com" and ch.tab.closed
    assert oc.fetch_account(AccChrome(url="https://accounts.google.com/signin")) == ""


def test_account_js_picks_the_account_button():
    node = __import__("shutil").which("node")
    if not node:
        pytest.skip("node not installed")
    src = oc.JS_ACCOUNT
    js = ("const els=[{a:'Menu',t:''},{a:'Contact us at help@google.com',t:''},"
          "{a:'Google Account: Ann (ann@gmail.com)',t:''}];"
          "global.document={querySelectorAll:()=>els.map(e=>({getAttribute:k=>k==='aria-label'?e.a:e.t}))};"
          f"console.log({src});")
    out = subprocess.run([node, "-e", js], capture_output=True, text=True).stdout.strip()
    assert out == "ann@gmail.com"


def test_whoami_prints_and_caches(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(oc, "HOME", str(tmp_path))
    monkeypatch.setattr(oc, "open_chrome", AccChrome)
    monkeypatch.setattr(oc, "is_gemini", lambda: True)
    oc.cmd_whoami(argparse.Namespace())
    assert capsys.readouterr().out.strip() == "me@example.com"
    assert oc.cached_account()[0] == "me@example.com"
    assert oct(os.stat(oc.account_file()).st_mode & 0o777) == "0o600"
    monkeypatch.setattr(oc, "open_chrome", lambda: AccChrome(url="https://accounts.google.com/x"))
    with pytest.raises(SystemExit) as ei:
        oc.cmd_whoami(argparse.Namespace())
    assert "login" in str(ei.value.code)


def test_diag_is_never_empty(tmp_path):
    (tmp_path / "account-google.txt").write_text("me@example.com 1\n")
    env = {**os.environ, "AISTUDIO_HOME": str(tmp_path), "OFFLOAD_CALLER": "claude"}
    r = subprocess.run([sys.executable, CLI, "diag"], env=env, capture_output=True, text=True)
    assert r.returncode == 0
    out = r.stdout
    assert "account: me@example.com" in out and "default_model:" in out and "chrome: not running" in out
    assert "no failure bundles" in out


def test_router_may_whoami():
    assert oc.check_router_command("aistudio whoami") is None
