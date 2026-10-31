import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import offload_core as o


def _run(tmp_path, monkeypatch, inner):
    monkeypatch.setattr(o, "_cmd_drive", inner)
    args = types.SimpleNamespace(log=str(tmp_path / "L"))
    return args


def test_drive_log_success(tmp_path, monkeypatch, capsys):
    def inner(a):
        o.log("waiting: 15s")
        o.DRIVE_STATE.update(steps=3, last_model="m1", summary="ok")
        sys.exit(0)
    args = _run(tmp_path, monkeypatch, inner)
    with pytest.raises(SystemExit):
        o.cmd_drive(args)
    d = tmp_path / "L"
    assert "waiting: 15s" in (d / "stderr.log").read_text()
    r = json.loads((d / "result.json").read_text())
    assert r["exit"] == 0 and r["steps"] == 3 and r["last_model"] == "m1" and r["summary"] == "ok"
    assert sys.stderr is not None and not isinstance(sys.stderr, o._Tee)


def test_drive_log_failure_diag(tmp_path, monkeypatch, capsys):
    def inner(a):
        o.log("attempt 1 failed, falling back")
        print("DIAG HUNG /x/y: stuck", file=sys.stderr, flush=True)
        sys.exit(1)
    args = _run(tmp_path, monkeypatch, inner)
    with pytest.raises(SystemExit):
        o.cmd_drive(args)
    d = tmp_path / "L"
    txt = (d / "stderr.log").read_text()
    assert "falling back" in txt and "DIAG HUNG" in txt
    r = json.loads((d / "result.json").read_text())
    assert r["exit"] == 1 and r["reason"] == "DIAG HUNG /x/y: stuck"


def test_drive_log_exception(tmp_path, monkeypatch):
    def inner(a):
        raise RuntimeError("boom")
    args = _run(tmp_path, monkeypatch, inner)
    with pytest.raises(RuntimeError):
        o.cmd_drive(args)
    r = json.loads((tmp_path / "L" / "result.json").read_text())
    assert r["exit"] == 1 and "boom" in r["reason"]
