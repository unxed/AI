import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from offload_core import check_router_command as chk, extract_patch

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
