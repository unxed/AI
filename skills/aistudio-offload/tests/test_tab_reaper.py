"""Orphan tab cleanup in the offload browser (no real Chrome: CDP calls are faked)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cdp  # noqa: E402

DEAD = 2 ** 22 + 12345  # beyond pid_max on typical systems


class FakeConn:
    def __init__(self, ch):
        self.ch = ch

    def call(self, method, timeout=60, **p):
        if method == "Target.closeTarget":
            self.ch.pages = [t for t in self.ch.pages if t["id"] != p["targetId"]]
        elif method == "Target.createTarget":
            tid = f"T{len(self.ch.pages) + 100}"
            self.ch.pages.append({"id": tid, "type": "page", "url": p["url"]})
            return {"targetId": tid}
        return {}

    def close(self):
        pass


def chrome(tmp_path, pages, owners):
    ch = cdp.Chrome.__new__(cdp.Chrome)
    ch.port_file = str(tmp_path / "chrome.port")
    ch.pages = [{"id": i, "type": "page", "url": u} for i, u in pages]
    ch._json = lambda path: list(ch.pages)
    ch.browser = lambda: FakeConn(ch)
    os.makedirs(tmp_path / "tabs", exist_ok=True)
    for tid, pid in owners.items():
        (tmp_path / "tabs" / tid).write_text(str(pid))
    return ch


def test_closes_only_tabs_of_dead_owners(tmp_path):
    ch = chrome(tmp_path, [("A", "https://aistudio/1"), ("B", "https://aistudio/2"), ("C", "https://x.com/")],
                {"A": os.getpid(), "B": DEAD})
    closed = ch.reap_orphan_tabs()
    assert closed == ["https://aistudio/2"]  # C is unregistered but a live owner (A) exists
    assert [t["id"] for t in ch.pages] == ["A", "C"]
    assert sorted(os.listdir(tmp_path / "tabs")) == ["A"]


def test_unregistered_tabs_closed_when_nothing_alive_but_blank_kept(tmp_path):
    ch = chrome(tmp_path, [("A", "https://aistudio/1"), ("Z", "about:blank"), ("C", "https://x.com/")], {"A": DEAD})
    assert sorted(ch.reap_orphan_tabs()) == ["https://aistudio/1", "https://x.com/"]
    assert [t["url"] for t in ch.pages] == ["about:blank"]


def test_unregistered_tabs_kept_while_other_runs_alive(tmp_path):
    ch = chrome(tmp_path, [("C", "https://x.com/")], {})
    assert ch.reap_orphan_tabs(others_alive=True) == []


def test_last_page_is_replaced_by_blank(tmp_path):
    ch = chrome(tmp_path, [("A", "https://aistudio/1")], {"A": DEAD, "GONE": DEAD})
    assert ch.reap_orphan_tabs() == ["https://aistudio/1"]
    assert [t["url"] for t in ch.pages] == ["about:blank"]  # Chrome keeps running
    assert os.listdir(tmp_path / "tabs") == []  # stale record of a vanished tab dropped too


def test_new_tab_registers_and_close_unregisters(tmp_path):
    ch = chrome(tmp_path, [], {})
    ch._json = lambda path: [{"id": t["id"], "type": "page", "url": t["url"], "webSocketDebuggerUrl": "ws://x"}
                             for t in ch.pages]
    cdp.Conn, orig = (lambda url: FakeConn(ch)), cdp.Conn
    try:
        tab = ch.new_tab("https://aistudio/")
        assert (tmp_path / "tabs" / tab.tid).read_text() == str(os.getpid())
        tab.close()
        assert not (tmp_path / "tabs" / tab.tid).exists() and ch.pages == []
    finally:
        cdp.Conn = orig
