#!/usr/bin/env python3
"""aistudio.py - offload LLM work to Google AI Studio's *chat UI* via headless Chrome.

The chat UI (aistudio.google.com) has much higher free quotas than the API, so
this tool never touches the API: it drives a real (headless) browser with your
Google session cookies.

  aistudio.py login                 # sign in once (visible Chrome), saves cookies
  aistudio.py login --remote        # same, on a headless VM (via ssh -L tunnel)
  aistudio.py ask "question"        # answer -> stdout
  aistudio.py ask -f a.py -f b.py "refactor this"   # files are inlined
  echo prompt | aistudio.py ask -   # prompt from stdin
  aistudio.py serve &               # keep a warm browser; `ask` uses it if running
  aistudio.py batch prompts.jsonl   # parallel, N tabs (see --jobs)

State lives in $AISTUDIO_HOME (default ~/.aistudio): cookies.json, profile/.
"""
import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

HOME = os.path.expanduser(os.environ.get("AISTUDIO_HOME", "~/.aistudio"))
COOKIES = os.path.join(HOME, "cookies.json")
PROFILE = os.path.join(HOME, "profile")
PORT = int(os.environ.get("AISTUDIO_PORT", "8765"))
DEFAULT_MODEL = os.environ.get("AISTUDIO_MODEL", "gemini-3.8-flash")
BASE = "https://aistudio.google.com"
GEN_RPC = "MakerSuiteService/GenerateContent"


def log(*a):
    if os.environ.get("AISTUDIO_QUIET") != "1":
        print("[aistudio]", *a, file=sys.stderr, flush=True)


LAUNCH_ARGS = ["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox",
               "--disable-blink-features=AutomationControlled", "--lang=en-US"]
UA = os.environ.get("AISTUDIO_UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")


def launch_kwargs(viewport=(1280, 900)):
    """Persistent-context options. A normal desktop UA (not 'HeadlessChrome') keeps
    Google sign-in and AI Studio happy; AISTUDIO_CHROME picks a browser binary."""
    kw = dict(headless=os.environ.get("AISTUDIO_HEADED") != "1",
              viewport={"width": viewport[0], "height": viewport[1]},
              user_agent=UA, locale="en-US", args=LAUNCH_ARGS)
    if os.environ.get("AISTUDIO_CHROME"):
        kw["executable_path"] = os.environ["AISTUDIO_CHROME"]
    return kw


# ---------------------------------------------------------------- login

def _logged_in(cookies):
    names = {c["name"] for c in cookies if c["domain"].endswith("google.com")}
    return "SID" in names or "__Secure-1PSID" in names


LOGIN_HTML = """<!doctype html><meta charset=utf-8><title>aistudio login</title>
<style>body{margin:0;background:#222;color:#eee;font:14px sans-serif}#bar{padding:6px}
img{display:block;cursor:crosshair;max-width:100%}input{width:40%}</style>
<div id=bar>Click the picture to focus, then type directly (or use the box + Enter).
 <input id=t placeholder="text to type"> <button onclick="k('Enter')">Enter</button>
 <button onclick="k('Tab')">Tab</button> <button onclick="k('Backspace')">&#9003;</button>
 <span id=st></span></div><img id=s tabindex=0>
<script>
const s=document.getElementById('s'),st=document.getElementById('st'),t=document.getElementById('t');
const post=(u,b)=>fetch(u,{method:'POST',body:JSON.stringify(b)});
function k(key){post('/key',{key})}
async function loop(){try{const r=await fetch('/shot?'+Date.now());const j=r.headers.get('X-Status');
 if(j)st.textContent=j;s.src=URL.createObjectURL(await r.blob());if(j==='DONE')return;}catch(e){}
 setTimeout(loop,600)}loop();
s.onclick=e=>{const r=s.getBoundingClientRect();s.focus();
 post('/click',{x:(e.clientX-r.left)*s.naturalWidth/r.width,y:(e.clientY-r.top)*s.naturalHeight/r.height})};
s.onkeydown=e=>{e.preventDefault();if(e.key.length===1)post('/type',{text:e.key});else post('/key',{key:e.key})};
t.onkeydown=e=>{if(e.key==='Enter'){post('/type',{text:t.value}).then(()=>k('Enter'));t.value=''}};
</script>"""


def cmd_login(args):
    """Sign in without any visible window: headless Chrome + a tiny web remote-control page.
    Open http://127.0.0.1:<port>/ in any browser (on a VM: `ssh -L <port>:127.0.0.1:<port> vm`)."""
    from playwright.sync_api import sync_playwright
    os.makedirs(HOME, exist_ok=True)
    shutil.rmtree(PROFILE, ignore_errors=True)
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(PROFILE, **launch_kwargs((1000, 760)))
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(args.url)
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
            if self.path.startswith("/shot"):
                p = ctx.pages[-1]
                ck = ctx.cookies()
                st = p.url[:60]
                if _logged_in(ck) and args.done_host in p.url:
                    _save_cookies(ck, keep_profile=True)
                    state["done"] = True
                    st = "DONE"
                self._send(p.screenshot(type="jpeg", quality=60), "image/jpeg", {"X-Status": st})
            else:
                self._send(LOGIN_HTML.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            p = ctx.pages[-1]
            if self.path == "/click":
                p.mouse.click(req["x"], req["y"])
            elif self.path == "/type":
                p.keyboard.type(req["text"])
            elif self.path == "/key":
                p.keyboard.press(req["key"])
            self._send(b"ok", "text/plain")

    srv = HTTPServer(("127.0.0.1", args.port), H)
    srv.timeout = 1
    print(f"Open http://127.0.0.1:{args.port}/ and sign in to Google there.\n"
          f"(On a remote VM first run on your laptop: ssh -L {args.port}:127.0.0.1:{args.port} <vm>)",
          flush=True)
    deadline = time.time() + args.timeout
    while not state["done"] and time.time() < deadline:
        srv.handle_request()
    for _ in range(3):  # let the page fetch the final DONE frame
        srv.handle_request()
    ctx.close()
    pw.stop()
    if not state["done"]:
        sys.exit("Timed out waiting for sign-in.")
    print(f"Logged in. Cookies saved to {COOKIES}; headless profile at {PROFILE}")


def _save_cookies(ck, keep_profile=False):
    os.makedirs(HOME, exist_ok=True)
    fd = os.open(COOKIES, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(ck, f)
    if not keep_profile:
        shutil.rmtree(PROFILE, ignore_errors=True)  # re-seed headless profile from cookies


def cmd_import_cookies(args):
    data = sys.stdin.read() if args.file == "-" else open(args.file).read()
    ck = json.loads(data)
    if isinstance(ck, dict) and "cookies" in ck:  # playwright storage_state
        ck = ck["cookies"]
    for c in ck:  # accept common browser-extension export formats too
        if "expirationDate" in c and "expires" not in c:
            c["expires"] = c.pop("expirationDate")
        c.setdefault("path", "/")
        ss = str(c.get("sameSite", "Lax")).capitalize()
        c["sameSite"] = {"No_restriction": "None", "Unspecified": "Lax"}.get(ss, ss)
        for k in list(c):
            if k not in ("name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"):
                del c[k]
    _save_cookies(ck)
    print(f"{len(ck)} cookies imported. Logged in: {_logged_in(ck)}")


def cmd_export_cookies(args):
    print(open(COOKIES).read())


# ---------------------------------------------------------------- browser

class Studio:
    """One headless browser; each ask() runs in its own tab, so asks run concurrently."""

    @classmethod
    async def start(cls, headless=True):
        from playwright.async_api import async_playwright
        if not os.path.exists(COOKIES):
            raise SystemExit(f"Not logged in: {COOKIES} missing. Run `aistudio.py login` first.")
        self = cls()
        self._pw = await async_playwright().start()
        fresh = not os.path.exists(PROFILE)
        kw = launch_kwargs()
        kw["headless"] = kw["headless"] and headless
        self.ctx = await self._pw.chromium.launch_persistent_context(PROFILE, **kw)
        if fresh:
            await self.ctx.add_cookies(json.load(open(COOKIES)))
        return self

    async def close(self):
        await self.ctx.close()
        await self._pw.stop()

    async def ask(self, prompt, model=DEFAULT_MODEL, system=None, timeout=600):
        page = await self.ctx.new_page()
        try:
            return await asyncio.wait_for(self._ask(page, prompt, model, system), timeout)
        finally:
            await page.close()

    async def _ask(self, page, prompt, model, system):
        resps = []
        page.on("response", lambda r: resps.append(r) if GEN_RPC in r.url else None)
        await page.goto(f"{BASE}/prompts/new_chat?model={model}", wait_until="domcontentloaded")
        if "accounts.google.com" in page.url:
            raise RuntimeError("Session expired: run `aistudio.py login` again.")
        box = page.locator("ms-prompt-input-wrapper textarea, textarea[aria-label*='prompt' i]").first
        await box.wait_for(timeout=60000)
        await self._dismiss_dialogs(page)
        if system:
            await self._set_system(page, system)
        await box.fill(prompt)
        run = page.locator("ms-run-button button, button[aria-label='Run']").first
        for _ in range(120):
            if await run.is_enabled():
                break
            await page.wait_for_timeout(250)
        await run.click()
        t0 = time.time()
        while not resps:
            if time.time() - t0 > 60:
                raise RuntimeError("Run did not start (quota? dialog?). " + await self._error_text(page))
            await page.wait_for_timeout(250)
        resp = resps[-1]
        raw = await resp.text()  # waits for the streamed body to finish
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}: {raw[:500]}")
        text = parse_generate(raw)
        if not text.strip():
            raise RuntimeError("Empty answer. " + await self._error_text(page))
        return text

    @staticmethod
    async def _dismiss_dialogs(page):
        for sel in ("button:has-text('Got it')", "button:has-text('Dismiss')",
                    "button[aria-label='Close']"):
            try:
                b = page.locator(sel).first
                if await b.is_visible():
                    await b.click(timeout=1000)
            except Exception:
                pass

    @staticmethod
    async def _set_system(page, system):
        await page.locator("button:has-text('System instructions'), "
                           "[aria-label*='System instructions' i]").first.click()
        ta = page.locator("textarea[aria-label*='System instructions' i], "
                          "ms-system-instructions textarea").first
        await ta.fill(system)
        await page.keyboard.press("Escape")

    @staticmethod
    async def _error_text(page):
        try:
            return (await page.locator(".error, ms-callout, [role=alert]").first.inner_text(timeout=1000))[:300]
        except Exception:
            return ""


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


# ---------------------------------------------------------------- daemon

def _daemon_alive():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
            return True
    except OSError:
        return False


def cmd_serve(args):
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    studio = asyncio.run_coroutine_threadsafe(Studio.start(not args.headed), loop).result()
    sem = asyncio.Semaphore(args.tabs)

    async def guarded(req):
        async with sem:
            return await studio.ask(req["prompt"], req.get("model") or DEFAULT_MODEL, req.get("system"))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                res = {"text": asyncio.run_coroutine_threadsafe(guarded(req), loop).result()}
            except Exception as e:
                res = {"error": str(e) or type(e).__name__}
            body = json.dumps(res).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    log(f"serving on 127.0.0.1:{PORT} with {args.tabs} parallel tabs")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


def build_prompt(text, files):
    parts = []
    for f in files or []:
        body = open(f, encoding="utf-8", errors="replace").read()
        parts.append(f"=== FILE: {f} ===\n{body}\n=== END FILE: {f} ===")
    parts.append(text)
    return "\n\n".join(parts)


def _ask_daemon(prompt, model, system):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/", method="POST",
        data=json.dumps({"prompt": prompt, "model": model, "system": system}).encode())
    res = json.load(urllib.request.urlopen(req, timeout=900))
    if "error" in res:
        raise RuntimeError(res["error"])
    return res["text"]


async def ask_many(jobs, jobs_n=3, retries=2):
    """jobs: list of (prompt, model, system). Returns list of text or Exception."""
    use_daemon = _daemon_alive()
    studio = None if use_daemon else await Studio.start()
    sem = asyncio.Semaphore(jobs_n)

    async def one(prompt, model, system):
        async with sem:
            for attempt in range(retries + 1):
                try:
                    if use_daemon:
                        return await asyncio.to_thread(_ask_daemon, prompt, model, system)
                    return await studio.ask(prompt, model, system)
                except Exception as e:
                    if attempt == retries or "login" in str(e):
                        return e
                    log(f"attempt {attempt + 1} failed: {e or type(e).__name__}; retrying")
                    await asyncio.sleep(5)
    try:
        return await asyncio.gather(*(one(*j) for j in jobs))
    finally:
        if studio:
            await studio.close()


def cmd_ask(args):
    text = sys.stdin.read() if args.prompt == "-" else args.prompt
    ans = asyncio.run(ask_many([(build_prompt(text, args.file), args.model, args.system)]))[0]
    if isinstance(ans, Exception):
        sys.exit(f"ERROR: {ans or type(ans).__name__}")
    if args.out:
        open(args.out, "w").write(ans)
        log(f"answer written to {args.out} ({len(ans)} chars)")
    else:
        sys.stdout.write(ans if ans.endswith("\n") else ans + "\n")


def cmd_batch(args):
    """jsonl lines: {"id":..., "prompt":..., "model"?:..., "files"?:[...]} -> results jsonl."""
    jobs = [json.loads(l) for l in open(args.file) if l.strip()]
    res = asyncio.run(ask_many(
        [(build_prompt(j["prompt"], j.get("files")), j.get("model", args.model), j.get("system"))
         for j in jobs], args.jobs))
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
        ans = asyncio.run(ask_many([(prompt, args.model, None)]))[0]
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



def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("login", help="sign in via a headless browser + web remote page")
    s.add_argument("--port", type=int, default=8766); s.add_argument("--timeout", type=int, default=1800)
    s.add_argument("--url", default=f"https://accounts.google.com/ServiceLogin?continue={BASE}/prompts/new_chat")
    s.add_argument("--done-host", default="aistudio.google.com")
    s.set_defaults(fn=cmd_login)
    s = sub.add_parser("import-cookies"); s.add_argument("file"); s.set_defaults(fn=cmd_import_cookies)
    s = sub.add_parser("export-cookies"); s.set_defaults(fn=cmd_export_cookies)
    s = sub.add_parser("ask"); s.add_argument("prompt"); s.add_argument("-f", "--file", action="append")
    s.add_argument("-m", "--model", default=DEFAULT_MODEL); s.add_argument("-s", "--system")
    s.add_argument("-o", "--out"); s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("serve"); s.add_argument("--tabs", type=int, default=3)
    s.add_argument("--headed", action="store_true"); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("batch"); s.add_argument("file"); s.add_argument("-j", "--jobs", type=int, default=3)
    s.add_argument("-m", "--model", default=DEFAULT_MODEL); s.set_defaults(fn=cmd_batch)
    s = sub.add_parser("code", help="implement a task as an ap patch, apply it, run tests, iterate")
    s.add_argument("task", help="task text or - for stdin"); s.add_argument("--task-file")
    s.add_argument("-C", "--dir", default="."); s.add_argument("-p", "--paths", nargs="*")
    s.add_argument("-t", "--test", help="shell command that must pass")
    s.add_argument("--test-timeout", type=int, default=900)
    s.add_argument("-r", "--rounds", type=int, default=4)
    s.add_argument("-m", "--model", default=DEFAULT_MODEL); s.set_defaults(fn=cmd_code)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
