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
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome, _port_open  # noqa: E402

HOME = os.path.expanduser(os.environ.get("AISTUDIO_HOME", "~/.aistudio"))
COOKIES = os.path.join(HOME, "cookies.json")
PROFILE = os.path.join(HOME, "profile")
PORT_FILE = os.path.join(HOME, "chrome.port")
DEFAULT_MODEL = os.environ.get("AISTUDIO_MODEL", "auto")
# `-m auto`: a quick triage call to a small Gemini picks the worker by difficulty.
TIERS = {"simple": "gemini-3.5-flash", "medium": "gemini-3.8-flash", "hard": "gemini-3.1-pro-preview"}
TRIAGE_MODEL = os.environ.get("AISTUDIO_TRIAGE_MODEL", "gemini-3.1-flash-lite")
# on quota/empty answers try the next model of the chain instead of hammering the same one
FALLBACK = {"gemini-3.1-pro-preview": ["gemini-2.5-pro", "gemini-3.8-flash"],
            "gemini-3.8-flash": ["gemini-3.5-flash", "gemini-2.5-flash"],
            "gemini-3.5-flash": ["gemini-2.5-flash", "gemini-3.8-flash"],
            "gemini-2.5-pro": ["gemini-3.8-flash"], "gemini-2.5-flash": ["gemini-3.5-flash"]}
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
        print("[aistudio]", *a, file=sys.stderr, flush=True)


def _logged_in(cookies):
    names = {c["name"] for c in cookies if c["domain"].endswith("google.com")}
    return "SID" in names or "__Secure-1PSID" in names


def logged_in(cookies):  # indirection so provider wrappers can replace it
    return _logged_in(cookies)


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
            ck = ch.cookies()  # done = session cookie present (URL may be a chrome:// interstitial)
            if logged_in(ck) and "/signin/" not in url and "/flow/" not in url:
                _save_cookies(ck)
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


def _js_str(s):
    return json.dumps(s)


def ask_tab(ch, prompt, model=DEFAULT_MODEL, system=None, timeout=900):
    tab = ch.new_tab(f"{BASE}/prompts/new_chat?model={model}")
    try:
        tab.wait_js(f"!!{JS_BOX} || location.host.startsWith('accounts.')", timeout=90)
        if "accounts.google.com" in (tab.url() or ""):
            raise RuntimeError("Session expired: run `aistudio login` again.")
        # close onboarding/announcement dialogs if any
        tab.c.eval("""for (const b of document.querySelectorAll('button')) {
            const t=(b.innerText||b.getAttribute('aria-label')||'').trim();
            if (/^(Got it|Dismiss|No thanks|Close)$/i.test(t) && b.offsetParent) b.click(); }""")
        if system:
            tab.c.eval("""(()=>{const b=[...document.querySelectorAll('button')].find(b=>
                /System instructions/i.test(b.innerText||b.getAttribute('aria-label')||''));
                if(b) b.click();})()""")
            tab.wait_js("!!document.querySelector(\"textarea[aria-label*='System instructions' i]\")", 15)
            tab.c.eval(_fill_js("document.querySelector(\"textarea[aria-label*='System instructions' i]\")",
                                system))
        tab.c.eval(_fill_js(JS_BOX, prompt), timeout=120)
        tab.wait_js(f"{JS_RUN} && !{JS_RUN}.disabled", timeout=60)
        status, raw = tab.capture_response(GEN_RPC, lambda: tab.c.eval(f"{JS_RUN}.click()"),
                                           timeout=timeout)
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {raw[:300]}")
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


def build_prompt(text, files):
    parts = []
    for f in files or []:
        body = open(f, encoding="utf-8", errors="replace").read()
        parts.append(f"=== FILE: {f} ===\n{body}\n=== END FILE: {f} ===")
    parts.append(text)
    return "\n\n".join(parts)


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

    def one(job):
        prompt, model, system = job
        model = model or DEFAULT_MODEL
        if model == "auto" and is_gemini():  # Gemini only; Grok has its own auto
            model = choose_model(ch, prompt)
        chain = [model] + FALLBACK.get(model, [])
        for attempt in range(retries + 1):
            m = chain[min(attempt, len(chain) - 1)]
            try:
                return globals()["ask_tab"](ch, prompt, m, system)
            except Exception as e:
                if attempt == retries or "login" in str(e):
                    return e
                log(f"{m}: attempt {attempt + 1} failed: {e or type(e).__name__}; retrying")
                time.sleep(5 * (attempt + 1))

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


def cmd_ask(args):
    text = sys.stdin.read() if args.prompt == "-" else args.prompt
    ans = ask_many([(build_prompt(text, args.file), args.model, args.system)])[0]
    if isinstance(ans, Exception):
        sys.exit(f"ERROR: {ans or type(ans).__name__}")
    if args.out:
        open(args.out, "w").write(ans)
        log(f"answer written to {args.out} ({len(ans)} chars)")
    else:
        sys.stdout.write(ans if ans.endswith("\n") else ans + "\n")


def cmd_batch(args):
    """jsonl lines: {"id":..., "prompt":..., "model"?:..., "files"?:[...]} -> results jsonl."""
    jobs = [json.loads(line) for line in open(args.file) if line.strip()]
    res = ask_many([(build_prompt(j["prompt"], j.get("files")), j.get("model", args.model),
                     j.get("system")) for j in jobs], args.jobs)
    for j, r in zip(jobs, res):
        out = {"id": j.get("id")}
        out.update({"error": str(r) or type(r).__name__} if isinstance(r, Exception) else {"text": r})
        print(json.dumps(out, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- code (ap patches)

HERE = os.path.dirname(os.path.abspath(__file__))
AP_PY = os.path.join(HERE, "vendor", "ap.py")
AP_MD = os.path.join(HERE, "vendor", "ap.md")
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".wasm", ".woff", ".woff2",
            ".ttf", ".pdf", ".zip", ".gz", ".xz", ".tar", ".so", ".o", ".a", ".exe", ".dll", ".pyc",
            ".jar", ".class", ".mp3", ".mp4", ".lock")


def combine_tree(root, paths=None, max_bytes=3_000_000):
    """Concatenate source files (read-only) as `=== BEGIN path ===` blocks.
    In a git repo only tracked files are used; `paths` limits to given files/dirs."""
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
    out, total = [], 0
    for f in filter(None, files):
        full = os.path.join(root, f)
        if f.lower().endswith(SKIP_EXT) or not os.path.isfile(full) or os.path.islink(full):
            continue
        try:
            body = open(full, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        total += len(body)
        if total > max_bytes:
            log(f"context limit reached, skipping {f} and the rest")
            break
        out.append(f"=== BEGIN {f} ===\n{body}{'' if body.endswith(chr(10)) else chr(10)}=== END {f} ===")
    return "\n\n".join(out)


CODE_RULES = """You are a senior engineer. Implement the TASK below in the given codebase.
Reply with exactly ONE patch in the 'ap' format (spec above), inside a single ```ap fenced block.
Rules: snippets must be copied verbatim from the current files and be unique; prefer small
REPLACE/INSERT_AFTER edits; create new files with CREATE_FILE (or REPLACE on a new FILE as the
spec allows); keep the project's code style; add or update tests when it makes sense.
After the code block you may add at most 5 lines of explanation."""


def extract_patch(ans):
    import re
    m = re.findall(r"```(?:ap|text|diff)?[ \t]*\n(.*?)```", ans, re.S)
    if m:
        return max(m, key=len)
    return ans


def cmd_code(args):
    root = os.path.abspath(args.dir)
    task = sys.stdin.read() if args.task == "-" else args.task
    if args.task_file:
        task = open(args.task_file).read() + "\n" + (task or "")
    spec = open(AP_MD).read()
    history = ""
    for rnd in range(1, args.rounds + 1):
        ctx = combine_tree(root, args.paths)
        prompt = (f"<ap_spec>\n{spec}\n</ap_spec>\n\n<codebase>\n{ctx}\n</codebase>\n\n"
                  f"{CODE_RULES}\n\nTASK:\n{task}\n{history}")
        log(f"round {rnd}: asking {args.model} ({len(prompt)} chars of context)")
        ans = ask_many([(prompt, args.model, None)])[0]
        if isinstance(ans, Exception):
            sys.exit(f"ERROR: {ans}")
        patch = extract_patch(ans)
        pfile = os.path.join(root, ".afix.ap")
        open(pfile, "w").write(patch)
        ap = subprocess.run([sys.executable, AP_PY, pfile, "--dir", root],
                            capture_output=True, text=True)
        if ap.returncode != 0:
            err = (ap.stdout + ap.stderr)[-3000:]
            log(f"round {rnd}: patch failed to apply:\n{err}")
            history = (f"\nYOUR PREVIOUS PATCH FAILED TO APPLY (files are unchanged):\n"
                       f"```ap\n{patch}\n```\nPatcher output:\n{err}\nSend a corrected full patch.")
            continue
        os.remove(pfile)
        log(f"round {rnd}: patch applied")
        if not args.test:
            print(ans)
            return
        t = subprocess.run(args.test, shell=True, cwd=root, capture_output=True, text=True,
                           timeout=args.test_timeout)
        if t.returncode == 0:
            log(f"round {rnd}: tests passed")
            print(ans)
            return
        out = (t.stdout + t.stderr)[-4000:]
        log(f"round {rnd}: tests failed:\n{out[-1500:]}")
        history = (f"\nA previous patch WAS APPLIED (the codebase above already contains it) but "
                   f"the test command `{args.test}` failed:\n{out}\nSend a patch that fixes it.")
    sys.exit(f"FAILED after {args.rounds} rounds")



# ---------------------------------------------------------------- router gate

ROUTER_SUBCMDS = ("ask", "code", "batch", "status", "serve")
ROUTER_BINARIES = ("aistudio", "aistudio.py", "grok", "grok.py")


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
        if not argv[0].startswith("AISTUDIO_"):
            return "only AISTUDIO_* environment assignments are allowed"
        argv = argv[1:]
    if not argv or os.path.basename(argv[0]) not in ROUTER_BINARIES:
        return f"only these commands are allowed: {', '.join(ROUTER_BINARIES)}"
    if len(argv) < 2 or argv[1] not in ROUTER_SUBCMDS:
        return f"allowed subcommands: {', '.join(ROUTER_SUBCMDS)}"
    return None


def cmd_guard(args):
    """PreToolUse hook (Claude Code JSON on stdin). Exit 2 blocks the tool call."""
    try:
        ev = json.load(sys.stdin)
    except Exception:
        print("router gate: bad hook input", file=sys.stderr)
        sys.exit(2)
    tool = ev.get("tool_name", "")
    if tool != "Bash":
        print(f"ROUTER GATE: tool {tool} is forbidden. You are a router: only run "
              "`aistudio ...` commands; Gemini does all thinking and writing.", file=sys.stderr)
        sys.exit(2)
    why = check_router_command((ev.get("tool_input") or {}).get("command", ""))
    if why:
        print(f"ROUTER GATE: {why}. You are a router, not a worker: run exactly one "
              "`aistudio ask|code|batch|status` command per call and pass the task verbatim.",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def cmd_status(args):
    ok = os.path.exists(COOKIES) and logged_in(json.load(open(COOKIES)))
    print(f"logged_in={ok} chrome_running={os.path.exists(PORT_FILE)} home={HOME} default_model={DEFAULT_MODEL}"
          + (f" tiers={TIERS}" if is_gemini() else ""))
    sys.exit(0 if ok else 1)


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
    s.add_argument("-o", "--out"); s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("serve", help="keep a warm Chrome running"); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("stop", help="stop the warm Chrome"); s.set_defaults(fn=cmd_stop)
    s = sub.add_parser("batch"); s.add_argument("file"); s.add_argument("-j", "--jobs", type=int, default=3)
    s.add_argument("-m", "--model", default=DEFAULT_MODEL); s.set_defaults(fn=cmd_batch)
    s = sub.add_parser("code", help="implement a task as an ap patch, apply it, run tests, iterate")
    s.add_argument("task", help="task text or - for stdin"); s.add_argument("--task-file")
    s.add_argument("-C", "--dir", default="."); s.add_argument("-p", "--paths", nargs="*")
    s.add_argument("-t", "--test", help="shell command that must pass")
    s.add_argument("--test-timeout", type=int, default=900)
    s.add_argument("-r", "--rounds", type=int, default=4)
    s.add_argument("-m", "--model", default=DEFAULT_MODEL); s.set_defaults(fn=cmd_code)
    s = sub.add_parser("guard", help="PreToolUse hook that gates router models")
    s.set_defaults(fn=cmd_guard)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
