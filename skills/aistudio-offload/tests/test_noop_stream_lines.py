import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import offload_core as oc
from test_models_rounds_account import ap_patch, code_args, repo  # noqa: F401


# ---- 1. PATCH_NOOP
def test_noop_patch_fails_loudly(repo, monkeypatch, capsys):
    r, task = repo
    task.write_text("x")
    same = ap_patch("    return 1", "    return 1")  # content == snippet: ap says success, nothing changes
    monkeypatch.setattr(oc, "ask_many", lambda reqs: [same])
    with pytest.raises(SystemExit) as e:
        oc.cmd_code(code_args(r, task, rounds=2))
    assert e.value.code != 0
    err = capsys.readouterr().err
    assert "PATCH_NOOP" in err and "files changed (0): NONE" in err
    assert "DIAG PATCH_NOOP" in err


def test_partly_noop_second_file_is_caught(repo, monkeypatch, capsys):
    r, task = repo
    task.write_text("x")
    (r / "n.txt").write_text("keep\n")
    two = ("```ap\nf0cacc1a AP 3.2\n\nf0cacc1a FILE\nm.py\n\nf0cacc1a REPLACE\n\nf0cacc1a snippet\n    return 1\n\n"
           "f0cacc1a content\n    return 10\n\nf0cacc1a FILE\nn.txt\n\nf0cacc1a REPLACE\n\nf0cacc1a snippet\nkeep\n\n"
           "f0cacc1a content\nkeep\n\n```")
    answers = iter([two, ap_patch("    return 2", "    return 20")])
    monkeypatch.setattr(oc, "ask_many", lambda reqs: [next(answers)])
    oc.cmd_code(code_args(r, task))
    err = capsys.readouterr().err
    assert "the patch did not change: n.txt" in err
    assert "files changed (1): m.py" in err and "files changed (1): m.py" in err


def test_real_change_logs_files(repo, monkeypatch, capsys):
    r, task = repo
    task.write_text("x")
    monkeypatch.setattr(oc, "ask_many", lambda reqs: [ap_patch("    return 1", "    return 10")])
    oc.cmd_code(code_args(r, task))
    assert "files changed (1): m.py" in capsys.readouterr().err


# ---- 2. stream parsing
CH = lambda t: [None, t]  # noqa: E731


def test_parse_ok_and_prefix():
    raw = json.dumps([[[CH("hel"), [None, "x", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]], [CH("lo")]]])
    assert oc.parse_generate(raw) == "hello"
    assert oc.parse_generate(")]}'\n" + raw + "\n garbage") == "hello"


def test_error_chunk_after_text_is_classified():
    good = json.dumps([[CH("partial answer")]])[:-1]
    raw = good + ',[,[7,"The caller does not have permission"]]]'
    with pytest.raises(RuntimeError) as e:
        oc.parse_generate(raw)
    assert oc.classify_failure(e.value) == "PERMISSION_DENIED"
    from genwatch import retry_pause
    assert retry_pause(e.value, 1)[1] == "permission denied"


def test_truncated_stream_is_malformed_not_partial():
    raw = json.dumps([[CH("a" * 50)], [CH("b" * 50)]])[:-30]
    with pytest.raises(RuntimeError) as e:
        oc.parse_generate(raw)
    assert oc.classify_failure(e.value) == "MALFORMED_RESPONSE"
    assert "MALFORMED_RESPONSE" in oc.REASONS


# ---- 3. line numbers
def test_number_lines():
    assert oc.number_lines("a\nb\n") == "   1| a\n   2| b"


def test_ask_prompt_numbered_by_default(tmp_path):
    f = tmp_path / "a.go"
    f.write_text("x\ny\n")
    p = oc.build_prompt("q", [str(f)], line_numbers=True)
    assert "   2| y" in p and "NOT part of the file" in p
    assert "   2| y" not in oc.build_prompt("q", [str(f)])


def test_code_context_not_numbered_by_default_and_opt_in(repo, monkeypatch):
    r, task = repo
    task.write_text("x")
    seen = []
    monkeypatch.setattr(oc, "ask_many", lambda reqs: seen.append(reqs[0][0]) or [ap_patch("    return 1", "    return 10")])
    oc.cmd_code(code_args(r, task))
    assert "   1| def a" not in seen[0] and "def a():\n    return 1" in seen[0]
    (r / "m.py").write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")
    oc.cmd_code(code_args(r, task, line_numbers=True))
    assert "   1| def a" in seen[1] and "NOT part" in seen[1]


def test_cli_flags():
    import argparse  # noqa: F401
    src = open(oc.__file__).read()
    assert "--no-line-numbers" in src and "--verify-refs" in src


# ---- 4. verify-refs
def test_verify_refs(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.go").write_text("1\n2\n3\n")
    ans = "see pkg/a.go:2, a.go:3-3 and pkg/a.go:99, pkg/zz.go:1, `a.go:2`"
    bad = oc.verify_refs(ans, str(tmp_path))
    assert bad == ["pkg/a.go:99: file has only 3 lines", "pkg/zz.go:1: file not found"]
