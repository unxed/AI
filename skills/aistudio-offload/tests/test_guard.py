import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from offload_core import check_router_command as chk, extract_patch, looks_like_diff

OK = ['aistudio ask "explain foo"', "aistudio code --task-file /tmp/t.md -t 'go test ./...'",
      "aistudio code - < task.md", "AISTUDIO_MODEL=gemini-2.5-pro aistudio ask hi",
      "~/.local/bin/aistudio status", "aistudio batch jobs.jsonl -j 3", "aistudio serve --tabs 2 &"]
BAD = ["python3 -c 'print(1)'", "aistudio ask hi; rm -rf /", "aistudio ask hi && cat x",
       "aistudio ask hi | tee f", "aistudio ask hi > out.py", "echo x > a.py", "cat a.py",
       "aistudio ask $(cat a)", "aistudio ask `id`", "aistudio guard", "aistudio login",
       "aistudio ask hi\nrm x", "FOO=1 aistudio ask hi", "cat <<EOF > a\nx\nEOF",
       "aistudio ask hi & rm x", "sed -i s/a/b/ f", "git commit -am x"]


def test_allowed():
    for c in OK:
        assert chk(c) is None, (c, chk(c))


def test_blocked():
    for c in BAD:
        assert chk(c) is not None, c


def test_extract_patch():
    assert extract_patch("intro\n```ap\nX\n```\nbye") == "X\n"
    assert extract_patch("raw patch") == "raw patch"


def test_diff_is_detected_and_not_extracted_as_patch():
    d = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n-a\n+b\n"
    assert looks_like_diff(d) and looks_like_diff("diff --git a/x b/x\n")
    assert not looks_like_diff("f0cacc1a AP 3.2\n\nf0cacc1a FILE\nx.py\n")
    assert extract_patch("```diff\n" + d + "```") == "```diff\n" + d + "```"


def test_small_machine_override(monkeypatch):
    import offload_core
    monkeypatch.setenv("OFFLOAD_ALLOW_LOCAL_BUILD", "1")
    assert offload_core._small_machine() is False


def test_generated_js_parses():
    import shutil, subprocess, pytest, offload_core as o
    if not shutil.which("node"):
        pytest.skip("node not installed")
    for js in (o.center_js(o.JS_RUN), o.JS_CLOSE_DIALOGS, o._fill_js(o.JS_BOX, "a\"b`c")):
        r = subprocess.run(["node", "-e", f"new Function({js!r})"], capture_output=True, text=True)
        assert r.returncode == 0, (js, r.stderr)


def test_failure_excerpt_keeps_early_traceback():
    from offload_core import failure_excerpt
    log = ("ok line\n" * 50 + "ERROR: test_x (loader._FailedTest)\nTraceback (most recent call last):\n"
           "  File \"t.py\", line 3\nIndentationError: unindent\n" + "noise from passing tests\n" * 3000
           + "Ran 598 tests\nFAILED (errors=1)\n")
    ex = failure_excerpt(log)
    assert "IndentationError" in ex and "FAILED (errors=1)" in ex and len(ex) < 6200


def test_code_loop_diff_then_partial_then_fixed(tmp_path, monkeypatch):
    """diff answer -> rejected; partly failing ap patch -> briefing sent back; fix -> applied."""
    import argparse, subprocess, offload_core
    (tmp_path / "m.py").write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    subprocess.run(["git", "add", "."], cwd=tmp_path)

    def ap(*mods):
        return "```ap\nf0cacc1a AP 3.2\n\n" + "".join(
            f"f0cacc1a FILE\nm.py\n\nf0cacc1a REPLACE\n\nf0cacc1a snippet\n{a}\n\nf0cacc1a content\n{b}\n\n"
            for a, b in mods) + "```"
    answers = ["```diff\n--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n-x\n+y\n```",
               ap(("    return 1", "    return 10"), ("    return 999", "    return 0")),
               ap(("    return 2", "    return 20"))]
    prompts = []

    def fake(reqs):
        prompts.append(reqs[0][0])
        return [answers[len(prompts) - 1]]
    monkeypatch.setattr(offload_core, "ask_many", fake)
    args = argparse.Namespace(dir=str(tmp_path), task="t", task_file=None, test=None, ci=False,
                              ci_branch=None, ci_base="main", ci_body=None, paths=None,
                              rounds=4, model="m", test_timeout=60)
    offload_core.cmd_code(args)
    assert len(prompts) == 3
    assert "UNIFIED DIFF" in prompts[1] and "PARTLY APPLIED" in prompts[2]
    assert (tmp_path / "m.py").read_text() == "def a():\n    return 10\n\ndef b():\n    return 20\n"
    assert not (tmp_path / "afailed.ap").exists() and not (tmp_path / ".afix.ap").exists()
