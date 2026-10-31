import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from offload_core import check_manager_tool as chk, check_router_command, classify_failure


def test_manager_gate():
    assert chk("Edit", {"file_path": "a.py"})
    assert chk("Bash", {"command": "python3 -c 1"})
    assert chk("Bash", {"command": "python3 tools/x.py"}) is None
    assert chk("Write", {"file_path": "/r/task.md"}) is None and chk("Write", {"file_path": "/r/a.md"})


def test_diag_router_and_classify():
    assert check_router_command("x diag") is not None  # unknown binary
    assert classify_failure(RuntimeError("Permission denied")) == "PERMISSION_DENIED"
