#!/usr/bin/env python3
"""mistral-chat - offload LLM work to Mistral's web chat Le Chat (chat.mistral.ai) via a
headless real Chrome. Same command set as the aistudio-offload skill (login, ask, code,
batch, serve, status, guard...). Self-contained: offload_core.py and cdp.py are an
identical copy of the shared engine (raw CDP to a real Chrome, no Playwright).

  mistral-chat login               # sign in once (e.g. "Continue with Google"), web remote view
  mistral-chat ask "question"      # -m fast (default) | think (reasoning mode)
  mistral-chat code "task" -t "make test"
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import offload_core as eng  # noqa: E402

URL = "https://chat.mistral.ai/work/temporary-chat"   # incognito: nothing kept in history
INLINE_LIMIT = 40_000  # longer prompts go in as an attached .txt file
MARKER = os.path.join(eng.HOME, "mistral.ok")
MODES = {"fast": ("Швидко", "Быстро", "Fast"), "think": ("Думати", "Думать", "Think")}

JS_BOX = "document.querySelector('.ProseMirror')"
JS_SEND = "document.querySelector('button[type=submit]')"
JS_PLUS = ("[...document.querySelectorAll('form button[aria-label]')].find(b=>/settings menu|"
           "меню налаштувань|меню настро/i.test(b.getAttribute('aria-label')))"
           " || document.querySelector('form button')")
JS_MODEL_BTN = ("[...document.querySelectorAll('button[aria-label]')].find(b=>/модел|model/i"
                ".test(b.getAttribute('aria-label')))")

def _patch(doc, op):
    """Apply one JSON-patch-like op (replace/add/append/remove) to a dict/list tree."""
    path = [p.replace("~1", "/").replace("~0", "~") for p in op.get("path", "/").split("/")[1:]]
    kind, val = op.get("op"), op.get("value")
    if not path or path == [""]:
        return val if kind in ("replace", "add") else doc
    cur = doc
    for p in path[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur.setdefault(p, {})
    last = path[-1]
    if isinstance(cur, list):
        i = len(cur) if last == "-" else int(last)
        if kind == "add":
            cur.insert(i, val)
        elif kind == "remove":
            cur.pop(i)
        elif kind == "append":
            cur[i] = (cur[i] or "") + val
        else:
            cur[i] = val
    elif kind == "remove":
        cur.pop(last, None)
    elif kind == "append":
        cur[last] = (cur.get(last) or "") + val
    else:
        cur[last] = val
    return doc


def parse_chat_stream(raw):
    """(status, text) of the assistant message in a Le Chat /api/chat stream.

    Lines look like `15:{"json":{"type":"message","messageId":..,"patches":[..]}}`; the
    assistant message starts with a patch replacing "/" by {role: "assistant", ...}."""
    msgs, assistant = {}, None
    for line in raw.splitlines():
        head, _, body = line.partition(":")
        if not head.isdigit() or not body.strip().startswith("{"):
            continue
        try:
            ev = json.loads(body).get("json") or {}
        except ValueError:
            continue  # unterminated last line
        if ev.get("type") != "message":
            continue
        mid = ev.get("messageId")
        for op in ev.get("patches") or []:
            msgs[mid] = _patch(msgs.get(mid, {}), op)
        if (msgs.get(mid) or {}).get("role") == "assistant":
            assistant = mid
    m = msgs.get(assistant) or {}
    chunks = m.get("contentChunks") or []
    # reasoning ("thinking") parts are text chunks tagged _context.type == "reasoning"
    text = "".join(c.get("text", "") for c in chunks if isinstance(c, dict) and c.get("type") == "text"
                   and (c.get("_context") or {}).get("type") != "reasoning")
    return m.get("generationStatus"), text or (m.get("content") or "")


def _pick_mode(tab, mode):
    labels = MODES.get(mode)
    if not labels:
        return
    r = tab.c.eval(f"(()=>{{const b={JS_MODEL_BTN}; if(!b) return null; const r=b.getBoundingClientRect();"
                   " return [r.x+r.width/2, r.y+r.height/2, b.innerText.trim()];})()")
    if not r or r[2] in labels:
        return
    tab.click(r[0], r[1])  # Radix menus open on a real pointer event, not .click()
    time.sleep(0.8)
    ok = tab.c.eval(f"""(()=>{{const want={json.dumps(list(labels))};
        for (const e of document.querySelectorAll('[role=menuitem],[role=menuitemradio]'))
          if (want.some(w=>(e.innerText||'').trim().startsWith(w))) {{ e.click(); return true; }}
        return false;}})()""")
    if not ok:
        eng.log(f"mode {mode!r} not found in the model menu; using the default")
        tab.key("Escape")


def mistral_ask_tab(ch, prompt, model="fast", system=None, timeout=900):
    if system:
        prompt = f"SYSTEM INSTRUCTIONS:\n{system}\n\n{prompt}"
    tab = ch.new_tab(URL)
    tmpdir = None
    try:
        tab.wait_js(f"!!{JS_BOX} || /auth\\.|login|sign/.test(location.href)", timeout=90)
        if not tab.c.eval(f"!!{JS_BOX}"):
            raise RuntimeError("Session expired: run `mistral-chat login` again.")
        _pick_mode(tab, model)
        if len(prompt) > INLINE_LIMIT:
            tmpdir = tempfile.mkdtemp(prefix="mistral-")
            path = os.path.join(tmpdir, "task_and_context.txt")
            open(path, "w").write(prompt)
            if not tab.c.eval("!!document.querySelector('input[type=file]')"):
                r = tab.c.eval(f"(()=>{{const b={JS_PLUS}; const r=b.getBoundingClientRect();"
                               " return [r.x+r.width/2, r.y+r.height/2];})()")
                tab.click(*r)  # the file input only exists while the "+" menu is open
                tab.wait_js("!!document.querySelector('input[type=file]')", timeout=10)
            tab.set_files("input[type=file]", [path])
            tab.key("Escape")
            tab.wait_js("document.body.innerText.includes('task_and_context')", timeout=180)
            time.sleep(3)  # upload + parsing
            prompt = ("The attached file task_and_context.txt contains the complete task and all "
                      "context. Read all of it and follow the instructions in it exactly.")
        tab.c.eval(f"(()=>{{const e={JS_BOX}; e.focus(); "
                   f"document.execCommand('insertText', false, {json.dumps(prompt)});}})()", timeout=120)
        tab.wait_js(f"!!({JS_SEND}) && !({JS_SEND}).disabled", timeout=120)
        # The app keeps its own fetch reference (an in-page hook sees nothing), so the
        # /api/chat stream is read over CDP once it finishes.
        code, raw = tab.capture_response("/api/chat", lambda: tab.c.eval(f"({JS_SEND}).click()"),
                                         timeout)
        status, text = parse_chat_stream(raw)
        if code != 200 or status not in ("success", "completed"):
            raise RuntimeError(f"Le Chat answer status {status!r} (HTTP {code}, rate limit?): {raw[-300:]}")
        if not text.strip():
            raise RuntimeError("Empty answer (rate limit or moderation?)")
        return text
    finally:
        tab.close()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def mistral_login_done(ch, tab, url):
    if "chat.mistral.ai" in url:
        try:
            if tab.c.eval(f"!!{JS_BOX}"):
                open(MARKER, "w").close()
                return True
        except Exception:
            pass
    return False


def main():
    eng.PROG = "mistral-chat"
    eng.VENDOR = "mistral"
    eng.COOKIES = os.path.join(eng.HOME, "cookies-mistral.json")
    eng.DEFAULT_MODEL = os.environ.get("MISTRAL_MODE", "fast")
    eng.LOGIN_URL = "https://chat.mistral.ai/work"
    eng.DONE_HOST = "chat.mistral.ai"
    eng.logged_in = lambda cookies: os.path.exists(MARKER)
    eng.login_done = mistral_login_done
    eng.ask_tab = mistral_ask_tab
    eng.__doc__ = __doc__
    eng.main()


if __name__ == "__main__":
    main()
