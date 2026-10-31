#!/usr/bin/env python3
"""grok - offload LLM work to Grok inside X (x.com/i/grok) via a headless real Chrome.

Same command set as the aistudio-offload skill (login, ask, code, batch, serve, status,
guard...), but the worker is Grok on X. Self-contained: offload_core.py and cdp.py are an
identical copy of the shared engine (raw CDP to a real Chrome, no Playwright).

  grok login                 # sign in to X once (web remote view, works over ssh -L)
  grok ask "question"        # -m fast|auto|expert
  grok code "task" -t "make test"
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import offload_core as eng  # noqa: E402

GROK_URL = "https://x.com/i/grok"
INLINE_LIMIT = 50_000   # longer prompts go in as an attached .txt (the box caps near 58k)
MODES = {"fast": ("Быстрый", "Fast"), "auto": ("Авто", "Auto"), "expert": ("Эксперт", "Expert")}

JS_BOX = "document.querySelector('[data-testid=\"primaryColumn\"] [contenteditable=true], [contenteditable=true]')"
JS_SEND = ("[...document.querySelectorAll('button[aria-label]')].find(b=>"
           "/^(Отправить|Send|Grok something)$/i.test(b.getAttribute('aria-label')))")


def x_logged_in(cookies):
    return any(c["name"] == "auth_token" and c["domain"].endswith("x.com") for c in cookies)


def _pick_mode(tab, mode):
    labels = MODES.get(mode)
    if not labels:
        return
    tab.c.eval("document.querySelector('button[aria-label^=\"Выберите модель\"], "
               "button[aria-label^=\"Choose model\"], button[aria-label^=\"Select model\"]').click()")
    time.sleep(0.8)
    ok = tab.c.eval(f"""(()=>{{const want={json.dumps(list(labels))};
        for (const e of document.querySelectorAll('[role=menuitemradio],[role=menuitem]'))
          if (want.some(w=>(e.innerText||'').trim().startsWith(w))) {{ e.click(); return true; }}
        return false;}})()""")
    if not ok:
        eng.log(f"mode {mode!r} not found in the model menu; using the default")
        tab.key("Escape")


def grok_ask_tab(ch, prompt, model="fast", system=None, timeout=900):
    if system:
        prompt = f"SYSTEM INSTRUCTIONS:\n{system}\n\n{prompt}"
    tab = ch.new_tab(GROK_URL)
    tmpdir = None
    try:
        tab.wait_js(f"!!{JS_BOX} || /login|flow/.test(location.pathname)", timeout=90)
        if "/login" in (tab.url() or "") or "/flow" in (tab.url() or ""):
            raise RuntimeError("Session expired: run `grok login` again.")
        _pick_mode(tab, model)
        if len(prompt) > INLINE_LIMIT:
            tmpdir = tempfile.mkdtemp(prefix="grok-")
            path = os.path.join(tmpdir, "task_and_context.txt")
            open(path, "w").write(prompt)
            tab.set_files("input[type=file]", [path])
            tab.wait_js("document.body.innerText.includes('task_and_context')", timeout=120)
            prompt = ("The attached file task_and_context.txt contains the complete task and all "
                      "context. Read all of it and follow the instructions in it exactly.")
        tab.c.eval(f"(()=>{{const e={JS_BOX}; e.focus(); "
                   f"document.execCommand('insertText', false, {json.dumps(prompt)});}})()", timeout=120)
        tab.wait_js(f"!!({JS_SEND}) && !({JS_SEND}).disabled", timeout=60)

        parts, state = {}, {"rid": None}

        def on_frame(payload):
            try:
                msg = json.loads(payload)
            except ValueError:
                return None
            ev = msg.get("event") or {}
            t = ev.get("type")
            if t == "response.created":
                state["rid"] = (ev.get("response") or {}).get("id")
            elif t == "response.chunk":
                txt = (ev.get("chunk") or {}).get("text") or {}
                if txt.get("channel") == "CHANNEL_ASSISTANT_RESPONSE":
                    parts.setdefault(ev.get("response_id"), []).append(txt.get("text", ""))
            elif t == "response.done":
                resp = ev.get("response") or {}
                rid = resp.get("id") or state["rid"]
                if resp.get("status") not in (None, "completed"):
                    raise RuntimeError(f"Grok response status: {resp.get('status')}")
                return "".join(parts.get(rid, []))
            elif t in ("error", "response.failed"):
                raise RuntimeError(f"Grok error: {json.dumps(ev)[:300]}")
            return None

        text = tab.collect_ws(lambda: tab.c.eval(f"({JS_SEND}).click()"), on_frame, timeout)
        if not text.strip():
            raise RuntimeError("Empty answer (rate limit?)")
        return text
    finally:
        tab.close()
        if tmpdir:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    eng.PROG = "grok"
    eng.VENDOR = "xai"
    eng.COOKIES = os.path.join(eng.HOME, "cookies-xai.json")
    eng.DEFAULT_MODEL = os.environ.get("GROK_MODE", "fast")
    eng.LOGIN_URL = "https://x.com/i/flow/login?redirect_after_login=%2Fi%2Fgrok"
    eng.DONE_HOST = "x.com/i/grok"
    eng.logged_in = x_logged_in
    eng.ask_tab = grok_ask_tab
    eng.__doc__ = __doc__
    eng.main()


if __name__ == "__main__":
    main()
