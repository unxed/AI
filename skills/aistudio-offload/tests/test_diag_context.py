import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import offload_core as oc

CLI = os.path.join(os.path.dirname(__file__), "..", "aistudio.py")


@pytest.mark.parametrize("exc,texts,want", [
    (RuntimeError("AI Studio error: Permission denied"), (), "PERMISSION_DENIED"),
    (RuntimeError("Run did not start (quota? dialog?). You exceeded your quota"), (), "QUOTA"),
    (RuntimeError("HTTP 429: RESOURCE_EXHAUSTED"), (), "RATE_LIMIT"),
    (RuntimeError("x"), ("The input token count exceeds the maximum",), "CONTEXT_TOO_LARGE"),
    (RuntimeError("Session expired: run `aistudio login` again."), (), "NOT_LOGGED_IN"),
    (RuntimeError("Empty answer (quota/safety?). "), (), "EMPTY_ANSWER"),
    (RuntimeError("Empty answer"), ("Response blocked due to safety",), "SAFETY"),
    (TimeoutError("timeout waiting for: (window.__ofl.done"), (), "TIMEOUT"),
    (TimeoutError("timeout waiting for: !!document.querySelector(ms-x)"), (), "UI_CHANGED"),
    (RuntimeError("Run did not start (quota? dialog?). "), (), "UI_CHANGED"),
    (RuntimeError("boom"), (), "UNKNOWN"),
])
def test_classify(exc, texts, want):
    got = oc.classify_failure(exc, *texts)
    assert got == want, (exc, got)
    assert got in oc.REASONS


def test_bundle_written(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "HOME", str(tmp_path))
    e = oc.attach_diag(RuntimeError("Permission denied"), {"model_requested": "m", "prompt_chars": 5},
                       {"url": "https://u", "page": "body", "alerts": "a", "shot": b"jpg",
                        "ofl": {"n": 1, "done": True, "status": 200, "text": "raw"}})
    assert e.diag_reason == "PERMISSION_DENIED" and e.diag_line.startswith(f"DIAG PERMISSION_DENIED {e.diag_dir}:")
    for f in ("summary.txt", "page.txt", "alerts.txt", "screenshot.jpg"):
        assert os.path.isfile(os.path.join(e.diag_dir, f))
    s = open(os.path.join(e.diag_dir, "summary.txt")).read()
    assert "https://u" in s and "model_requested: m" in s and "raw" in s


def test_diag_never_masks(monkeypatch):
    monkeypatch.setattr(oc, "HOME", "/proc/nonexistent/x")
    e = oc.attach_diag(RuntimeError("orig"))
    assert "orig" in e.diag_line


def test_build_prompt_limit(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * 1000)
    assert "x" * 1000 in oc.build_prompt("task", [str(f)], 5000)
    with pytest.raises(oc.ContextTooLarge) as ei:
        oc.build_prompt("task", [str(f)], 500)
    assert ei.value.total > 1000 and ei.value.limit == 500


def test_max_context_env(monkeypatch):
    monkeypatch.delenv("OFFLOAD_MAX_CONTEXT", raising=False)
    assert oc.max_context() == 400_000
    monkeypatch.setenv("OFFLOAD_MAX_CONTEXT", "1234")
    assert oc.max_context() == 1234 and oc.max_context(7) == 7


def run(args, home, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("OFFLOAD_", "CLAUDECODE"))}
    e.update(AISTUDIO_HOME=str(home), OFFLOAD_CALLER="glm-5", **env)
    return subprocess.run([sys.executable, CLI, *args], env=e, capture_output=True, text=True)


def test_code_over_limit_exits_3(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "big.py").write_text("x = 1\n" * 100_000)
    (repo / "small.py").write_text("y = 2\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    r = run(["code", "do it", "-C", str(repo), "--max-context", "50000"], tmp_path / "h")
    assert r.returncode == 3, r.stderr
    assert "CONTEXT_TOO_LARGE" in r.stderr and "big.py" in r.stderr and "-p" in r.stderr
    assert "limit 50,000" in r.stderr and "DIAG CONTEXT_TOO_LARGE" in r.stderr
    d = os.listdir(tmp_path / "h" / "diag")
    assert len(d) == 1
    # env var works too, and the diag command shows the bundle
    r = run(["code", "do it", "-C", str(repo)], tmp_path / "h", OFFLOAD_MAX_CONTEXT="1000")
    assert r.returncode == 3
    r = run(["diag"], tmp_path / "h")
    assert r.returncode == 0 and "reason: CONTEXT_TOO_LARGE" in r.stdout


def test_ask_over_limit_exits_3(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("z" * 3000)
    r = run(["ask", "q", "-f", str(f), "--max-context", "1000"], tmp_path / "h")
    assert r.returncode == 3 and "fewer -f" in r.stderr


def test_router_may_run_diag():
    from offload_core import check_router_command as chk
    assert chk("aistudio diag 3") is None


def test_ask_many_failure_snapshots_tab(tmp_path, monkeypatch):
    class C:
        def eval(self, expr, timeout=60):
            if "innerText" in expr and "body" in expr:
                return "PAGE BODY Permission denied"
            if "ms-callout" in expr:
                return "callout: oops"
            if "__ofl" in expr:
                return {"n": 1, "done": True, "status": 500, "text": "rawtext"}
            return ""

    class T:
        c = C()
        closed = False

        def url(self):
            return "https://aistudio.google.com/x"

        def screenshot(self):
            return b"jpegbytes"

        def close(self):
            self.closed = True

    class Ch:
        proc = None

        def new_tab(self, url=""):
            self.t = T()
            return self.t

    def fake_ask(ch, prompt, model="m", system=None, timeout=900):
        tab = ch.new_tab("u")
        try:
            raise RuntimeError("boom")
        finally:
            tab.close()

    monkeypatch.setattr(oc, "HOME", str(tmp_path))
    monkeypatch.setattr(oc, "open_chrome", Ch)
    monkeypatch.setattr(oc, "ask_tab", fake_ask)
    monkeypatch.setattr(oc.time, "sleep", lambda s: None)
    r = oc.ask_many([("hello", "m", None)], retries=0)[0]
    assert isinstance(r, RuntimeError) and r.diag_reason == "PERMISSION_DENIED"
    d = r.diag_dir
    assert open(os.path.join(d, "page.txt")).read().startswith("PAGE BODY")
    assert "callout" in open(os.path.join(d, "alerts.txt")).read()
    assert "rawtext" in open(os.path.join(d, "summary.txt")).read()
    assert os.path.getsize(os.path.join(d, "screenshot.jpg")) == 9


def test_stall_decision():
    f = oc.stall_decision
    assert f(10, 0, 0, 5, 180) == (10, 5, False)          # growth resets the window
    assert f(10, 10, 5, 100, 180) == (10, 5, False)       # quiet but within the window
    assert f(10, 10, 5, 185, 180) == (10, 5, True)        # no growth for 180 s
    assert f(0, 0, 0, 181, 180)[2] is True                # never started producing


def test_stalled_classified():
    assert oc.classify_failure(oc.StallError("STALLED: no output growth for 181s")) == "STALLED"
    assert "STALLED" in oc.REASONS


def test_repeated_p_flags_accumulate(monkeypatch):
    # `-p a -p b` must keep both (it used to keep only the last one, so Gemini never saw
    # the file it had to patch -> ap "Snippet not found")
    import offload_core as oc
    seen = {}
    monkeypatch.setattr(oc, "cmd_code", lambda args: seen.setdefault("ns", args))
    monkeypatch.setattr(oc.sys, "argv", ["aistudio", "code", "t", "-p", "a.md", "-p", "b.py", "c.md"])
    try:
        oc.main()
    except SystemExit:
        pass
    assert seen["ns"].paths == ["a.md", "b.py", "c.md"]
