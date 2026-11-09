# -*- coding: utf-8 -*-
"""Data-node port visibility verification (WHA-SNAPSHOT-121 R1-1 pin).

The "plain leaves hide their dead input ports" CSS rule used to swallow
the snapshot capture/clear and compare A/B ports whole (admission JS and
CSS disagreed — the ports were wireable in theory and invisible in the
DOM). This pin loads the REAL panel module with a REAL controller config
carrying every condition type, enters the editor, and asserts the live
port dots: snapshot/compare inputs must be visible, the legacy dead-port
faces (plain leaf input_1/2, group input_2) must stay hidden, and the
palette path must produce a visible-node too. DOM-truth only — no
re-derivation of the CSS selectors.

Follows dev/test_routing.py: in-process HTTP server (daemon thread),
hass stub with fetchWithAuth, Playwright chromium headless.

Usage: python dev/test_ports.py  → exit 0 = all checks passed
"""

import http.server
import os
import sys

from playwright.sync_api import sync_playwright

DEV_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(DEV_DIR)
PORT = 8781

_HEX = "a" * 32
_PORTS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>wha port test</title></head>
<body>
  <div id="standalone-host"></div>
  <script type="module">
    const json = (data, status = 200) =>
      new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
    const controller = {
      name: "port-test", enabled: true, logging_enabled: false,
      triggers: [{ id: "trg_%H%", type: "state", label: "", enabled: true,
                   entity_id: "switch.c", routes: { conditions: ["cond_gate"] } }],
      conditions: [
        { id: "cond_gate", type: "state", label: "g", enabled: true,
          entity_id: "switch.c", state: "on" },
        { id: "cond_snap", type: "snapshot", label: "s", enabled: true,
          entity_id: "sensor.a", capture: ["cond_gate"], clear: [] },
        { id: "cond_lit", type: "literal", label: "l", enabled: true,
          value_type: "number", value: 25 },
        { id: "cond_cmp", type: "compare", label: "c", enabled: true, op: "below",
          a: { kind: "entity", entity_id: "sensor.a" },
          b: { kind: "literal", cond: "cond_lit" } },
        { id: "cond_dur", type: "duration", label: "d", enabled: true,
          seconds: 5, start: "cond_gate", abort: null },
        { id: "cond_flag", type: "flag", label: "f", enabled: true,
          set_conditions: ["cond_gate"], reset_conditions: [], initial: false },
        { id: "cond_grp", type: "or", label: "grp", enabled: true,
          conditions: ["cond_gate"] },
      ],
      outputs: [{ name: "o", type: "switch", entity_id: "ssc_%H%",
                  on_conditions: ["cond_cmp"], off_conditions: [],
                  manual_override: false }],
    };
    const hassStub = {
      language: "zh-Hans",
      states: {},
      async fetchWithAuth(url, opts = {}) {
        if (url.includes("/config"))
          return json({ ok: true, controllers: { ctrl_test01: controller } });
        return json({ ok: true });
      },
    };
    window.hassStub = hassStub;

    await import("/sensor_switch_controller/panel.js");
    const a = document.createElement("sensor-switch-controller-panel");
    a.hass = hassStub;
    document.getElementById("standalone-host").appendChild(a);
    a._nav("#/editor/ctrl_test01");
    window.__panel = a;
  </script>
</body></html>
""".replace("%H%", _HEX)

# (selector, expect_visible) — DOM truth via offsetParent
PORT_CHECKS = [
    # R1-1 fix face: data-node inputs must be wireable dots
    (".cond-snapshot .input_1", True),
    (".cond-snapshot .input_2", True),
    (".cond-compare .input_1", True),
    (".cond-compare .input_2", True),
    # legacy live faces stay visible (regression guard)
    (".cond-duration .input_1", True),
    (".cond-flag .input_2", True),
    # legacy dead-port faces stay hidden (the rule still has teeth)
    (".cond-state .input_1", False),
    (".cond-or .input_2", False),
]


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/sensor_switch_controller/"):
            rel = clean[len("/sensor_switch_controller/"):]
            return os.path.join(
                REPO_ROOT, "custom_components", "sensor_switch_controller", "static", *rel.split("/")
            )
        if clean in ("/", "/ports.html"):
            return os.path.join(DEV_DIR, "_ports_page.html")
        return super().translate_path(clean)

    def log_message(self, fmt, *args):  # keep test output clean
        pass


def main():
    page_path = os.path.join(DEV_DIR, "_ports_page.html")
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(_PORTS_HTML)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading = __import__("threading")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{PORT}/")
            page.wait_for_timeout(1500)  # vendor drawflow + canvas import

            canvas = "window.__panel.shadowRoot"
            # editor + canvas must be live first
            nodes = page.evaluate(
                "() => %s.querySelectorAll('.drawflow .wha-node').length" % canvas
            )
            assert nodes >= 7, f"canvas did not import the config nodes: {nodes}"
            print(f"[canvas] editor imported {nodes} nodes from the config")

            for selector, expect in PORT_CHECKS:
                vis = page.evaluate(
                    "([sel]) => { const el = %s.querySelector('.drawflow ' + sel);"
                    " return el ? el.offsetParent !== null : null; }" % canvas,
                    [selector],
                )
                assert vis is not None, f"selector not found on canvas: {selector}"
                assert vis is expect, (
                    f"{selector}: expected visible={expect}, got {vis}"
                    " (admission JS and CSS disagree — WHA-SNAPSHOT-121 R1-1)"
                )
                print(f"[port] {selector} visible={vis} (expected {expect})")

            # literal nodes expose NO input ports at all (drawflow renders
            # none for inputs=0) — both selectors must be absent, not hidden
            lit_ports = page.evaluate(
                "() => %s.querySelectorAll("
                "'.drawflow .cond-literal .input_1, .drawflow .cond-literal .input_2'"
                ").length" % canvas
            )
            assert lit_ports == 0, (
                f"literal node must expose no input ports, found {lit_ports}"
            )
            print("[port] .cond-literal exposes no input ports (as designed)")

            # palette path: a freshly added snapshot node keeps visible ports
            added = page.evaluate(
                "() => { const c = %s; const before = c.querySelectorAll('.cond-snapshot').length;"
                " c.querySelector('[data-add-cond=\"snapshot\"]').click();"
                " return c.querySelectorAll('.cond-snapshot').length - before; }" % canvas
            )
            assert added == 1, f"palette click did not add a snapshot node: {added}"
            page.wait_for_timeout(200)
            vis = page.evaluate(
                "() => { const all = %s.querySelectorAll('.drawflow .cond-snapshot .input_1');"
                " const el = all[all.length - 1];"
                " return el ? el.offsetParent !== null : null; }" % canvas
            )
            assert vis is True, (
                f"palette-added snapshot node input_1 not visible: {vis}"
            )
            print("[palette] freshly added snapshot node has a visible input_1")

            assert not errors, f"page errors: {errors}"
            browser.close()
        print("\nALL PORT CHECKS PASSED")
    finally:
        server.shutdown()
        os.remove(page_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
