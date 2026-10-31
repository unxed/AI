import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import offload_core as oc


def test_batch_stagger_arg(monkeypatch):
    seen = {}
    monkeypatch.setattr(oc, "chain_guard", lambda: None)
    monkeypatch.setattr(oc, "cmd_batch", lambda args: seen.setdefault("ns", args))
    monkeypatch.setattr(oc.sys, "argv", ["aistudio", "batch", "jobs.jsonl", "--stagger", "5"])
    try:
        oc.main()
    except SystemExit:
        pass
    assert seen["ns"].stagger == 5.0
