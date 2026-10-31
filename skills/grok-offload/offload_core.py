#!/usr/bin/env python3
"""aistudio - offload LLM work to Google AI Studio's *chat UI* via a headless real Chrome.

The chat UI (aistudio.google.com) has much higher free quotas than the API, so this
tool never touches the API: it drives a real Google Chrome over a minimal raw CDP
connection (no Playwright/Selenium, which Google detects) with your Google session.

  aistudio login                    # sign in once via a web remote view (works over ssh -L)
  aistudio ask "question"           # answer -> stdout
  aistudio ask -f a.py -f b.py "refactor this"   # files are inlined
  echo prompt | aistudio ask -      # prompt from stdin
  aistudio code "task" -t "make test"   # Gemini writes an ap patch, applied + tested
  aistudio batch prompts.jsonl -j 3 # parallel, one tab per job
  aistudio serve                    # keep Chrome warm between calls (optional)

State lives in $AISTUDIO_HOME (default ~/.aistudio): profile/, cookies.json.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome, _port_open  # noqa: E402

# One Chrome profile shared by all *-offload skills: a single Google sign-in also covers
# "Sign in with Google" on Mistral/DeepSeek, and all skills reuse one running Chrome.
HOME = os.path.expanduser(os.environ.get("AISTUDIO_HOME") or os.environ.get("OFFLOAD_HOME")
                          or "~/.offload-browser")
VENDOR = "google"  # vendor of the worker model; provider wrappers override
COOKIES = os.path.join(HOME, f"cookies-{VENDOR}.json")
PROFILE = os.path.join(HOME, "profile")
PORT_FILE = os.path.join(HOME, "chrome.port")
DEFAULT_MODEL = os.environ.get("AISTUDIO_MODEL", "auto")
# `-m auto`: a quick triage call to a small Gemini picks the worker by difficulty.
# (the chat UI offers no gemini-3.5-flash / 2.5 text models any more, only TTS variants)
TIERS = {"simple": "gemini-3.5-flash-lite", "medium": "gemini-3.8-flash", "hard": "gemini-3.1-pro-preview"}
TRIAGE_MODEL = os.environ.get("AISTUDIO_TRIAGE_MODEL", "gemini-3.1-flash-lite")
# on quota/empty answers try the next model of the chain instead of hammering the same one
FALLBACK = {"gemini-3.1-pro-preview": ["gemini-pro-latest", "gemini-3.8-flash"],
            "gemini-3.8-flash": ["gemini-3-flash-preview", "gemini-flash-latest"],
            "gemini-3.5-flash-lite": ["gemini-3.1-flash-lite", "gemini-flash-lite-latest"],
            "gemini-3.1-flash-lite": ["gemini-flash-lite-latest"]}
TRIAGE_PROMPT = """You route tasks to LLMs. Rate how hard the TASK below is for a strong LLM.
simple = factual question, short rewrite/translation, trivial or boilerplate code;
medium = typical coding task: a feature or bugfix in a few files, a review, a plan;
hard = tricky algorithms, cross-cutting multi-file design, concurrency/security/perf
subtleties, proofs, or anything needing long careful reasoning.
The full prompt is {n} characters long (larger context = harder).
Reply with exactly one word: simple, medium or hard.

TASK (tail of the prompt):
<<<
{tail}
>>>"""
BASE = "https://aistudio.google.com"
GEN_RPC = "MakerSuiteService/GenerateContent"
PROG = "aistudio"  # provider wrappers (e.g. grok-offload) override these globals
LOGIN_URL = f"https://accounts.google.com/ServiceLogin?continue={BASE}/prompts/new_chat"
DONE_HOST = "aistudio.google.com"


def log(*a):
    if os.environ.get("AISTUDIO_QUIET") != "1":
        print(f"[{PROG}]", *a, file=sys.stderr, flush=True)


def _logged_in(cookies):
    names = {c["name"] for c in cookies if c["domain"].endswith("google.com")}
    return "SID" in names or "__Secure-1PSID" in names


def logged_in(cookies):  # indirection so provider wrappers can replace it
    return _logged_in(cookies)


def login_done(ch, tab, url):
    """Login page poll: session cookie present and we left the sign-in flow (Chrome may
    show a chrome:// interstitial instead of the target URL). Providers may override."""
    return logged_in(ch.cookies()) and "/signin/" not in url and "/flow/" not in url


def _save_cookies(ck):
    os.makedirs(HOME, exist_ok=True)
    fd = os.open(COOKIES, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(ck, f)


def open_chrome():
    """Running Chrome on our profile (reused if `serve`/another call started it)."""
    os.makedirs(HOME, exist_ok=True)
    fresh = not os.path.exists(PROFILE)
    ch = Chrome(PROFILE, PORT_FILE)
    if fresh and os.path.exists(COOKIES):
        ch.set_cookies(json.load(open(COOKIES)))  # e.g. cookies imported from another machine
    return ch


# ---------------------------------------------------------------- login

LOGIN_HTML = """<!doctype html><meta charset=utf-8><title>aistudio login</title>
<style>body{margin:0;background:#222;color:#eee;font:15px sans-serif}#bar{padding:8px;display:flex;gap:6px;
flex-wrap:wrap;align-items:center}#t{flex:1;min-width:240px;font-size:18px;padding:8px}button{font-size:15px;padding:6px 10px}
img{display:block;cursor:crosshair;max-width:100%;outline:none}#st{opacity:.7;font-size:12px;width:100%}</style>
<div id=bar><input id=t autofocus autocomplete=off placeholder="1) click a field in the picture  2) type or paste here  3) press Enter">
<button onclick="send(true)">Type + Enter</button><button onclick="send(false)">Type</button>
<button onclick="k('Tab')">Tab</button><button onclick="k('Backspace')">&#9003;</button>
<label><input type=checkbox id=pw onchange="t.type=this.checked?'password':'text'">hide</label>
<details style="width:100%"><summary>Sign-in blocked? Paste cookies from your normal browser instead</summary>
DevTools &rarr; Application &rarr; Cookies on the site: copy the session cookies as
<code>name=value; name2=value2</code> (X: <code>auth_token</code>, <code>ct0</code>;
Google: <code>SID</code>, <code>HSID</code>, <code>SSID</code>, <code>APISID</code>, <code>SAPISID</code>,
<code>__Secure-1PSID</code>, <code>__Secure-3PSID</code>) <input id=ck style="width:60%">
<button onclick="post('/cookies',{text:document.getElementById('ck').value})">Use cookies</button></details>
<span id=st></span></div><img id=s tabindex=0>
<script>
const s=document.getElementById('s'),st=document.getElementById('st'),t=document.getElementById('t');
let busy=false,again=false;
const post=(u,b)=>fetch(u,{method:'POST',body:JSON.stringify(b)}).then(refresh);
function k(key){post('/key',{key})}
function send(enter){const v=t.value;t.value='';post('/type',{text:v,enter})}
t.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();send(true)}};
async function refresh(){if(busy){again=true;return}busy=true;
 try{const r=await fetch('/shot?'+Date.now());const j=r.headers.get('X-Status');if(j)st.textContent=j;
  const u=URL.createObjectURL(await r.blob());s.onload=()=>URL.revokeObjectURL(u);s.src=u;
  if(j==='DONE'){st.textContent='DONE - signed in, you can close this tab';busy=false;return 'done'}}catch(e){}
 busy=false;if(again){again=false;refresh()}}
setInterval(()=>{if(!document.hidden)refresh()},1500);refresh();
s.onclick=e=>{const r=s.getBoundingClientRect();
 post('/click',{x:(e.clientX-r.left)*s.naturalWidth/r.width,y:(e.clientY-r.top)*s.naturalHeight/r.height});t.focus()};
</script>"""


def cmd_login(args):
    """Sign in without any visible window: headless real Chrome + a tiny web remote page.
    Open http://127.0.0.1:<port>/ in any browser (on a VM: `ssh -L <port>:127.0.0.1:<port> vm`)."""
    if _port_open(int(open(PORT_FILE).read() or 0) if os.path.exists(PORT_FILE) else 0):
        sys.exit("Chrome is already running (aistudio serve?). Stop it first: aistudio stop")
    ch = Chrome(PROFILE, PORT_FILE, size=(900, 680))
    tab = ch.new_tab(args.url)
    state = {"done": False}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, ctype, extra=None):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.path.startswith("/shot"):
                return self._send(LOGIN_HTML.encode(), "text/html; charset=utf-8")
            img, url = tab.screenshot(), tab.url() or ""
            st = url[:70]
            if login_done(ch, tab, url):
                _save_cookies(ch.cookies())
                state["done"] = True
                st = "DONE"
            self._send(img, "image/jpeg", {"X-Status": st})

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            if self.path == "/click":
                tab.click(req["x"], req["y"])
                time.sleep(0.25)
            elif self.path == "/type":
                if req.get("text"):
                    tab.insert_text(req["text"])
                if req.get("enter"):
                    tab.key("Enter")
                time.sleep(0.4)
            elif self.path == "/key":
                tab.key(req["key"])
            elif self.path == "/cookies":  # fallback: paste "name=value; name2=value2"
                host = args.done_host.split("/")[0]
                dom = "." + ".".join(host.split(".")[-2:])
                ck = [{"name": k.strip(), "value": v.strip(), "domain": dom, "path": "/",
                       "secure": True, "httpOnly": True, "expires": time.time() + 3e7}
                      for k, v in (p.split("=", 1) for p in req.get("text", "").split(";") if "=" in p)]
                ch.set_cookies(ck)
                tab.goto(f"https://{args.done_host}")
                time.sleep(2)
            self._send(b"ok", "text/plain")

    srv = HTTPServer(("127.0.0.1", args.port), H)
    srv.timeout = 1
    print(f"Open http://127.0.0.1:{args.port}/ and sign in there.\n"
          f"(On a remote VM first run on your laptop: ssh -L {args.port}:127.0.0.1:{args.port} <vm>)",
          flush=True)
    deadline = time.time() + args.timeout
    try:
        while not state["done"] and time.time() < deadline:
            srv.handle_request()
        for _ in range(3):  # let the page fetch the final DONE frame
            srv.handle_request()
    finally:
        tab.close()
        ch.quit()
    if not state["done"]:
        sys.exit("Timed out waiting for sign-in.")
    print(f"Logged in. Session kept in {PROFILE} (cookies backup: {COOKIES})")


def cmd_import_cookies(args):
    data = sys.stdin.read() if args.file == "-" else open(args.file).read()
    ck = json.loads(data)
    if isinstance(ck, dict) and "cookies" in ck:  # storage_state-like export
        ck = ck["cookies"]
    for c in ck:  # accept common browser-extension export formats too
        if "expirationDate" in c and "expires" not in c:
            c["expires"] = c.pop("expirationDate")
        c.setdefault("path", "/")
        ss = str(c.get("sameSite", "Lax")).capitalize()
        c["sameSite"] = {"No_restriction": "None", "Unspecified": "Lax"}.get(ss, ss)
    _save_cookies(ck)
    shutil.rmtree(PROFILE, ignore_errors=True)  # next start seeds the profile from cookies
    print(f"{len(ck)} cookies imported. Logged in: {logged_in(ck)}")


def cmd_export_cookies(args):
    ch = open_chrome()
    ck = ch.cookies()
    if ch.proc:
        ch.quit()
    _save_cookies(ck)
    print(json.dumps(ck))


# ---------------------------------------------------------------- chat

JS_BOX = "document.querySelector(\"ms-prompt-input-wrapper textarea, textarea[aria-label*='prompt' i]\")"
JS_RUN = "document.querySelector(\"ms-run-button button, button[aria-label='Run']\")"


def center_js(el):
    """JS expression -> [x, y] of the element's centre (for a real CDP click)."""
    return f"(()=>{{const r=({el}).getBoundingClientRect(); return [r.x+r.width/2, r.y+r.height/2];}})()"


def _js_str(s):
    return json.dumps(s)


JS_CLOSE_DIALOGS = """(()=>{let n=0; for (const b of document.querySelectorAll(
    '.cdk-overlay-container button, mat-dialog-container button, button')) {
    const t=(b.getAttribute('aria-label')||b.innerText||'').trim();
    if (/^(close|got it|dismiss|no thanks|not now|maybe later)$/i.test(t) && b.offsetParent) {b.click(); n++;}
  } return n;})()"""

# Capture the GenerateContent XHR inside the page: AI Studio reads it as a stream and the
# body is not retrievable via CDP afterwards, so keep the latest responseText ourselves.
JS_HOOK = """(()=>{ if (window.__ofl) return 'already';
  window.__ofl = {n:0, done:false, text:'', status:0};
  const O = XMLHttpRequest.prototype.open, S = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m, u) { this.__u = String(u); return O.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function(b) {
    if (this.__u && this.__u.includes('/GenerateContent')) {
      const x = this, st = window.__ofl = {n: window.__ofl.n + 1, done:false, text:'', status:0};
      const upd = () => { try { if (x.responseText) st.text = x.responseText; } catch (e) {} st.status = x.status; };
      x.addEventListener('readystatechange', upd); x.addEventListener('progress', upd);
      x.addEventListener('loadend', () => { upd(); st.done = true; });
    }
    return S.apply(this, arguments);
  }; return 'hooked'; })()"""


def select_model(tab, model):
    """AI Studio ignores ?model=; pick it in the model selector (sticky per account)."""
    cur = tab.c.eval("(document.querySelector('ms-model-selector [data-test-id=model-name]')||{}).innerText||''")
    if cur.strip() == model:
        return
    tab.c.eval("document.querySelector('ms-model-selector button').click()")
    tab.wait_js("document.querySelectorAll('ms-model-carousel-row').length > 0", timeout=20)
    tab.c.eval("""(()=>{const e=[...document.querySelectorAll('ms-model-carousel *')].find(e=>
        e.children.length===0 && (e.innerText||'').trim()==='All'); if (e) (e.closest('button')||e).click();})()""")
    time.sleep(1.0)
    ok = tab.c.eval(f"""(()=>{{const id=r=>(r.innerText.match(/(gemini|gemma)-[\\w.-]+/)||[''])[0];
        const r=[...document.querySelectorAll('ms-model-carousel-row')].find(r=>id(r)==={json.dumps(model)});
        if (!r) return false; (r.querySelector('button')||r).click(); return true;}})()""")
    if not ok:
        tab.key("Escape")
        raise RuntimeError(f"model {model!r} is not available in the AI Studio chat UI")
    tab.wait_js(f"(document.querySelector('ms-model-selector [data-test-id=model-name]')||{{}}).innerText==={json.dumps(model)}",
                timeout=20)


STALL_SECONDS = float(os.environ.get("OFFLOAD_STALL_SECONDS") or 180)
PROGRESS_LOG_EVERY = 30
JS_GEN_STATE = """(()=>{const o=window.__ofl||{}; const txt=o.text||''; let done=!!o.done;
  if(!done){try{JSON.parse(txt); done=txt.length>0}catch(e){}}
  const t=[...document.querySelectorAll('ms-chat-turn')].pop();
  const e=t&&t.querySelector('[class*=error]'); const err=e&&e.innerText.trim()?e.innerText.trim():'';
  const rb=document.querySelector('ms-run-button');
  return {done, err, n:txt.length, turn:t?(t.innerText||'').length:0,
          busy:!!(rb&&/stop/i.test((rb.innerText||'')+(rb.getAttribute('aria-label')||'')))
              || !!document.querySelector('button[aria-label*="Stop" i]')};})()"""


class StallError(RuntimeError):
    pass


def stall_decision(size, last_size, last_change, now, stall_s):
    """Pure progress watchdog step -> (new_last_size, new_last_change, stalled).
    `size` is the current amount of generated output (chars); stalled = no growth for stall_s."""
    if size > last_size:
        return size, now, False
    return last_size, last_change, (now - last_change) >= stall_s


def wait_generation(tab, timeout, stall_s=None):
    """Wait for the answer; returns 'DONE' or 'ERR:<text>'. Logs progress every 30 s and raises
    StallError when the output does not grow for the stall window (default 180 s)."""
    stall_s = stall_s or STALL_SECONDS
    start = time.time()
    last_size, last_change, last_log, seen_busy, gone_since = 0, start, start, False, None
    while True:
        now = time.time()
        if now - start > timeout:
            raise TimeoutError("timeout waiting for the answer (window.__ofl)")
        try:
            st = tab.c.eval(JS_GEN_STATE, timeout=20) or {}
        except RuntimeError:
            st = {}
        if st.get("done"):
            return "DONE"
        if st.get("err"):
            return "ERR:" + st["err"]
        size = max(st.get("n", 0), st.get("turn", 0))
        last_size, last_change, stalled = stall_decision(size, last_size, last_change, now, stall_s)
        if now - last_log >= PROGRESS_LOG_EVERY:
            log(f"generating: {size} chars, {int(now - start)}s")
            last_log = now
        if st.get("busy"):
            seen_busy, gone_since = True, None
        elif seen_busy and size == 0:
            gone_since = gone_since or now
            if now - gone_since >= 20:
                raise RuntimeError("Empty answer: the generation indicator disappeared with no response")
        if stalled:
            raise StallError(f"STALLED: no output growth for {int(now - last_change)}s "
                             f"(size {size} chars, {int(now - start)}s since start)")
        tab.c.pump(1.0)


def ask_tab(ch, prompt, model=DEFAULT_MODEL, system=None, timeout=900):
    tab = ch.new_tab(f"{BASE}/prompts/new_chat")
    try:
        tab.wait_js(f"!!{JS_BOX} || location.host.startsWith('accounts.')", timeout=90)
        if "accounts.google.com" in (tab.url() or ""):
            raise RuntimeError("Session expired: run `aistudio login` again.")
        time.sleep(1.5)  # late announcement/upsell dialogs
        tab.c.eval(JS_CLOSE_DIALOGS)
        select_model(tab, model)
        if system:
            tab.c.eval("""(()=>{const b=[...document.querySelectorAll('button')].find(b=>
                /System instructions/i.test(b.innerText||b.getAttribute('aria-label')||''));
                if(b) b.click();})()""")
            tab.wait_js("!!document.querySelector(\"textarea[aria-label*='System instructions' i]\")", 15)
            tab.c.eval(_fill_js("document.querySelector(\"textarea[aria-label*='System instructions' i]\")",
                                system))
            tab.key("Escape")
        tab.c.eval(JS_HOOK)
        # Real browser input (CDP Input.*) instead of JS-set values and el.click(): the page
        # gets the same trusted events a user's paste and click produce.
        # (multi-line Input.insertText is slow - ~1 min per 100k chars - so a long prompt
        # is set via JS and only its tail is typed for real)
        head, tail = (prompt[:-200], prompt[-200:]) if len(prompt) > 4000 else ("", prompt)
        if head:
            tab.c.eval(_fill_js(JS_BOX, head), timeout=120)
        tab.c.eval(f"(()=>{{const e={JS_BOX}; e.focus(); e.setSelectionRange(e.value.length, e.value.length);}})()")
        tab.c.call("Input.insertText", text=tail, timeout=120)
        if tab.c.eval(f"{JS_BOX}.value.length") < len(prompt.strip()) // 2:
            tab.c.eval(_fill_js(JS_BOX, prompt), timeout=120)  # fallback
        tab.wait_js(f"{JS_RUN} && !{JS_RUN}.disabled", timeout=60)
        started = False
        for _ in range(3):  # a dialog may swallow the first click
            tab.c.eval(JS_CLOSE_DIALOGS)
            # the informational cookie bar ("... uses cookies", only a Hide button) covers Run
            tab.c.eval("""(()=>{const b=document.querySelector('.glue-cookie-notification-bar');
                const h=b && [...b.querySelectorAll('button,a')].find(e=>/^(hide|ok|got it)$/i
                .test((e.innerText||'').trim())); if (h) h.click();})()""")
            tab.c.eval(f"{JS_RUN}.scrollIntoView({{block:'center'}})")
            x, y = tab.c.eval(center_js(JS_RUN))
            if tab.c.eval(f"{JS_RUN}.contains(document.elementFromPoint({x},{y}))"):
                tab.click(x, y)
            else:
                log("Run button is covered by an overlay; clicking it from JS")
                tab.c.eval(f"{JS_RUN}.click()")
            try:
                tab.wait_js("window.__ofl && window.__ofl.n > 0", timeout=20)
                started = True
                break
            except TimeoutError:
                continue
        if not started:
            err = tab.c.eval("(document.querySelector('ms-callout, .error, [role=alert]')||{}).innerText||''")
            raise RuntimeError(f"Run did not start (quota? dialog?). {err}")
        # done, or an error shown in the model turn (quota, "Permission denied", safety...)
        # (the XHR may stay open after the answer: complete = the streamed JSON array parses)
        res = wait_generation(tab, timeout)
        if res.startswith("ERR:"):
            raise RuntimeError(f"AI Studio error: {res[4:][:300]}")
        st = tab.c.eval("window.__ofl")
        raw = st.get("text") or ""
        if st.get("status") not in (200, 0) or not raw:
            raise RuntimeError(f"HTTP {st.get('status')}: {raw[:300]}")
        text = parse_generate(raw)
        if not text.strip():
            err = tab.c.eval("(document.querySelector('ms-callout, .error, [role=alert]')||{}).innerText||''")
            raise RuntimeError(f"Empty answer (quota/safety?). {err or raw[:300]}")
        return text
    finally:
        tab.close()


_GEMINI_ASK_TAB = ask_tab


def is_gemini():
    """True unless a provider wrapper (e.g. grok.py) replaced ask_tab."""
    return globals()["ask_tab"] is _GEMINI_ASK_TAB


# ---------------------------------------------------------------- limits + diagnostics

DEFAULT_MAX_CONTEXT = 400_000
EXIT_CONTEXT = 3
_tls = threading.local()
RUN = {"files": None}  # set by commands for the diagnostics summary


class ContextTooLarge(Exception):
    def __init__(self, total, limit, sizes, nfiles):
        self.total, self.limit, self.sizes, self.nfiles = total, limit, sizes, nfiles
        super().__init__(f"packed context is {total:,} chars in {nfiles} files, limit {limit:,}")


def max_context(arg=None):
    """Context limit in chars: --max-context, else $OFFLOAD_MAX_CONTEXT, else 400k."""
    if arg:
        return int(arg)
    try:
        return int(os.environ.get("OFFLOAD_MAX_CONTEXT") or DEFAULT_MAX_CONTEXT)
    except ValueError:
        return DEFAULT_MAX_CONTEXT


REASONS = ("STALLED", "QUOTA", "RATE_LIMIT", "PERMISSION_DENIED", "CONTEXT_TOO_LARGE", "NOT_LOGGED_IN", "SAFETY",
           "EMPTY_ANSWER", "TIMEOUT", "UI_CHANGED", "PATCH_FAILED", "TESTS_FAILED", "UNKNOWN")
_CLASSIFY = (
    ("NOT_LOGGED_IN", r"session expired|log ?in again|sign in to continue|accounts\.google\.com|not logged"),
    ("STALLED", r"stalled: no output growth"),
    ("PERMISSION_DENIED", r"permission denied|permission_denied|\b403\b"),
    ("CONTEXT_TOO_LARGE", r"too many tokens|token limit|context (length|window|limit)|too long|too large|"
                          r"exceeds? the (maximum|limit)|input token|\b413\b|payload"),
    ("RATE_LIMIT", r"rate.?limit|too many requests|\b429\b|slow down"),
    ("QUOTA", r"quota|resource_exhausted|exhausted|usage limit|daily limit|limit reached|out of (credits|messages)"),
    ("SAFETY", r"safety|blocked|prohibited|policy|moderation|harmful|recitation"),
    ("EMPTY_ANSWER", r"empty answer"),
)


def classify_failure(exc, *texts):
    """Short reason code for a failed model request from the exception and collected page texts."""
    import re
    msg = re.sub(r"\([^()]*\?\)", "", f"{exc}") if exc is not None else ""  # drop our "(quota? dialog?)" hints
    blob = "\n".join([msg, *[t for t in texts if t]]).lower()
    for code, rx in _CLASSIFY:
        if re.search(rx, blob):
            return code
    if isinstance(exc, TimeoutError) or "timed out" in blob or "timeout" in blob:
        # waiting for the answer = TIMEOUT; waiting for some page element = the UI changed
        return "TIMEOUT" if "__ofl" in blob or not isinstance(exc, TimeoutError) else "UI_CHANGED"
    if re.search(r"run did not start|not available in the .* chat ui|queryselector|cdp|no such|unexpected", blob):
        return "UI_CHANGED"
    return "UNKNOWN"


JS_ALERTS = """(()=>{const out=[]; const sel='ms-callout, [role=alert], .error, mat-snack-bar-container, '+
  'mat-snack-bar, simple-snack-bar, [class*=snack], [class*=toast]';
  document.querySelectorAll(sel).forEach(e=>{const t=(e.innerText||'').trim(); if(t) out.push(e.tagName.toLowerCase()+': '+t)});
  const ts=document.querySelectorAll('ms-chat-turn'); if(ts.length) out.push('LAST ms-chat-turn: '+ts[ts.length-1].innerText);
  return out.join('\\n---\\n');})()"""
JS_SELECTED = "(document.querySelector('ms-model-selector [data-test-id=model-name]')||{}).innerText||''"


def snapshot_tab(tab):
    """Everything useful about a tab that is about to be closed after a failure. Never raises."""
    snap = {}

    def grab(key, fn):
        try:
            snap[key] = fn()
        except Exception as e:
            snap[key] = None
            snap.setdefault("errors", []).append(f"{key}: {type(e).__name__}: {e}")
    grab("url", lambda: tab.url())
    grab("page", lambda: (tab.c.eval("document.body.innerText", timeout=15) or "")[-20000:])
    grab("alerts", lambda: tab.c.eval(JS_ALERTS, timeout=15) or "")
    grab("ofl", lambda: tab.c.eval("window.__ofl ? {n:window.__ofl.n, done:window.__ofl.done, "
                                   "status:window.__ofl.status, text:(window.__ofl.text||'').slice(0,2000)} : null", timeout=15))
    grab("selected", lambda: (tab.c.eval(JS_SELECTED, timeout=15) or "").strip())
    grab("shot", lambda: tab.screenshot())
    return snap


class _DiagChrome:
    """Wraps Chrome for ask_tab calls (any provider): a tab closed while an exception is
    propagating (ask_tab's `finally`) is snapshotted first, before the page is lost."""

    def __init__(self, ch):
        self._ch = ch

    def __getattr__(self, name):
        return getattr(self._ch, name)

    def new_tab(self, *a, **k):
        tab = self._ch.new_tab(*a, **k)
        orig = tab.close

        def close():
            if sys.exc_info()[0] is not None:
                try:
                    _tls.snap = snapshot_tab(tab)
                except Exception:
                    pass
            return orig()
        tab.close = close
        return tab


def _oneline(x, n=300):
    return " ".join(str(x).split())[:n]


def write_diag(exc, ctx=None, snap=None, reason=None, detail=""):
    """Save ~/.offload-browser/diag/<utc>-<pid>/ and return (reason, dir). Never raises."""
    try:
        ctx, snap = ctx or {}, snap or {}
        alerts, page = snap.get("alerts") or "", snap.get("page") or ""
        if not reason:
            raw = snap["ofl"].get("text") if isinstance(snap.get("ofl"), dict) else ""
            reason = classify_failure(exc, alerts, raw, detail)
            if reason == "UNKNOWN" and page:  # page text last: it holds unrelated words (footer, menus)
                reason = classify_failure(exc, alerts, raw, detail, page[-3000:])
        base = os.path.join(HOME, "diag", f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}")
        d, i = base, 1
        while os.path.exists(d):
            i += 1
            d = f"{base}-{i}"
        os.makedirs(d, exist_ok=True)
        ofl = snap.get("ofl")
        lines = [f"reason: {reason}",
                 f"command: {ctx.get('command') or ' '.join(sys.argv)}",
                 f"provider: {PROG} ({VENDOR})",
                 f"model_requested: {ctx.get('model_requested')}",
                 f"model_selected: {snap.get('selected') or ctx.get('model_selected') or 'n/a'}",
                 f"prompt_chars: {ctx.get('prompt_chars')}",
                 f"files: {ctx.get('files') if ctx.get('files') is not None else RUN.get('files')}",
                 f"elapsed_s: {round(time.time() - ctx['t0'], 1) if ctx.get('t0') else 'n/a'}",
                 f"exception: {type(exc).__name__}: {_oneline(exc, 2000)}" if exc is not None else "exception: -",
                 f"page_url: {snap.get('url')}",
                 f"__ofl: {json.dumps({k: v for k, v in ofl.items() if k != 'text'}) if isinstance(ofl, dict) else None}",
                 f"raw_response_head: {(ofl or {}).get('text', '')[:2000] if isinstance(ofl, dict) else ''}"]
        if detail:
            lines.append(f"detail:\n{detail[-3000:]}")
        if snap.get("errors"):
            lines.append("snapshot_errors: " + "; ".join(snap["errors"]))
        for name, content in (("summary.txt", "\n".join(lines) + "\n"), ("page.txt", page), ("alerts.txt", alerts)):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(content)
        if isinstance(snap.get("shot"), (bytes, bytearray)):
            with open(os.path.join(d, "screenshot.jpg"), "wb") as f:
                f.write(snap["shot"])
        return reason, d
    except Exception:
        return reason or "UNKNOWN", ""


def attach_diag(exc, ctx=None, snap=None, reason=None, detail=""):
    """Write a bundle for `exc` and set exc.diag_line = 'DIAG <REASON> <dir>: <message>'."""
    reason, d = write_diag(exc, ctx, snap, reason, detail)
    try:
        exc.diag_reason, exc.diag_dir = reason, d
        exc.diag_line = f"DIAG {reason} {d}: {_oneline(exc) or type(exc).__name__}"
    except Exception:
        pass
    return exc


def fail_exit(exc, code=1):
    """Exit non-zero with the DIAG line (when there is one) as the final message."""
    line = getattr(exc, "diag_line", None) or f"ERROR: {exc or type(exc).__name__}"
    print(line, file=sys.stderr, flush=True)
    sys.exit(code)


def context_fail(e, what="ask", ctx=None):
    """Exit 3 with a message listing the largest files, never truncating."""
    top = sorted(e.sizes, key=lambda x: -x[1])[:15]
    hint = ("pass only the relevant files with `-p <paths...>`" if what == "code"
            else "pass fewer -f files")
    print(f"CONTEXT_TOO_LARGE: packed context is {e.total:,} chars in {e.nfiles} files, limit {e.limit:,} "
          f"(--max-context N / OFFLOAD_MAX_CONTEXT). Nothing was sent.\n15 largest files:", file=sys.stderr)
    for f, n in top:
        print(f"  {n:>10,}  {f}", file=sys.stderr)
    print(f"The caller must narrow the context: {hint}.", file=sys.stderr)
    attach_diag(e, ctx, reason="CONTEXT_TOO_LARGE",
                detail="\n".join(f"{n} {f}" for f, n in top))
    print(e.diag_line, file=sys.stderr, flush=True)
    sys.exit(EXIT_CONTEXT)


def _fill_js(el, text):
    """Set a textarea value the way Angular notices (native setter + input event)."""
    return f"""(()=>{{const e={el}; const v={_js_str(text)};
        const set=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;
        e.focus(); set.call(e, v); e.dispatchEvent(new Event('input',{{bubbles:true}}));
        e.dispatchEvent(new Event('change',{{bubbles:true}})); return e.value.length;}})()"""


def parse_generate(raw):
    """Extract the visible answer text from a GenerateContent stream body.

    The body is a JSON array of chunks (protobuf-as-JSON). A text part looks like
    [null, "text", ...] and thought parts carry a 1 at index 12. We walk all
    chunks and concatenate non-thought text parts in order."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # streamed bodies may be ")]}'"-prefixed or truncated
        raw = raw[raw.find("["):]
        data = json.loads(raw)
    out = []

    def is_part(x):
        return (isinstance(x, list) and len(x) >= 2 and x[0] is None
                and isinstance(x[1], str))

    def walk(x):
        if is_part(x):
            thought = len(x) > 12 and x[12] == 1
            if not thought:
                out.append(x[1])
            return
        if isinstance(x, list):
            for y in x:
                walk(y)

    walk(data)
    return "".join(out)


def build_prompt(text, files, limit=None):
    """Inline `files` before the task. Raises ContextTooLarge (never truncates) when the
    result would exceed `limit` chars (default: max_context())."""
    limit = limit or max_context()
    parts, sizes = [], []
    for f in files or []:
        body = open(f, encoding="utf-8", errors="replace").read()
        sizes.append((f, len(body)))
        parts.append(f"=== FILE: {f} ===\n{body}\n=== END FILE: {f} ===")
    parts.append(text)
    out = "\n\n".join(parts)
    if len(out) > limit:
        raise ContextTooLarge(len(out), limit, sizes + [("<prompt text>", len(text))], len(sizes))
    return out


def choose_model(ch, prompt):
    """Pick a worker model for `prompt` with one fast triage call (no user input,
    no tokens from the calling agent). Falls back to the medium tier."""
    try:
        ans = ask_tab(ch, TRIAGE_PROMPT.format(n=len(prompt), tail=prompt[-6000:]),
                      TRIAGE_MODEL, timeout=120)
        tier = next((t for t in ("hard", "medium", "simple") if t in ans.lower()), "medium")
    except Exception as e:
        log(f"triage failed ({e}); using medium tier")
        tier = "medium"
    if len(prompt) > 600_000 and tier == "simple":
        tier = "medium"
    log(f"auto model: {tier} -> {TIERS[tier]}")
    return TIERS[tier]


def ask_many(jobs, jobs_n=3, retries=2):
    """jobs: list of (prompt, model, system). Returns list of text or Exception.
    Runs up to jobs_n tabs in parallel in one Chrome."""
    ch = open_chrome()
    owned = ch.proc is not None  # we started it -> we stop it

    dch = _DiagChrome(ch)

    def one(job):
        prompt, model, system = job
        model = model or DEFAULT_MODEL
        ctx = {"command": " ".join(sys.argv), "model_requested": model, "prompt_chars": len(prompt),
               "files": RUN.get("files"), "t0": time.time()}
        if model == "auto" and is_gemini():  # Gemini only; Grok has its own auto
            model = choose_model(ch, prompt)
        chain = [model] + FALLBACK.get(model, [])
        for attempt in range(retries + 1):
            m = chain[min(attempt, len(chain) - 1)]
            _tls.snap = None
            try:
                out = globals()["ask_tab"](dch, prompt, m, system)
                log(f"answered by {m}")  # may be a fallback model: name it in reports/PRs
                return out
            except Exception as e:
                if attempt == retries or "login" in str(e):
                    ctx["model_selected"] = m
                    return attach_diag(e, ctx, getattr(_tls, "snap", None))
                if isinstance(e, StallError):  # keep evidence of each stall, then retry in a fresh tab
                    ctx["model_selected"] = m
                    _, sd = write_diag(e, ctx, getattr(_tls, "snap", None), "STALLED")
                    log(f"{m}: STALLED, diagnostics in {sd}")
                log(f"{m}: attempt {attempt + 1} failed: {e or type(e).__name__}; retrying")
                # "Permission denied" comes and goes (more often right after a previous run):
                # back off longer instead of hammering the account.
                time.sleep((30 if "Permission denied" in str(e) else 5) * (attempt + 1))

    try:
        with ThreadPoolExecutor(max(1, jobs_n)) as ex:
            return list(ex.map(one, jobs))
    finally:
        if owned:
            ch.quit()


def cmd_serve(args):
    ch = open_chrome()
    if not ch.proc:
        print(f"Chrome already running on port {ch.port}")
        return
    print(f"Chrome running on port {ch.port}; `aistudio stop` to stop.", flush=True)
    try:
        ch.proc.wait()
    except KeyboardInterrupt:
        ch.quit()


def cmd_stop(args):
    if os.path.exists(PORT_FILE):
        ch = Chrome.__new__(Chrome)
        ch.port_file, ch.proc = PORT_FILE, None
        ch.port = int(open(PORT_FILE).read() or 0)
        ch.quit()
    print("stopped")


def set_stall(args):
    global STALL_SECONDS
    if getattr(args, "stall", None):
        STALL_SECONDS = float(args.stall)


def cmd_ask(args):
    set_stall(args)
    text = sys.stdin.read() if args.prompt == "-" else args.prompt
    lim = max_context(getattr(args, "max_context", None))
    ctx = {"command": " ".join(sys.argv), "model_requested": args.model, "files": len(args.file or [])}
    try:
        prompt = build_prompt(text, args.file, lim)
    except ContextTooLarge as e:
        ctx["prompt_chars"] = e.total
        context_fail(e, "ask", ctx)
    RUN["files"] = len(args.file or [])
    log(f"context: {RUN['files']} files, {len(prompt)} chars")
    ans = ask_many([(prompt, args.model, args.system)])[0]
    if isinstance(ans, Exception):
        fail_exit(ans)
    if args.out:
        open(args.out, "w").write(ans)
        log(f"answer written to {args.out} ({len(ans)} chars)")
    else:
        sys.stdout.write(ans if ans.endswith("\n") else ans + "\n")


def cmd_batch(args):
    """jsonl lines: {"id":..., "prompt":..., "model"?:..., "files"?:[...]} -> results jsonl."""
    jobs = [json.loads(line) for line in open(args.file) if line.strip()]
    built = []
    for j in jobs:
        try:
            built.append((build_prompt(j["prompt"], j.get("files")), j.get("model", args.model), j.get("system")))
        except ContextTooLarge as e:
            built.append(attach_diag(e, {"command": f"batch job {j.get('id')}", "prompt_chars": e.total},
                                     reason="CONTEXT_TOO_LARGE"))
    ok = [b for b in built if not isinstance(b, Exception)]
    it = iter(ask_many(ok, args.jobs) if ok else [])
    res = [b if isinstance(b, Exception) else next(it) for b in built]
    for j, r in zip(jobs, res):
        out = {"id": j.get("id")}
        out.update({"error": getattr(r, "diag_line", None) or str(r) or type(r).__name__}
                   if isinstance(r, Exception) else {"text": r})
        print(json.dumps(out, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- code (ap patches)

HERE = os.path.dirname(os.path.abspath(__file__))
AP_PY = os.path.join(HERE, "vendor", "ap.py")
AP_MD = os.path.join(HERE, "vendor", "ap.md")
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".wasm", ".woff", ".woff2",
            ".ttf", ".pdf", ".zip", ".gz", ".xz", ".tar", ".so", ".o", ".a", ".exe", ".dll", ".pyc",
            ".jar", ".class", ".mp3", ".mp4", ".lock")


def pack_tree(root, paths=None):
    """Text files (read-only) as [(path, body)]. In a git repo only tracked files are used;
    `paths` limits to given files/dirs."""
    root = os.path.abspath(root)
    try:
        files = subprocess.run(["git", "-C", root, "ls-files", "-z", "--", *(paths or [])],
                               capture_output=True, text=True, check=True).stdout.split("\0")
    except Exception:
        files = []
        for p in (paths or ["."]):
            full = os.path.join(root, p)
            if os.path.isfile(full):
                files.append(p)
            for d, dirs, fs in os.walk(full):
                dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in
                                 ("node_modules", "__pycache__", "venv", ".venv", "dist", "build"))
                files += [os.path.relpath(os.path.join(d, f), root) for f in sorted(fs)]
    items = []
    for f in filter(None, files):
        full = os.path.join(root, f)
        if f.lower().endswith(SKIP_EXT) or not os.path.isfile(full) or os.path.islink(full):
            continue
        try:
            body = open(full, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        items.append((f, body))
    return items


def render_tree(items):
    return "\n\n".join(f"=== BEGIN {f} ===\n{body}{'' if body.endswith(chr(10)) else chr(10)}=== END {f} ==="
                        for f, body in items)


def combine_tree(root, paths=None, max_chars=None, extra=0):
    """Concatenate source files as `=== BEGIN path ===` blocks. Never truncates: raises
    ContextTooLarge when the result (+ `extra` chars of task text) exceeds `max_chars`."""
    items = pack_tree(root, paths)
    text = render_tree(items)
    if max_chars and len(text) + extra > max_chars:
        raise ContextTooLarge(len(text) + extra, max_chars, [(f, len(b)) for f, b in items], len(items))
    return text


CODE_RULES = """You are a senior engineer. Implement the TASK below in the given codebase.
Reply with exactly ONE patch in the 'ap' format (spec above), inside a single ```ap fenced block.
Rules: snippets must be copied verbatim from the current files and be unique; prefer small
REPLACE/INSERT_AFTER edits; create new files with CREATE_FILE (or REPLACE on a new FILE as the
spec allows); keep the project's code style; add or update tests when it makes sense.
After the code block you may add at most 5 lines of explanation.
NEVER answer with a unified diff / git diff / `--- a/ +++ b/ @@` hunks / whole-file dumps: line
numbers in diff headers are always miscounted. Only the 'ap' format is accepted."""

DIFF_RE = r"(?m)^(diff --git |--- (a/|/dev/null)|\+\+\+ (b/|/dev/null)|@@ -\d+(,\d+)? \+\d+(,\d+)? @@)"


def extract_patch(ans):
    import re
    m = re.findall(r"```(?:ap|text)?[ \t]*\n(.*?)```", ans, re.S)
    if m:
        return max(m, key=len)
    return ans


def looks_like_diff(text):
    """True if the answer is a unified diff, which is forbidden (ap only)."""
    import re
    return bool(re.search(DIFF_RE, text))


_FAIL_RE = None


def failure_excerpt(out, limit=6000, tail=1500):
    """The parts of a long test/CI log a model needs: every error block (Traceback, ERROR:,
    FAIL, panic, compiler `error:`) with some context, plus the end of the log. A plain tail
    misses e.g. an import error printed before hundreds of passing tests."""
    import re
    global _FAIL_RE
    _FAIL_RE = _FAIL_RE or re.compile(
        r"Traceback \(most recent|^(ERROR|FAIL)[: ]|^--- FAIL|^panic:|\berror(\[\w+\])?:|"
        r"Error:|^E\s{3}|FAILED", re.M | re.I)
    if len(out) <= limit:
        return out
    lines, keep = out.splitlines(), set()
    for i, ln in enumerate(lines):
        if _FAIL_RE.search(ln):
            keep.update(range(max(0, i - 2), min(len(lines), i + 25)))
    blocks, prev = [], -2
    for i in sorted(keep):
        if i != prev + 1:
            blocks.append("...")
        blocks.append(lines[i])
        prev = i
    head = "\n".join(blocks)[: limit - tail]
    return f"{head}\n...\n[end of log]\n{out[-tail:]}"


def _small_machine():
    """True on tiny VMs (< 2 GB RAM, e.g. GCP e2-micro): no local builds/tests there."""
    try:
        kb = int(open("/proc/meminfo").read().split("MemTotal:")[1].split()[0])
    except Exception:
        return False
    return kb < 2_000_000 and os.environ.get("OFFLOAD_ALLOW_LOCAL_BUILD") != "1"


def _run(root, *cmd, check=True):
    r = subprocess.run(list(cmd), cwd=root, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}: {(r.stderr or r.stdout).strip()[-500:]}")
    return r.stdout.strip()


def ci_check(root, branch, base, title, body, message, timeout):
    """Commit the working tree to `branch`, push it, make sure a draft PR exists (CI
    usually runs on pull_request) and wait for the GitHub Actions runs of that commit.
    Returns (passed, failure_log)."""
    if _run(root, "git", "rev-parse", "--abbrev-ref", "HEAD") != branch:
        _run(root, "git", "checkout", "-B", branch)
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-q", "-m", message, check=False)
    _run(root, "git", "push", "-q", "-f", "-u", "origin", branch)
    url = _run(root, "gh", "pr", "view", branch, "--json", "url", "-q", ".url", check=False)
    if not url:
        url = _run(root, "gh", "pr", "create", "--draft", "--base", base, "--head", branch,
                   "--title", title, "--body", body)
    sha = _run(root, "git", "rev-parse", "HEAD")
    log(f"CI: pushed {sha[:8]} to {branch} ({url}); waiting for checks")
    deadline, seen = time.time() + timeout, 0
    while time.time() < deadline:
        time.sleep(30)
        runs = json.loads(_run(root, "gh", "run", "list", "--commit", sha, "--json",
                               "databaseId,status,conclusion,name", check=False) or "[]")
        if not runs:
            seen += 1
            if seen > 20:
                return False, "No GitHub Actions run started for this commit (no CI configured?)."
            continue
        if all(r["status"] == "completed" for r in runs):
            bad = [r for r in runs if r["conclusion"] not in ("success", "skipped", "neutral")]
            if not bad:
                return True, ""
            out = "\n".join(_run(root, "gh", "run", "view", str(r["databaseId"]), "--log-failed",
                                 check=False) for r in bad)
            return False, failure_excerpt(out, limit=8000)
    return False, f"CI did not finish within {timeout}s"


def cmd_code(args):
    set_stall(args)
    root = os.path.abspath(args.dir)
    task = sys.stdin.read() if args.task == "-" else args.task
    if args.task_file:
        task = open(args.task_file).read() + "\n" + (task or "")
    if args.test and not args.ci and _small_machine():
        sys.exit("ERROR: this machine has < 2 GB RAM: builds/tests must not run here. Use --ci "
                 "(GitHub Actions on a draft PR) instead of -t, or set OFFLOAD_ALLOW_LOCAL_BUILD=1.")
    branch = args.ci_branch or f"offload/{time.strftime('%Y%m%d-%H%M%S')}"
    title = (task or "").strip().splitlines()[0].lstrip("# ")[:70] if task else "Offloaded change"
    spec = open(AP_MD).read()
    history = ""
    lim = max_context(getattr(args, "max_context", None))
    t0, last_reason, last_detail = time.time(), None, ""
    dctx = {"command": " ".join(sys.argv), "model_requested": args.model, "t0": t0}
    for rnd in range(1, args.rounds + 1):
        items = pack_tree(root, args.paths)
        tree = render_tree(items)
        RUN["files"] = dctx["files"] = len(items)
        dctx["prompt_chars"] = len(tree) + len(task or "")
        log(f"context: {len(items)} files, {len(tree) + len(task or '')} chars")
        if len(tree) + len(task or "") > lim:
            context_fail(ContextTooLarge(len(tree) + len(task or ""), lim, [(f, len(b)) for f, b in items],
                                         len(items)), "code", dctx)
        prompt = (f"<ap_spec>\n{spec}\n</ap_spec>\n\n<codebase>\n{tree}\n</codebase>\n\n"
                  f"{CODE_RULES}\n\nTASK:\n{task}\n{history}")
        log(f"round {rnd}: asking {args.model} ({len(prompt)} chars of context)")
        ans = ask_many([(prompt, args.model, None)])[0]
        if isinstance(ans, Exception):
            fail_exit(ans)
        patch = extract_patch(ans)
        if looks_like_diff(patch):
            log(f"round {rnd}: the model answered with a unified diff, which is forbidden")
            last_reason, last_detail = "PATCH_FAILED", "the model answered with a unified diff"
            history = ("\nYOUR PREVIOUS ANSWER WAS A UNIFIED DIFF. Diffs are forbidden: the line counts in "
                       "their headers are always wrong. Nothing was applied. Answer ONLY in the 'ap' "
                       "format from the spec above, inside one ```ap block.")
            continue
        pfile = os.path.join(root, ".afix.ap")
        # the patcher refuses to run while a stale afailed.ap is around
        for stale in ("afailed.ap", "afailed.md"):
            if os.path.exists(os.path.join(root, stale)):
                os.remove(os.path.join(root, stale))
        open(pfile, "w").write(patch)
        # Tolerant mode (default, no -s): ap self-heals what it can (fuzzy locators, ID drift,
        # missing header...), applies every modification that resolves and writes the ones that
        # do not to afailed.ap plus a repair briefing for the model to afailed.md.
        ap = subprocess.run([sys.executable, AP_PY, pfile, "--dir", root],
                            capture_output=True, text=True)
        if ap.returncode != 0:
            err = (ap.stdout + ap.stderr)[-3000:]
            log(f"round {rnd}: patch not (fully) applied:\n{err}")
            last_reason, last_detail = "PATCH_FAILED", err
            brief = os.path.join(root, "afailed.md")
            if os.path.exists(brief):
                history = ("\nYOUR PREVIOUS PATCH WAS ONLY PARTLY APPLIED by the ap patcher (the codebase "
                           "above already contains the modifications that applied). Its repair briefing:\n"
                           + open(brief, encoding="utf-8").read()[:30000]
                           + "\nSend a NEW ap patch (ap format only, never a diff) with only the fixes.")
            else:
                history = (f"\nYOUR PREVIOUS PATCH FAILED TO APPLY (files are unchanged):\n"
                           f"```ap\n{patch}\n```\nPatcher output:\n{err}\n"
                           "Send a corrected full ap patch (never a diff).")
            for stale in ("afailed.ap", "afailed.md", ".afix.ap"):
                if os.path.exists(os.path.join(root, stale)):
                    os.remove(os.path.join(root, stale))
            continue
        os.remove(pfile)
        log(f"round {rnd}: patch applied")
        if args.ci:
            ok, out = ci_check(root, branch, args.ci_base, title, args.ci_body or
                               f"Draft opened by `{PROG} code --ci`; CI is the test runner.",
                               f"{title} (round {rnd})", args.test_timeout)
            if ok:
                log(f"round {rnd}: CI passed on {branch}")
                print(ans)
                return
            log(f"round {rnd}: CI failed:\n{out[-1500:]}")
            last_reason, last_detail = "TESTS_FAILED", out
            history = (f"\nA previous patch WAS APPLIED (the codebase above already contains it) but "
                       f"the CI checks failed:\n{out}\nSend a patch that fixes it.")
            continue
        if not args.test:
            print(ans)
            return
        t = subprocess.run(args.test, shell=True, cwd=root, capture_output=True, text=True,
                           timeout=args.test_timeout)
        if t.returncode == 0:
            log(f"round {rnd}: tests passed")
            print(ans)
            return
        out = failure_excerpt(t.stdout + t.stderr)
        log(f"round {rnd}: tests failed:\n{out[-1500:]}")
        last_reason, last_detail = "TESTS_FAILED", out
        history = (f"\nA previous patch WAS APPLIED (the codebase above already contains it) but "
                   f"the test command `{args.test}` failed:\n{out}\nSend a patch that fixes it.")
    e = RuntimeError(f"FAILED after {args.rounds} rounds ({last_reason or 'UNKNOWN'}): {_oneline(last_detail, 200)}")
    attach_diag(e, dctx, reason=last_reason or "UNKNOWN", detail=last_detail)
    fail_exit(e)



# ---------------------------------------------------------------- router gate

ROUTER_SUBCMDS = ("ask", "code", "batch", "status", "serve", "diag")
ROUTER_BINARIES = ("aistudio", "aistudio.py", "grok", "grok.py", "mistral-chat", "mistral_chat.py",
                   "deepseek-chat", "deepseek_chat.py")


def check_router_command(cmd):
    """Return None if `cmd` is an allowed router command, else the reason it is not.

    A router model may run exactly one `aistudio <subcommand> ...` per call and nothing
    else: no chaining, pipes, redirects (except `<` from a file), substitutions or
    multi-line scripts, so it cannot write or run code of its own."""
    import shlex
    c = cmd.strip()
    if "\n" in c or "\r" in c:
        return "multi-line commands are not allowed"
    for bad in (";", "&&", "||", "|", ">", "`", "$(", "<(", "<<"):
        if bad in c:
            return f"shell operator {bad!r} is not allowed"
    if c.endswith("&"):
        c = c[:-1].rstrip()
        if "&" in c:
            return "only a single trailing & is allowed"
    elif "&" in c:
        return "'&' is not allowed"
    try:
        argv = shlex.split(c)
    except ValueError as e:
        return f"unparsable command: {e}"
    while argv and "=" in argv[0] and argv[0].split("=")[0].isidentifier():
        if not argv[0].startswith(("AISTUDIO_", "OFFLOAD_")):
            return "only AISTUDIO_*/OFFLOAD_* environment assignments are allowed"
        argv = argv[1:]
    if not argv or os.path.basename(argv[0]) not in ROUTER_BINARIES:
        return f"only these commands are allowed: {', '.join(ROUTER_BINARIES)}"
    if len(argv) < 2 or argv[1] not in ROUTER_SUBCMDS:
        return f"allowed subcommands: {', '.join(ROUTER_SUBCMDS)}"
    return None


MANAGER_TASK_WRITE = ("task*.md", "*.task.md")
_SEPS = set(";&|\n()")
_INTERPRETERS = {"bash", "sh", "zsh", "dash"}


def _tmp_ok(path):
    """Redirect targets a manager may write: /dev/null and scratch logs under /tmp."""
    if path == "/dev/null":
        return True
    return path.startswith("/tmp/") and ("/work/" in path or "/logs" in path or path.endswith((".out", ".log")))


def _manager_tokens(cmd):
    import shlex
    lx = shlex.shlex(cmd, posix=True, punctuation_chars=";<>|&()\n")
    lx.whitespace = " \t\r"
    lx.whitespace_split = True
    lx.commenters = ""
    return list(lx)


def _check_manager_segment(argv):
    """argv of one simple command (redirects already removed) -> reason or None."""
    while argv and ("=" in argv[0] and argv[0].split("=")[0].replace("_", "a").isalnum()
                    or os.path.basename(argv[0]) in ("sudo", "env", "time", "nohup", "command", "exec")):
        argv = argv[1:]
    if not argv:
        return None
    name, args = os.path.basename(argv[0]), argv[1:]
    import re
    if name == "eval":
        return "eval of a string is not allowed"
    if name in _INTERPRETERS and "-c" in args[:3]:
        i = args.index("-c")
        if i + 1 < len(args):
            return check_manager_command(args[i + 1]) or None
        return None
    if re.fullmatch(r"python[\d.]*|pypy3?", name):
        for a in args:
            if a == "-":
                return "python reading a script from stdin (`python3 -`) is not allowed"
            if a == "-m" or not a.startswith("-"):
                return None  # module or a script file
            if not a.startswith("--") and "c" in a[1:]:
                return "inline python (`python3 -c`) is not allowed"
        return "python without a script file (stdin/inline code) is not allowed"
    if name in ("node", "nodejs", "ruby", "php") and any(a in ("-e", "-p", "--eval", "-r", "-E") for a in args):
        return f"inline code (`{name} -e`) is not allowed"
    if name == "sed" and any(a == "--in-place" or a.startswith("--in-place=") or
                             (a.startswith("-") and not a.startswith("--") and "i" in a[1:]) for a in args):
        return "`sed -i` edits files in place"
    if name == "perl" and any(a.startswith("-") and not a.startswith("--") and ("i" in a[1:] or "e" in a[1:] or "E" in a[1:])
                              for a in args):
        return "`perl -i/-e` is not allowed"
    if name in ("awk", "gawk", "mawk") and any(re.search(r"print[^;}]*>|system\s*\(", a) for a in args):
        return "awk writing to files / running commands is not allowed"
    if name == "tee" and any(not a.startswith("-") and not _tmp_ok(a) for a in args):
        return "`tee` writes files"
    if name in ("patch", "ap", "ap.py"):
        return "patches must be applied inside `code` (the router applies them), not by the manager"
    if name == "git":
        sub = next((a for a in args if not a.startswith("-")), "")
        if sub == "apply":
            return "`git apply`: patch application must happen inside `aistudio code`"
    if name == "gh":
        for i, a in enumerate(args):
            if a in ("--body", "-b") or a.startswith("--body="):
                return "`gh ... --body` with an inline text (use --body-file)"
            if name == "gh" and args[:1] == ["api"] and a in ("-f", "--raw-field", "-F", "--field") \
                    and i + 1 < len(args) and args[i + 1].startswith("body="):
                return "`gh api -f body=...` with an inline text"
            if a.startswith(("--field=body=", "--raw-field=body=")):
                return "`gh api --field body=...` with an inline text"
    return None


def check_manager_command(cmd):
    """Reason a Bash command is forbidden for the manager, or None."""
    try:
        toks = _manager_tokens(cmd)
    except ValueError:
        toks = cmd.split()
    seg, i = [], 0
    while i <= len(toks):
        t = toks[i] if i < len(toks) else None
        if t is None or (t and set(t) <= _SEPS):
            why = _check_manager_segment(seg)
            if why:
                return why
            seg = []
        elif t.startswith("<<"):
            return "heredocs / here-strings are not allowed"
        elif t and set(t) <= set("<>&|") and ">" in t:
            target = toks[i + 1] if i + 1 < len(toks) else ""
            i += 1
            if t.endswith("&") and (target.isdigit() or target == "-"):
                pass  # fd duplication: 2>&1, >&2
            elif not _tmp_ok(target):
                return f"output redirection to {target or '?'} writes a file"
        else:
            seg.append(t)
        i += 1
    return None


def check_manager_tool(tool, tool_input):
    """Orchestrator gate for a small manager model: None if the tool call is allowed, else why not."""
    import fnmatch
    tool_input = tool_input or {}
    if tool in ("Edit", "MultiEdit", "NotebookEdit"):
        return f"{tool} is forbidden"
    if tool == "Write":
        path = tool_input.get("file_path") or tool_input.get("path") or ""
        base = os.path.basename(path)
        if any(fnmatch.fnmatch(base, g) for g in MANAGER_TASK_WRITE) or "tasks" in path.split(os.sep)[:-1]:
            return None
        return f"Write to {path or '?'} is forbidden (only task descriptions: task*.md, *.task.md, tasks/)"
    if tool == "Bash":
        return check_manager_command(tool_input.get("command", ""))
    return None


def cmd_guard(args):
    """PreToolUse hook (Claude Code JSON on stdin). Exit 2 blocks the tool call."""
    try:
        ev = json.load(sys.stdin)
    except Exception:
        print("router gate: bad hook input", file=sys.stderr)
        sys.exit(2)
    tool = ev.get("tool_name", "")
    if getattr(args, "manager", False):
        why = check_manager_tool(tool, ev.get("tool_input"))
        if why:
            print(f"MANAGER GATE: {why}. You orchestrate only: give substantive work (code, analysis, "
                  "triage, texts, markdown edits) to a router subagent (gemini-router / mistral-router) "
                  "via a task file.", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)
    if tool != "Bash":
        print(f"ROUTER GATE: tool {tool} is forbidden. You are a router: only run "
              "`aistudio ...` commands; Gemini does all thinking and writing.", file=sys.stderr)
        sys.exit(2)
    why = check_router_command((ev.get("tool_input") or {}).get("command", ""))
    if why:
        print(f"ROUTER GATE: {why}. You are a router, not a worker: run exactly one "
              "`aistudio ask|code|batch|status|diag` command per call and pass the task verbatim.",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def cmd_diag(args):
    """Print the summary.txt of the last N failure bundles."""
    base = os.path.join(HOME, "diag")
    dirs = sorted(d for d in (os.listdir(base) if os.path.isdir(base) else [])
                  if os.path.isfile(os.path.join(base, d, "summary.txt")))
    if not dirs:
        print(f"no diagnostics in {base}")
        return
    for d in dirs[-max(1, args.n):]:
        print(f"== {os.path.join(base, d)}")
        print(open(os.path.join(base, d, "summary.txt"), encoding="utf-8", errors="replace").read())


def cmd_status(args):
    ok = bool(logged_in(json.load(open(COOKIES)) if os.path.exists(COOKIES) else []))
    print(f"logged_in={ok} chrome_running={os.path.exists(PORT_FILE)} home={HOME} default_model={DEFAULT_MODEL}"
          + (f" tiers={TIERS}" if is_gemini() else ""))
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- vendor chain

VENDORS = {
    "anthropic": ("claude", "haiku", "sonnet", "opus", "fable", "anthropic"),
    "openai": ("gpt", "openai", "luna", "terra", "astra", "codex", "o3", "o4"),
    "google": ("gemini", "gemma", "google", "aistudio"),
    "xai": ("grok", "xai"),
    "mistral": ("mistral", "codestral", "magistral", "devstral", "ministral", "pixtral", "lechat"),
    "deepseek": ("deepseek",),
    "zhipu": ("glm", "zhipu", "z.ai", "zai"),
    "nvidia": ("nemotron", "nvidia"),
    "alibaba": ("qwen", "alibaba"),
    "moonshot": ("kimi", "moonshot"),
    "xiaomi": ("mimo", "xiaomi"),
    "minimax": ("minimax",),
}


def vendor_of(name):
    n = name.strip().lower()
    for v, keys in VENDORS.items():
        if any(k in n for k in keys):
            return v
    return n


def chain_guard():
    """Never let a vendor offload to itself, directly or anywhere up the chain.

    OFFLOAD_CHAIN (e.g. "anthropic>google") lists the vendors that already planned or did
    work for this task; OFFLOAD_CALLER names the model running this command. If the worker's
    vendor is among them we refuse. The extended chain is exported to child processes and
    printed, so sub-tasks derived from the answer carry it on."""
    chain = [vendor_of(v) for v in os.environ.get("OFFLOAD_CHAIN", "").replace(",", ">").split(">")
             if v.strip()]
    caller = os.environ.get("OFFLOAD_CALLER") or ("anthropic" if os.environ.get("CLAUDECODE") else "")
    if not caller and not chain:
        sys.exit(f"REFUSED: set OFFLOAD_CALLER=<your model id or vendor> (e.g. OFFLOAD_CALLER=glm-5.3) "
                 f"so that a {VENDOR} model never offloads to {VENDOR}.")
    if caller and (not chain or chain[-1] != vendor_of(caller)):
        chain.append(vendor_of(caller))
    if VENDOR in chain:
        sys.exit(f"REFUSED: offload chain {'>'.join(chain)} already contains vendor '{VENDOR}'. "
                 f"A vendor must not offload to itself (directly or via a nested chain); "
                 f"use a different worker skill.")
    full = ">".join(chain + [VENDOR])
    os.environ["OFFLOAD_CHAIN"] = full
    log(f"chain {full}: run any sub-task derived from this answer with OFFLOAD_CHAIN={full}")
    return full


def main():
    p = argparse.ArgumentParser(prog=PROG, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("login", help="sign in via a headless browser + web remote page")
    s.add_argument("--port", type=int, default=8766); s.add_argument("--timeout", type=int, default=1800)
    s.add_argument("--url", default=LOGIN_URL)
    s.add_argument("--done-host", default=DONE_HOST)
    s.set_defaults(fn=cmd_login)
    s = sub.add_parser("import-cookies"); s.add_argument("file"); s.set_defaults(fn=cmd_import_cookies)
    s = sub.add_parser("export-cookies"); s.set_defaults(fn=cmd_export_cookies)
    s = sub.add_parser("ask"); s.add_argument("prompt"); s.add_argument("-f", "--file", action="append")
    s.add_argument("-m", "--model", default=DEFAULT_MODEL); s.add_argument("-s", "--system")
    s.add_argument("-o", "--out"); s.add_argument("--max-context", type=int, help="max chars of packed context "
                   "(default $OFFLOAD_MAX_CONTEXT or 400000)")
    s.add_argument("--stall", type=float, help="seconds without output growth = STALLED (default 180)"); s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("serve", help="keep a warm Chrome running"); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("stop", help="stop the warm Chrome"); s.set_defaults(fn=cmd_stop)
    s = sub.add_parser("batch"); s.add_argument("file"); s.add_argument("-j", "--jobs", type=int, default=3)
    s.add_argument("-m", "--model", default=DEFAULT_MODEL); s.set_defaults(fn=cmd_batch)
    s = sub.add_parser("code", help="implement a task as an ap patch, apply it, run tests, iterate")
    s.add_argument("task", nargs="?", default="", help="task text or - for stdin"); s.add_argument("--task-file")
    s.add_argument("-C", "--dir", default="."); s.add_argument("-p", "--paths", nargs="*")
    s.add_argument("--stall", type=float, help="seconds without output growth = STALLED (default 180)")
    s.add_argument("--max-context", type=int, help="max chars of packed context (default "
                   "$OFFLOAD_MAX_CONTEXT or 400000); over the limit -> exit 3, nothing is truncated")
    s.add_argument("-t", "--test", help="shell command that must pass")
    s.add_argument("--ci", action="store_true",
                   help="test in GitHub Actions: push a branch + draft PR, wait for checks")
    s.add_argument("--ci-branch"); s.add_argument("--ci-base", default="main")
    s.add_argument("--ci-body", help="draft PR description")
    s.add_argument("--test-timeout", type=int, default=1800)
    s.add_argument("-r", "--rounds", type=int, default=3)
    s.add_argument("-m", "--model", default=DEFAULT_MODEL); s.set_defaults(fn=cmd_code)
    s = sub.add_parser("guard", help="PreToolUse hook that gates router models (--manager: orchestrator gate)")
    s.add_argument("--manager", action="store_true", help="gate for a manager that must offload all work")
    s.set_defaults(fn=cmd_guard)
    s = sub.add_parser("diag", help="print the last N failure diagnostics summaries")
    s.add_argument("n", nargs="?", type=int, default=1); s.set_defaults(fn=cmd_diag)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    a = p.parse_args()
    if a.cmd in ("ask", "code", "batch"):
        chain_guard()
    a.fn(a)


if __name__ == "__main__":
    main()
