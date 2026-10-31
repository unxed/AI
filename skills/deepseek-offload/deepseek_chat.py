#!/usr/bin/env python3
"""deepseek-chat - offload LLM work to DeepSeek's web chat (chat.deepseek.com) via a
headless real Chrome. Same command set as the aistudio-offload skill (login, ask, code,
batch, serve, status, guard...). Self-contained: offload_core.py and cdp.py are an
identical copy of the shared engine (raw CDP to a real Chrome, no Playwright).

  deepseek-chat login              # sign in once (e.g. "Log in with Google"), web remote view
  deepseek-chat ask "question"     # -m chat (default) | think (DeepThink reasoning)
  deepseek-chat code "task" -t "make test"
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

URL = "https://chat.deepseek.com/"
INLINE_LIMIT = 50_000  # the textarea takes ~58k chars; longer prompts go in as a .txt file
MARKER = os.path.join(eng.HOME, "deepseek.ok")

JS_BOX = "document.querySelector('textarea')"
JS_SEND = ("[...document.querySelectorAll('div[role=button].ds-button--primary')]"
           ".filter(e=>e.querySelector('svg') && e.offsetParent).pop()")
JS_LOGGED_IN = "!!localStorage.getItem('userToken')"

JS_HISTORY = """(async () => {
  const id = (location.pathname.match(/\\/s\\/([0-9a-f-]+)/) || [])[1];
  if (!id) return {error: 'no chat id in ' + location.pathname};
  const tok = JSON.parse(localStorage.getItem('userToken') || '{}').value;
  const r = await fetch('/api/v0/chat/history_messages?chat_session_id=' + id + '&cache_version=0',
                        {headers: {Authorization: 'Bearer ' + tok}});
  return await r.json(); })()"""


def _last_assistant(h):
    """(status, answer) of the newest assistant message; answer = RESPONSE fragments only
    (THINK fragments are DeepThink reasoning)."""
    data = (h or {}).get("data") or {}
    msgs = ((data.get("biz_data") or {}).get("chat_messages")) or []
    for m in reversed(msgs):
        if m.get("role") == "ASSISTANT":
            frags = m.get("fragments") or []
            text = "".join(f.get("content", "") for f in frags if f.get("type") == "RESPONSE")
            return m.get("status"), text
    return None, ""


def _set_toggle(tab, label, want):
    tab.c.eval(f"""(()=>{{const e=[...document.querySelectorAll('.ds-toggle-button')].find(e=>
        (e.innerText||'').trim()==={json.dumps(label)});
      if (e && e.classList.contains('ds-toggle-button--selected') !== {str(want).lower()}) e.click();}})()""")


def deepseek_ask_tab(ch, prompt, model="chat", system=None, timeout=900):
    if system:
        prompt = f"SYSTEM INSTRUCTIONS:\n{system}\n\n{prompt}"
    tab = ch.new_tab(URL)
    tmpdir = None
    try:
        tab.wait_js(f"!!{JS_BOX} || /sign_in|login/.test(location.pathname)", timeout=90)
        if not tab.c.eval(JS_LOGGED_IN):
            raise RuntimeError("Session expired: run `deepseek-chat login` again.")
        _set_toggle(tab, "DeepThink", model in ("think", "reasoner", "deepthink"))
        _set_toggle(tab, "Search", False)
        if len(prompt) > INLINE_LIMIT:
            tmpdir = tempfile.mkdtemp(prefix="ds-")
            path = os.path.join(tmpdir, "task_and_context.txt")
            open(path, "w").write(prompt)
            tab.set_files("input[type=file]", [path])
            tab.wait_js("document.body.innerText.includes('task_and_context')", timeout=180)
            time.sleep(3)  # upload + parsing
            prompt = ("The attached file task_and_context.txt contains the complete task and all "
                      "context. Read all of it and follow the instructions in it exactly.")
        tab.c.eval(eng._fill_js(JS_BOX, prompt), timeout=120)
        tab.wait_js(f"!!({JS_SEND}) && ({JS_SEND}).getAttribute('aria-disabled')!=='true'", timeout=120)
        tab.c.eval(f"({JS_SEND}).click()")
        # the app keeps its own fetch reference, so poll the chat history instead of hooking
        tab.wait_js("/\\/s\\/[0-9a-f-]+/.test(location.pathname)", timeout=60)
        deadline = time.time() + timeout
        while True:
            status, text = _last_assistant(tab.c.eval(JS_HISTORY, timeout=60))
            if status == "FINISHED":
                break
            if status in ("FAILED", "CANCELED", "CANCELLED", "ERROR"):
                raise RuntimeError(f"DeepSeek message status {status} (rate limit?)")
            if time.time() > deadline:
                raise TimeoutError("DeepSeek answer did not finish")
            time.sleep(3)
        if not text.strip():
            raise RuntimeError("Empty answer (rate limit or content filter?)")
        return text
    finally:
        tab.close()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def deepseek_login_done(ch, tab, url):
    if "chat.deepseek.com" in url and "sign_in" not in url:
        try:
            if tab.c.eval(JS_LOGGED_IN):
                open(MARKER, "w").close()
                return True
        except Exception:
            pass
    return False


def main():
    eng.PROG = "deepseek-chat"
    eng.VENDOR = "deepseek"
    eng.COOKIES = os.path.join(eng.HOME, "cookies-deepseek.json")
    eng.DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODE", "chat")
    eng.LOGIN_URL = "https://chat.deepseek.com/sign_in"
    eng.DONE_HOST = "chat.deepseek.com"
    eng.logged_in = lambda cookies: os.path.exists(MARKER)
    eng.login_done = deepseek_login_done
    eng.ask_tab = deepseek_ask_tab
    eng.__doc__ = __doc__
    eng.main()


if __name__ == "__main__":
    main()
