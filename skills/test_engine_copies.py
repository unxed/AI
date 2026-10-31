"""The two skills are independent folders, so the shared engine is copied into each.
This test keeps the copies identical: edit one, then `cp` it over the other."""
import filecmp
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = ["offload_core.py", "cdp.py", "vendor/ap.py", "vendor/ap.md"]


def test_engine_copies_identical():
    for skill in ("grok-offload", "deepseek-offload", "mistral-offload"):
        if not os.path.isdir(os.path.join(HERE, skill)):
            continue
        for f in SHARED:
            a = os.path.join(HERE, "aistudio-offload", f)
            b = os.path.join(HERE, skill, f)
            assert filecmp.cmp(a, b, shallow=False), f"{f} differs in {skill}"
