import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import offload_core as oc
import genwatch
from test_genwatch import many, script  # noqa: F401  (fixtures/helpers)


def git(root, *a):
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "a@b")
    git(tmp_path, "config", "user.name", "n")
    (tmp_path / "tracked.py").write_text("print(1)\n")
    git(tmp_path, "add", "tracked.py")
    git(tmp_path, "commit", "-qm", "x")
    return tmp_path


def test_untracked_dir_is_packed_and_counted(repo):
    d = repo / "work-issues"
    d.mkdir()
    (d / "a.md").write_text("issue A\n")
    (d / "pic.png").write_bytes(b"\x89PNG")
    (d / "bin.dat").write_bytes(b"\xff\xfe\x00\x80")
    (d / ".hidden").mkdir()
    (d / ".hidden" / "h.md").write_text("no\n")
    (d / "node_modules").mkdir()
    (d / "node_modules" / "n.js").write_text("no\n")
    (d / "link.md").symlink_to(d / "a.md")
    (repo / "TRIAGE.md").write_text("triage\n")  # untracked single file
    counts = {}
    items = oc.pack_tree(str(repo), ["tracked.py", "TRIAGE.md", "work-issues"], counts)
    assert sorted(f for f, _ in items) == ["TRIAGE.md", "tracked.py", "work-issues/a.md"]
    assert counts == {"tracked.py": 1, "TRIAGE.md": 1, "work-issues": 1}
    assert "issue A" in oc.combine_tree(str(repo), ["work-issues"])


def test_missing_or_empty_explicit_path_fails(repo):
    (repo / "empty").mkdir()
    for p in ("nope", "empty"):
        with pytest.raises(oc.PathNotFound) as ei:
            oc.pack_tree(str(repo), ["tracked.py", p])
        assert p in str(ei.value)


def test_code_exits_3_naming_the_path(repo, monkeypatch, capsys):
    import argparse
    args = argparse.Namespace(paths=["missing-dir"], dir=str(repo), task="t", task_file=None, test=None,
                              ci=False, ci_branch=None, model="m", rounds=1, max_context=None, dry_run=False,
                              stall=None, heartbeat=None, attempt_timeout=None, no_fallback=False)
    monkeypatch.setattr(oc, "ask_many", lambda *a, **k: pytest.fail("must not ask"))
    with pytest.raises(SystemExit) as ei:
        oc.cmd_code(args)
    assert ei.value.code == 3 and "missing-dir" in capsys.readouterr().err


def test_only_ci_path_stages_files():
    # `code` applies patches with ap (touches only files named in the patch); the sole `git add`
    # in the engine is ci_check (--ci), which pre-dates this change
    src = open(oc.__file__).read()
    assert src.count('"git", "add"') == 1
    assert src.index('"git", "add"') > src.index("def ci_check")


# ------------------------------------------------------------------ quota cascade

def test_quota_on_all_models_waits_and_does_one_more_pass(many, monkeypatch):
    sleeps, lines = many
    monkeypatch.delenv("OFFLOAD_QUOTA_WAIT", raising=False)
    q = RuntimeError("Empty answer (quota/safety?). ")
    calls = script(monkeypatch, [q, RuntimeError("AI Studio error: quota exceeded"), q, "ok"])
    assert oc.ask_many([("p", "gemini-3.8-flash", None)])[0] == "ok"
    assert calls == ["gemini-3.8-flash", "gemini-3-flash-preview", "gemini-flash-latest", "gemini-3.8-flash"]
    assert 120.0 in sleeps
    assert any("quota on all models, waiting 120s before one more pass" in ln for ln in lines)


def test_quota_wait_env_and_second_pass_fails_with_both_passes_in_trail(many, monkeypatch):
    sleeps, lines = many
    monkeypatch.setenv("OFFLOAD_QUOTA_WAIT", "7")
    q = RuntimeError("Empty answer (quota/safety?). ")
    calls = script(monkeypatch, [q] * 10)
    r = oc.ask_many([("p", "gemini-3.8-flash", None)])[0]
    assert isinstance(r, Exception) and len(calls) == 6 and 7.0 in sleeps
    assert r.diag_line.count("gemini-3.8-flash: quota") == 2
    assert "[waited 7s, pass 2]" in r.diag_line


def test_no_second_pass_for_other_errors(many, monkeypatch):
    sleeps, lines = many
    calls = script(monkeypatch, [RuntimeError("boom")] * 5)
    r = oc.ask_many([("p", "gemini-3.8-flash", None)])[0]
    assert isinstance(r, Exception) and len(calls) == 3 and not any(s >= 100 for s in sleeps)
