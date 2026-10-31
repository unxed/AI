"""Generation watch shared by all *-offload engines (stdlib only).

* heartbeat: every N seconds one stderr line per request in flight, so a silent wait is
  never silent:  [aistudio] waiting: model=M, elapsed=95s, answer_chars=1200 (+300), state=generating
* run status file ~/.offload-browser/run-<pid>.json (no secrets), refreshed every few seconds,
  so a caller can ask "is the generation alive?" with one command:
  `aistudio status --runs` (one-shot) / `aistudio watch` (until all runs finish).
* ui_error(): recognises error banners/toasts of the chat UI (Permission denied, rate limit...).
* retry_pause(): how long to wait before the next attempt, by failure kind.

The engine feeds an Attempt through Runs.progress(); the ticker thread does the logging and
the file, so heartbeats keep coming even while the engine is blocked in a CDP call.
"""
import atexit
import glob
import json
import os
import re
import threading
import time

ACTIVE = ("starting", "preparing", "waiting")
GROWTH_WINDOW = 10  # seconds after the last growth during which the state is still "generating"
FINISHED_SHOWN = 600  # `status --runs` lists finished runs for this long
KEEP_FILES = 86400  # run-*.json older than this are pruned

UI_ERROR_RE = re.compile(
    r"permission denied|rate.?limit|quota|exhausted|too many requests|something went wrong|"
    r"failed to generate|internal error|an error (has )?occurred|request failed|network error|"
    r"overloaded|service unavailable|try again later|couldn.t generate", re.I)


def ui_error(*texts):
    """First error message found in banner/toast/callout texts, else ''. Whole texts are
    never scanned for loose words: only a known error phrase counts."""
    for t in texts:
        for chunk in (t if isinstance(t, (list, tuple)) else [t]):
            chunk = " ".join(str(chunk or "").split())
            if chunk and UI_ERROR_RE.search(chunk):
                return chunk[:300]
    return ""


def retry_pause(err, attempt):
    """(seconds, kind) to wait after failed attempt number `attempt` (1-based)."""
    s = str(err).lower()
    if "permission denied" in s:  # comes and goes, more often right after a previous run
        return 30 * attempt, "permission denied"
    if re.search(r"rate.?limit|too many requests|\b429\b", s):
        return 20 * attempt, "rate limit"
    if re.search(r"quota|exhausted", s):
        return 5, "quota"  # per model: the next model of the chain has its own
    if "stalled" in s:
        return 5, "stalled"
    return 5 * attempt, "error"


class Attempt:
    def __init__(self, model, attempt, job, now, requested=None):
        self.model, self.attempt, self.job = model, attempt, job
        self.requested = requested or model
        self.t0 = self.last_progress = self.last_hb = now
        self.phase, self.state = "starting", "preparing"
        self.chars, self.hb_chars, self.last_growth = None, 0, None
        self.busy, self.error = False, ""
        self.end_state = ""  # done / failed

    def as_dict(self, now):
        return {"job": self.job, "model": self.model, "attempt": self.attempt,
                "requested_model": self.requested,
                "actual_model": self.model if self.end_state == "done" else None,
                "state": self.end_state or self.state, "phase": self.phase,
                "answer_chars": self.chars, "elapsed": int(now - self.t0),
                "last_progress_ts": round(self.last_progress, 1), "error": self.error}


_tls = threading.local()


def bind(att):
    """Make `att` the current thread's attempt (read by the engine's wait loop)."""
    _tls.att = att


def current():
    return getattr(_tls, "att", None)


class Runs:
    """Registry of the requests in flight of this process + heartbeat + status file."""

    def __init__(self, home, log, hb=15.0, prog="aistudio", clock=time.time, pid=None):
        self.home, self.log, self.hb, self.prog = home, log, float(hb), prog
        self.clock, self.pid = clock, pid or os.getpid()
        self.path = os.path.join(home, f"run-{self.pid}.json")
        self.atts, self.lock = [], threading.Lock()
        self.stop_ev, self.thread, self.started = threading.Event(), None, clock()
        self.closed, self.note_text, self.between_hb = False, "", clock()

    # --- engine side
    def begin(self, model, attempt, job=0, requested=None):
        att = Attempt(model, attempt, job, self.clock(), requested)
        with self.lock:
            self.atts.append(att)
            self.note_text = ""
        self.write()
        return att

    def note(self, text):
        """What the process does while no request is in flight (retry pause, patch, tests...);
        shown in the heartbeat and the status file."""
        self.note_text, self.between_hb = text, self.clock()
        self.write()

    def phase(self, name, att=None):
        att = att or current()
        if att:
            att.phase, att.state, att.last_progress = name, "preparing", self.clock()

    def progress(self, att, chars, busy=False, error=""):
        """One probe of the page: answer length, generation indicator, UI error text."""
        if not att:
            return
        now = self.clock()
        if att.chars is None or chars > att.chars:
            att.last_progress = now
            if att.chars is not None:
                att.last_growth = now
        att.chars, att.busy, att.error, att.phase = chars, busy, error or "", "waiting"
        grew = att.last_growth is not None and now - att.last_growth < GROWTH_WINDOW
        att.state = "error" if error else ("generating" if busy or grew else "idle")
        if busy:
            att.last_progress = now

    def end(self, att, state, error=""):
        if att:
            att.end_state, att.error = state, str(error or "")[:300]
            att.last_progress = self.between_hb = self.clock()
        self.write()

    # --- ticker
    def heartbeat_line(self, att, now):
        if att.chars is None:  # no page probe yet (loading/typing, or a provider without one)
            return (f"waiting: model={att.model}, elapsed={int(now - att.t0)}s, "
                    f"state={att.state}, phase={att.phase}")
        return (f"waiting: model={att.model}, elapsed={int(now - att.t0)}s, "
                f"answer_chars={att.chars} ({att.chars - att.hb_chars:+d}), state={att.state}"
                + (f", error={att.error[:120]}" if att.error else ""))

    def tick(self, now=None):
        now = self.clock() if now is None else now
        with self.lock:
            live = [a for a in self.atts if not a.end_state]
        for a in live:
            if now - a.last_hb >= self.hb:
                self.log(self.heartbeat_line(a, now))
                a.last_hb, a.hb_chars = now, a.chars or 0
        if not live and not self.closed and now - self.between_hb >= self.hb:
            self.log(f"waiting: state=between, phase={self.note_text or 'local work'}")
            self.between_hb = now
        self.write()

    def snapshot(self):
        now = self.clock()
        with self.lock:
            atts = list(self.atts)
        live = [a for a in atts if not a.end_state]
        cur = (live or atts or [None])[-1]
        d = {"pid": self.pid, "prog": self.prog, "started": round(self.started, 1),
             "updated": round(now, 1), "jobs": [a.as_dict(now) for a in atts]}
        if cur:
            d.update({k: v for k, v in cur.as_dict(now).items() if k != "job"})
            d["state"] = cur.end_state or cur.state
        else:
            d.update({"state": "starting", "model": None, "attempt": 0, "answer_chars": None,
                      "last_progress_ts": round(self.started, 1)})
        d["active"] = not self.closed
        if not live and not self.closed and atts:
            d["state"] = "between"  # no request in flight: retry pause, patch, tests
            d["phase"] = self.note_text or "local work"
        return d

    def write(self):
        try:
            os.makedirs(self.home, exist_ok=True)
            tmp = f"{self.path}.tmp{threading.get_ident()}"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(self.snapshot(), f)
            os.replace(tmp, self.path)
        except Exception:
            pass  # status is best effort, never breaks a request

    def _loop(self):
        step = max(0.2, min(5.0, self.hb))
        while not self.stop_ev.wait(step):
            self.tick()

    def start(self):
        prune(self.home, self.clock())
        self.write()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="genwatch")
        self.thread.start()
        atexit.register(self.stop)

    def stop(self):
        self.stop_ev.set()
        self.closed = True
        with self.lock:
            for a in self.atts:
                if not a.end_state:
                    a.end_state, a.error = "failed", a.error or "process exited"
        self.write()


# ---------------------------------------------------------------- reading the status files

def prune(home, now):
    for p in glob.glob(os.path.join(home, "run-*.json")):
        try:
            if now - os.path.getmtime(p) > KEEP_FILES:
                os.remove(p)
        except OSError:
            pass


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists, not ours


def list_runs(home, now=None, stall=120.0, alive=_alive):
    """Runs from run-*.json with a computed `health`:
    ok | finished | failed | DEAD (process gone while active) | HUNG (no status refresh) |
    SILENT (no progress and no generation indicator for longer than `stall`)."""
    now = time.time() if now is None else now
    out = []
    for p in sorted(glob.glob(os.path.join(home, "run-*.json"))):
        try:
            d = json.load(open(p))
        except (OSError, ValueError):
            continue
        d["silent_for"] = int(now - d.get("last_progress_ts", now))
        d["age"] = int(now - d.get("updated", now))
        if d.get("active"):
            if not alive(d.get("pid", 0)):
                d["health"] = "DEAD"
            elif d["age"] > 30:
                d["health"] = "HUNG"
            elif d["state"] == "error" or (d["state"] == "idle" and d["silent_for"] > stall):
                d["health"] = "SILENT" if d["state"] == "idle" else "error"
            else:
                d["health"] = "ok"
        else:
            if d["age"] > FINISHED_SHOWN:
                continue
            d["health"] = "finished" if d.get("state") == "done" else "failed"
        out.append(d)
    return out


def format_run(d):
    chars = "?" if d.get("answer_chars") is None else d["answer_chars"]
    s = (f"pid={d['pid']} {d.get('prog', '')} model={d.get('model')} attempt={d.get('attempt')} "
         f"state={d.get('state')} answer_chars={chars} silent_for={d['silent_for']}s "
         f"elapsed={d.get('elapsed')}s health={d['health']}")
    if d.get("error"):
        s += f" error={d['error'][:150]!r}"
    return s


def runs_ok(runs):
    """True when no active run looks broken (DEAD/HUNG/SILENT/error)."""
    return all(r["health"] in ("ok", "finished", "failed") for r in runs)
