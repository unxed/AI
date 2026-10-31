import os
import subprocess
import sys

CLI = os.path.join(os.path.dirname(__file__), "..", "aistudio.py")


def run(env_extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OFFLOAD_", "CLAUDECODE"))}
    env.update(env_extra)
    env["AISTUDIO_HOME"] = "/nonexistent-offload-test"
    return subprocess.run([sys.executable, CLI, "ask", "hi"], env=env, capture_output=True, text=True)


def test_same_vendor_caller_refused():
    r = run({"OFFLOAD_CALLER": "gemini-3.8-flash"})
    assert r.returncode != 0 and "REFUSED" in r.stderr


def test_same_vendor_up_the_chain_refused():
    r = run({"OFFLOAD_CALLER": "claude-haiku", "OFFLOAD_CHAIN": "anthropic>google>deepseek"})
    assert "REFUSED" in r.stderr and "google" in r.stderr


def test_unknown_caller_refused():
    r = run({})
    assert "REFUSED" in r.stderr and "OFFLOAD_CALLER" in r.stderr


def test_other_vendor_allowed_past_guard():
    r = run({"OFFLOAD_CALLER": "glm-5.3-flash", "OFFLOAD_CHAIN": "anthropic>deepseek"})
    assert "REFUSED" not in r.stderr
    assert "chain anthropic>deepseek>zhipu>google" in r.stderr


def test_claude_code_detected():
    r = run({"CLAUDECODE": "1"})
    assert "REFUSED" not in r.stderr and "chain anthropic>google" in r.stderr
