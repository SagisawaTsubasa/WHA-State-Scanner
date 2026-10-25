# -*- coding: utf-8 -*-
"""Routing-mode verification for the WHA panel (WHA-F-253 regression pin).

Standalone mounts are hash-driven (#/editor/<id> deep links); in-shell
mounts (inside a FUMIHA-HUB-PANEL shadow root) must never touch
location.hash — the shell owns it with its own #pn= route and normalizes
anything else away, which used to make the editor/logs views unreachable.

The dev HTTP server is started in-process (daemon thread): ZCode's shell
sandbox breaks loopback HTTP to child processes (Stockroom harness lesson).

Usage: python dev/test_routing.py   → exit 0 = all checks passed
"""

import http.server
import os
import sys

from playwright.sync_api import sync_playwright

DEV_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(DEV_DIR)
PORT = 8779

ROUTING_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>wha routing test</title></head>
<body>
  <div id="standalone-host"></div>
  <fumiha-hub-panel id="shell-host"></fumiha-hub-panel>
  <script type="module">
    const json = (data, status = 200) =>
      new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
    const hassStub = {
      language: "zh-Hans",
      states: {},
      async fetchWithAuth(url, opts = {}) {
        if (url.includes("/config")) return json({ ok: true, controllers: {} });
        return json({ ok: true });
      },
    };
    window.hassStub = hassStub;

    await import("/sensor_switch_controller/panel.js");

    // hass BEFORE appendChild (WHA-F-261): connectedCallback → _boot runs at
    // insertion; a late hass assignment would boot into the error card and
    // the editor render chain would never be exercised.
    const a = document.createElement("sensor-switch-controller-panel");
    a.hass = hassStub;
    document.getElementById("standalone-host").appendChild(a);

    // in-shell: root = a ShadowRoot hosted by <fumiha-hub-panel>
    const host = document.getElementById("shell-host");
    const sr = host.attachShadow({ mode: "open" });
    const b = document.createElement("sensor-switch-controller-panel");
    b.hass = hassStub;
    sr.appendChild(b);

    window.__panels = { standalone: a, shell: b };
  </script>
</body></html>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/sensor_switch_controller/"):
            rel = clean[len("/sensor_switch_controller/"):]
            return os.path.join(
                REPO_ROOT, "custom_components", "sensor_switch_controller", "static", *rel.split("/")
            )
        # the generated routing page itself
        if clean in ("/", "/routing.html"):
            return os.path.join(DEV_DIR, "_routing_page.html")
        return super().translate_path(clean)

    def log_message(self, fmt, *args):  # keep test output clean
        pass


def start_server():
    page_path = os.path.join(DEV_DIR, "_routing_page.html")
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(ROUTING_HTML)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading = __import__("threading")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, page_path


def main():
    server, page_path = start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{PORT}/")
            page.wait_for_timeout(1200)

            # 前提：两个实例都在场，模式判定各就各位
            modes = page.evaluate(
                "() => ({s: window.__panels.standalone._inShell(),"
                " h: window.__panels.shell._inShell()})"
            )
            assert modes == {"s": False, "h": True}, f"mode detection wrong: {modes}"
            print("[mode] standalone=False / shell=True detected correctly")

            # ① standalone：hash 驱动（深链接保持）
            page.evaluate("() => window.__panels.standalone._nav('#/editor/ctrl_1')")
            page.wait_for_timeout(100)
            got = page.evaluate(
                "() => ({hash: location.hash,"
                " view: window.__panels.standalone._view,"
                " cid: window.__panels.standalone._cid})"
            )
            assert got["hash"] == "#/editor/ctrl_1", f"standalone must write hash, got {got}"
            assert got["view"] == "editor" and got["cid"] == "ctrl_1", got
            print("[standalone] _nav writes #/editor/ctrl_1 and switches view")

            # ② standalone：hashchange 仍驱动视图
            page.evaluate("() => { location.hash = '#/logs'; }")
            page.wait_for_timeout(100)
            view = page.evaluate("() => window.__panels.standalone._view")
            assert view == "logs", f"standalone hashchange must drive view, got {view}"
            print("[standalone] hashchange drives view → logs")

            # ③ 壳内：_nav 绝不写 location.hash，视图内存态切换
            page.evaluate("() => { location.hash = '#pn=lux.main'; }")
            page.wait_for_timeout(100)
            page.evaluate("() => window.__panels.shell._nav('#/editor/ctrl_9')")
            page.wait_for_timeout(100)
            got = page.evaluate(
                "() => ({hash: location.hash,"
                " view: window.__panels.shell._view,"
                " cid: window.__panels.shell._cid})"
            )
            assert got["hash"] == "#pn=lux.main", (
                f"in-shell _nav must NOT touch location.hash (WHA-F-253), got {got}"
            )
            assert got["view"] == "editor" and got["cid"] == "ctrl_9", got
            print("[shell] _nav switches view in memory, hash untouched")

            # ③b 壳内导航进编辑器必须真实渲染（WHA-F-261）：错误卡不得在位、
            # 编辑器 DOM（app 顶栏）必须在壳的 shadowRoot 内出现
            shell_rendered = page.evaluate(
                "() => { const p = window.__panels.shell;"
                " return {err: !!p._error,"
                " app: !!p.shadowRoot.querySelector('.wha-app'),"
                " headerBtns: p.shadowRoot.querySelectorAll('.wha-btn').length}; }"
            )
            assert shell_rendered["err"] is False, (
                f"in-shell panel must boot clean (WHA-F-261), got {shell_rendered}"
            )
            assert shell_rendered["app"] and shell_rendered["headerBtns"] > 0, (
                f"editor view must render real DOM in-shell, got {shell_rendered}"
            )
            print("[shell] editor view renders real DOM (no error card)")

            # ④ 壳内：壳归一化 hash 不重置视图（曾把编辑器打回总览）
            page.evaluate(
                "() => { location.hash = '#pn=sensorswitch.main';"
                " window.dispatchEvent(new HashChangeEvent('hashchange')); }"
            )
            page.wait_for_timeout(100)
            view = page.evaluate("() => window.__panels.shell._view")
            assert view == "editor", (
                f"shell hash normalization must not reset the in-memory view, got {view}"
            )
            print("[shell] shell-side hash rewrite does not reset the view")

            assert not errors, f"page errors: {errors}"
            browser.close()
        print("\nALL ROUTING CHECKS PASSED")
    finally:
        server.shutdown()
        os.remove(page_path)


if __name__ == "__main__":
    sys.exit(main())
