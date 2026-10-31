import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from offload_core import check_manager_tool as chk

CLI = os.path.join(os.path.dirname(__file__), "..", "aistudio.py")


def bash(c):
    return chk("Bash", {"command": c})


BASH_OK = ["python3 tools/foo.py --x 1", "python3 -m pytest -q", "git status", "git log --oneline | head -5",
           "gh pr view 12 --json title", "gh pr create --title t --body-file /tmp/work/b.md",
           "gh issue list > /dev/null 2>&1", "make test 2>&1 | tail -20", "ls -la > /tmp/x/work/ls.txt",
           "cmd >> /tmp/run/logs/a.txt", "cmd > /tmp/a.out", "cmd 2>/tmp/a.log", "grep 'a>b' f",
           "git commit -m \"docs: sed -i note\"", "sed -n 1,5p f", "aistudio code --task-file t.md -C .",
           "cd repo && git diff", "ls >&2"]
BASH_BAD = ["python3 -c 'print(1)'", "python -c 'x'", "python3 - <<EOF\nprint(1)\nEOF", "python3 -",
            "cat <<EOF > a.md\nx\nEOF", "sed -i s/a/b/ f", "sed -i.bak s/a/b/ f", "perl -pi -e 's/a/b/' f",
            "perl -e 'print 1'", "awk '{print $1 > \"o\"}' f", "ls | tee out.txt", "cat > a.md", "echo hi > a.md",
            "printf x >> notes.md", "echo x > /tmp/other.txt", "git apply p.diff", "patch -p1 < p", "ap p.ap",
            "gh pr create --body \"text\"", "gh issue comment 1 -b hi", "gh api repos/o/r/issues/1/comments -f body=hi",
            "gh api x --field body=hi", "cd x && python3 -c 1", "bash -c \"echo x > f\"", "ls &> out.txt"]


def test_bash_allowed():
    for c in BASH_OK:
        assert bash(c) is None, (c, bash(c))


def test_bash_blocked():
    for c in BASH_BAD:
        assert bash(c), c


def test_edit_tools_blocked():
    for t in ("Edit", "MultiEdit", "NotebookEdit"):
        assert chk(t, {"file_path": "/x/task.md"})


def test_write_only_task_files():
    for p in ("/r/task.md", "/r/task-triage.md", "/r/a.task.md", "/r/tasks/one.txt", "tasks/x.json"):
        assert chk("Write", {"file_path": p}) is None, p
    for p in ("/r/README.md", "/r/a.py", "/r/mytask.md", "/r/tasks"):
        assert chk("Write", {"file_path": p}), p


def test_other_tools_allowed():
    for t in ("Agent", "Task", "Read", "Glob", "Grep", "Monitor", "TaskOutput", "ToolSearch", "mcp__x__y"):
        assert chk(t, {}) is None, t


def run_guard(tool, inp):
    env = dict(os.environ, AISTUDIO_HOME="/nonexistent-offload-test")
    return subprocess.run([sys.executable, CLI, "guard", "--manager"], input=json.dumps(
        {"tool_name": tool, "tool_input": inp}), env=env, capture_output=True, text=True)


def test_guard_manager_cli():
    r = run_guard("Edit", {"file_path": "a.py"})
    assert r.returncode == 2 and r.stderr.startswith("MANAGER GATE:") and "router subagent" in r.stderr
    assert run_guard("Bash", {"command": "git status"}).returncode == 0
    assert run_guard("Bash", {"command": "python3 -c 1"}).returncode == 2
