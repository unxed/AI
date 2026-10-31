"""Minimal raw-CDP driver for a real (headless) Google Chrome. No Playwright.

Why: Google flags automation frameworks (Playwright/Puppeteer add --enable-automation,
navigator.webdriver, Runtime.enable side effects). We start Chrome as a normal process
and use only Target/Page.captureScreenshot/Input/Network/Storage and Runtime.evaluate
(without Runtime.enable).
"""
import base64
import itertools
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request

from websockets.sync.client import connect

UA = os.environ.get("AISTUDIO_UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
KEYS = {"Enter": ("Enter", 13), "Tab": ("Tab", 9), "Backspace": ("Backspace", 8),
        "Escape": ("Escape", 27), "ArrowDown": ("ArrowDown", 40), "ArrowUp": ("ArrowUp", 38)}


def find_chrome():
    for p in (os.environ.get("AISTUDIO_CHROME"), "google-chrome", "google-chrome-stable",
              "chromium", "chromium-browser", "chrome"):
        if p and shutil.which(p):
            return shutil.which(p)
    return None


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Conn:
    """One CDP websocket. Thread-confined: use one Conn per thread."""

    def __init__(self, ws_url):
        self.ws = connect(ws_url, max_size=200 * 2 ** 20, open_timeout=30)
        self.ids = itertools.count(1)
        self.events = []

    def call(self, method, timeout=60, **params):
        i = next(self.ids)
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        deadline = time.time() + timeout
        while True:
            msg = json.loads(self.ws.recv(timeout=max(0.1, deadline - time.time())))
            if msg.get("id") == i:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def pump(self, timeout):
        """Read events for up to `timeout` seconds."""
        try:
            msg = json.loads(self.ws.recv(timeout=timeout))
            if "method" in msg:
                self.events.append(msg)
        except TimeoutError:
            pass

    def eval(self, expr, timeout=60):
        r = self.call("Runtime.evaluate", timeout=timeout, expression=expr,
                      awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError("JS: " + json.dumps(r["exceptionDetails"])[:400])
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


class Chrome:
    """A headless real Chrome on a persistent profile. Reuses a running one if any."""

    def __init__(self, profile, port_file, size=(1280, 900), headless=True):
        self.profile, self.port_file, self.proc = profile, port_file, None
        port = None
        if os.path.exists(port_file):
            port = int(open(port_file).read().strip() or 0)
            if not _port_open(port):
                port = None
        if port is None:
            chrome = find_chrome()
            if not chrome:
                raise RuntimeError("Google Chrome not found (install it, or set AISTUDIO_CHROME)")
            port = _free_port()
            args = [chrome, f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
                    "--remote-allow-origins=*", f"--user-agent={UA}", "--lang=en-US",
                    f"--window-size={size[0]},{size[1]}", "--no-first-run",
                    "--no-default-browser-check", "--password-store=basic",
                    "--disable-dev-shm-usage", "--disable-gpu", "--mute-audio",
                    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows", "about:blank"]
            if headless:
                args.insert(1, "--headless=new")
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         start_new_session=True)
            for _ in range(150):
                if _port_open(port):
                    break
                time.sleep(0.2)
            with open(port_file, "w") as f:
                f.write(str(port))
        self.port = port
        self._lock = threading.Lock()

    def _json(self, path):
        return json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/{path}", timeout=10))

    def browser(self):
        return Conn(self._json("version")["webSocketDebuggerUrl"])

    def new_tab(self, url="about:blank"):
        b = self.browser()
        try:
            tid = b.call("Target.createTarget", url=url)["targetId"]
        finally:
            b.close()
        for t in self._json("list"):
            if t["id"] == tid:
                return Tab(self, tid, t["webSocketDebuggerUrl"])
        raise RuntimeError("new tab not found")

    def set_cookies(self, cookies):
        b = self.browser()
        try:
            ok = []
            for c in cookies:
                d = {k: c[k] for k in ("name", "value", "domain", "path", "secure", "httpOnly")
                     if k in c}
                if c.get("expires", -1) and c.get("expires", -1) > 0:
                    d["expires"] = c["expires"]
                if c.get("sameSite") in ("Strict", "Lax", "None"):
                    d["sameSite"] = c["sameSite"]
                ok.append(d)
            b.call("Storage.setCookies", cookies=ok)
        finally:
            b.close()

    def cookies(self):
        b = self.browser()
        try:
            return b.call("Storage.getCookies")["cookies"]
        finally:
            b.close()

    def quit(self):
        try:
            b = self.browser()
            b.call("Browser.close", timeout=5)
        except Exception:
            pass
        if self.proc:
            try:
                self.proc.wait(10)
            except Exception:
                self.proc.kill()
        try:
            os.remove(self.port_file)
        except OSError:
            pass


class Tab:
    def __init__(self, chrome, tid, ws_url):
        self.chrome, self.tid = chrome, tid
        self.c = Conn(ws_url)

    def goto(self, url):
        self.c.call("Page.navigate", url=url)

    def url(self):
        return self.c.eval("location.href")

    def wait_js(self, expr, timeout=60, interval=0.25):
        """Poll a JS expression until truthy; returns its value."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                v = self.c.eval(expr, timeout=20)
            except RuntimeError:
                v = None
            if v:
                return v
            self.c.pump(interval)
        raise TimeoutError(f"timeout waiting for: {expr[:80]}")

    def screenshot(self, quality=45):
        d = self.c.call("Page.captureScreenshot", format="jpeg", quality=quality)["data"]
        return base64.b64decode(d)

    def click(self, x, y):
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.c.call("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)

    def insert_text(self, text):
        self.c.call("Input.insertText", text=text)

    def key(self, key):
        code, vk = KEYS.get(key, (key, 0))
        for t in ("rawKeyDown", "keyUp"):
            extra = {"text": "\r"} if key == "Enter" and t == "rawKeyDown" else {}
            self.c.call("Input.dispatchKeyEvent", type=t, key=key, code=code,
                        windowsVirtualKeyCode=vk, nativeVirtualKeyCode=vk, **extra)

    def capture_response(self, url_part, trigger, timeout=900):
        """Enable Network, run trigger(), return (status, body) of the last finished
        request whose URL contains url_part."""
        self.c.call("Network.enable", maxResourceBufferSize=100 * 2 ** 20,
                    maxTotalBufferSize=200 * 2 ** 20)
        self.c.events.clear()
        trigger()
        reqs, status = {}, {}
        deadline = time.time() + timeout
        while time.time() < deadline:
            while self.c.events:
                e = self.c.events.pop(0)
                m, p = e["method"], e.get("params", {})
                if m == "Network.requestWillBeSent" and url_part in p["request"]["url"]:
                    reqs[p["requestId"]] = True
                elif m == "Network.responseReceived" and p["requestId"] in reqs:
                    status[p["requestId"]] = p["response"]["status"]
                elif m == "Network.loadingFinished" and p["requestId"] in reqs:
                    body = self.c.call("Network.getResponseBody", requestId=p["requestId"])
                    raw = body["body"]
                    if body.get("base64Encoded"):
                        raw = base64.b64decode(raw).decode("utf-8", "replace")
                    return status.get(p["requestId"], 0), raw
                elif m == "Network.loadingFailed" and p["requestId"] in reqs:
                    raise RuntimeError(f"request failed: {p.get('errorText')}")
            self.c.pump(1.0)
        raise TimeoutError(f"no finished response for {url_part}")

    def close(self):
        self.c.close()
        try:
            b = self.chrome.browser()
            b.call("Target.closeTarget", targetId=self.tid, timeout=10)
            b.close()
        except Exception:
            pass
