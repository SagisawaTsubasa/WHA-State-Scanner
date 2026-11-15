# -*- coding: utf-8 -*-
"""文羽服务 node body + trip leaves DOM verification (WHA-FUMIHA-NODE-125).

The R6 lesson (WHA-F-106): an admission criterion can be right on one end
and still ship a dead feature when the CSS hides what the JS allows — the
two ends must be checked in the same direction on the live DOM. This pin
loads the REAL panel module with a controller carrying the three trip
leaves and two 文羽服务 outputs, and asserts on DOM truth:

  1. trip leaves ARE signal origins on the canvas — input_3 visible, the
     dead gate ports input_1/2 hidden. Trip leaves are PLAIN leaves: the
     default :not() hide rule already covers them and they must NEVER be
     added to the :not() exemption chain (that chain lists leaves whose
     input_1/2 are LIVE ports — flag/snapshot/compare/stateful; R1#7).
  2. the trigger's signal wire to a trip leaf is actually drawn;
  3. the service node body hosts the two-level pickers: level 1 = built-in
     list ∩ integrations present in the hass stub's services map, level 2
     = the chosen domain's registered services, and picking a domain
     repopulates level 2;
  4. the explicit unavailable face (决策 4): a saved output whose domain is
     NOT installed keeps its value selectable and shows the .bad status
     line instead of hiding the problem.

Follows dev/test_ports.py: in-process HTTP server, hass stub with
fetchWithAuth + services map, Playwright chromium headless.

Usage: python dev/test_fumiha.py  → exit 0 = all checks passed
"""

import http.server
import os
import sys

from playwright.sync_api import sync_playwright

DEV_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(DEV_DIR)
PORT = 8793

_HEX = "c" * 32
_PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>wha fumiha test</title></head>
<body>
  <div id="standalone-host"></div>
  <script type="module">
    const json = (data, status = 200) =>
      new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
    const controller = {
      name: "fumiha-test", enabled: true, logging_enabled: false,
      triggers: [{ id: "trg_%H%", type: "state", label: "", enabled: true,
                   entity_id: "binary_sensor.trip",
                   routes: { conditions: ["cond_trp"] } }],
      conditions: [
        { id: "cond_trp", type: "trip_on", label: "on", enabled: true,
          entity_id: "binary_sensor.trip" },
        { id: "cond_td", type: "trip_day", label: "day", enabled: true,
          entity_id: "binary_sensor.trip", day: 2 },
        { id: "cond_tdu", type: "trip_duration", label: "dur", enabled: true,
          entity_id: "binary_sensor.trip", hours: 24 },
      ],
      outputs: [
        { name: "svc-ok", type: "fumiha_service", entity_id: "ssc_%H%",
          domain: "trip_count", service: "depart",
          on_conditions: ["cond_trp"], off_conditions: [] },
        { name: "svc-ghost", type: "fumiha_service", entity_id: "ssc_g%H%",
          domain: "fumiha_lighting", service: "scene_on",
          on_conditions: ["cond_td"], off_conditions: [] },
        { name: "svc-args", type: "fumiha_service", entity_id: "ssc_a%H%",
          domain: "trip_count", service: "force_evaluate",
          on_conditions: ["cond_tdu"], off_conditions: [] },
      ],
    };
    // services map face: ONLY two built-in domains installed — the level-1
    // dropdown must show exactly those two ("没装自然就没有"); trip_count
    // registers four services, one of which (force_evaluate) carries a
    // required field (descriptor form = services.yaml passed through, R1#2)
    // → the level-2 dropdown must filter it out; a SAVED output pointing at
    // it shows the needs-arguments face and keeps it selectable;
    // fumiha_lighting (a SAVED output's domain) is deliberately absent →
    // the unavailable face, and its saved service must stay visible too
    // (R1#10).
    const hassStub = {
      language: "zh-Hans",
      states: {},
      services: {
        trip_count: {
          depart: {}, back: {}, mark_day: {},
          force_evaluate: { fields: { entity_id: { required: true } } },
        },
        auto_night_light: { turn_on: {} },
      },
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


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/sensor_switch_controller/"):
            rel = clean[len("/sensor_switch_controller/"):]
            return os.path.join(
                REPO_ROOT, "custom_components", "sensor_switch_controller", "static", *rel.split("/")
            )
        if clean in ("/", "/fumiha.html"):
            return os.path.join(DEV_DIR, "_fumiha_page.html")
        return super().translate_path(clean)

    def log_message(self, fmt, *args):  # keep test output clean
        pass


def main():
    page_path = os.path.join(DEV_DIR, "_fumiha_page.html")
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(_PAGE_HTML)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading = __import__("threading")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    failures = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{PORT}/")
            page.wait_for_timeout(1500)  # vendor drawflow + canvas import

            canvas = "window.__panel.shadowRoot"
            nodes = page.evaluate(
                "() => %s.querySelectorAll('.drawflow .wha-node').length" % canvas
            )
            assert nodes >= 5, f"canvas did not import the config nodes: {nodes}"
            print(f"[canvas] editor imported {nodes} nodes from the config")

            # --- R6 double-ended check 1: trip leaves are signal origins on
            # the live DOM — input_3 visible, dead gate ports hidden.
            for tp in ("trip_on", "trip_day", "trip_duration"):
                vis3 = page.evaluate(
                    "([tp]) => { const el = %s.querySelector('.drawflow .cond-' + tp + ' .input_3');"
                    " return el ? el.offsetParent !== null : null; }" % canvas,
                    [tp],
                )
                assert vis3 is True, f".cond-{tp} .input_3 must be visible (signal origin), got {vis3}"
                for port in ("input_1", "input_2"):
                    vis = page.evaluate(
                        "([tp, port]) => { const el = %s.querySelector('.drawflow .cond-' + tp + ' .' + port);"
                        " return el ? el.offsetParent !== null : null; }" % canvas,
                        [tp, port],
                    )
                    assert vis is False, (
                        f".cond-{tp} .{port} must be hidden (plain leaf), got {vis}"
                        " (admission JS and CSS disagree — R6)"
                    )
                print(f"[port] .cond-{tp}: input_3 visible, input_1/2 hidden (signal origin)")

            # --- the trigger's signal wire to the trip leaf is drawn
            wires = page.evaluate(
                "() => %s.querySelectorAll('.drawflow .connection.signal').length" % canvas
            )
            assert wires >= 1, f"no amber signal wire drawn to the trip leaf: {wires}"
            print(f"[wire] {wires} signal wire(s) drawn (trigger → trip leaf)")

            # --- service node body: two-level pickers mounted
            picks = page.evaluate(
                "() => %s.querySelectorAll('.drawflow .wha-svc-pick').length" % canvas
            )
            assert picks == 3, f"expected 3 service picker bodies, got {picks}"
            # level 1 = built-in ∩ installed, built-in order: the stub has
            # trip_count + auto_night_light → exactly those two (+ the "—")
            dom_opts = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[0];"
                " return Array.from(out.querySelectorAll('.wha-svc-domain option'))"
                ".map((o) => o.value); }" % canvas
            )
            assert dom_opts == ["", "trip_count", "auto_night_light"], dom_opts
            print(f"[level1] domain options = {dom_opts} (built-in ∩ installed)")
            # level 2 = the chosen domain's registered services MINUS
            # required-field services (R1#2 filter face)
            svc_opts = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[0];"
                " return Array.from(out.querySelectorAll('.wha-svc-service option'))"
                ".map((o) => o.value); }" % canvas
            )
            assert svc_opts == ["", "back", "depart", "mark_day"], svc_opts
            assert "force_evaluate" not in svc_opts, (
                "a required-field service must be filtered from level 2 (R1#2)"
            )
            print(f"[level2] service options = {svc_opts} (required-field service filtered)")
            # the ghost output (saved domain NOT installed) keeps its value
            # selectable — the dropdown never silently swallows it (决策 4)
            ghost_opts = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[1];"
                " return Array.from(out.querySelectorAll('.wha-svc-domain option'))"
                ".map((o) => o.value); }" % canvas
            )
            assert ghost_opts == ["", "fumiha_lighting", "trip_count", "auto_night_light"], ghost_opts
            print(f"[level1] ghost output keeps its saved domain selectable: {ghost_opts}")
            # R1#10: the ghost domain ALSO keeps its saved service visible
            ghost_svc = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[1];"
                " return Array.from(out.querySelectorAll('.wha-svc-service option'))"
                ".map((o) => o.value); }" % canvas
            )
            assert "scene_on" in ghost_svc, (
                f"the saved service must stay selectable on a ghost domain (R1#10): {ghost_svc}"
            )
            print(f"[level2] ghost output keeps its saved service selectable: {ghost_svc}")
            # R1#2: a SAVED output pointing at a required-field service shows
            # the needs-arguments face and keeps the service selectable
            args_status = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[2];"
                " const st = out.querySelector('.wha-svc-status');"
                " return { cls: st.className, text: st.textContent }; }" % canvas
            )
            assert args_status["cls"].find("bad") >= 0, args_status
            assert "必填参数" in args_status["text"], args_status
            args_svc = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[2];"
                " return Array.from(out.querySelectorAll('.wha-svc-service option'))"
                ".map((o) => o.value); }" % canvas
            )
            assert "force_evaluate" in args_svc, (
                f"the saved required-args service must stay selectable (R1#2): {args_svc}"
            )
            print(f"[status] needs-arguments face live + service kept: {args_status['text'][:16]}…")
            # status face: the ok output shows ✓, the ghost one shows the
            # explicit unavailable face (.bad) — 决策 4
            statuses = page.evaluate(
                "() => Array.from(%s.querySelectorAll('.drawflow .wha-svc-status'))"
                ".map((el) => ({ cls: el.className, text: el.textContent.slice(0, 12) }))" % canvas
            )
            assert statuses[0]["cls"].find("ok") >= 0, statuses
            assert any(s["cls"].find("bad") >= 0 for s in statuses), statuses
            print(f"[status] ok face + unavailable face both live: {statuses}")

            # --- interaction: picking a domain repopulates level 2; the
            # stale service stays selectable (re-pick face) with the bad
            # status until the user picks one of the new domain's services
            page.evaluate(
                "() => { const sel = %s.querySelector('.drawflow .wha-svc-domain');"
                " sel.value = 'auto_night_light';"
                " sel.dispatchEvent(new Event('change', { bubbles: true })); }" % canvas
            )
            page.wait_for_timeout(200)
            svc_opts2 = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[0];"
                " return Array.from(out.querySelectorAll('.wha-svc-service option'))"
                ".map((o) => o.value); }" % canvas
            )
            assert svc_opts2 == ["", "depart", "turn_on"], svc_opts2
            status2 = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[0];"
                " return out.querySelector('.wha-svc-status').className; }" % canvas
            )
            assert status2.find("bad") >= 0, status2
            page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[0];"
                " const sel = out.querySelector('.wha-svc-service');"
                " sel.value = 'turn_on';"
                " sel.dispatchEvent(new Event('change', { bubbles: true })); }" % canvas
            )
            page.wait_for_timeout(200)
            status3 = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[0];"
                " return out.querySelector('.wha-svc-status').className; }" % canvas
            )
            assert status3.find("ok") >= 0, status3
            print(f"[interact] domain switch repopulated level 2 {svc_opts2}; re-pick restores the ok face")

            # --- R1#9: the vendor drag handling must not swallow real mouse
            # events on the pickers — panel.js sets df.draggable_inputs=false
            # (the vendor default true turns a select mousedown into a node
            # DRAG, making the dropdowns unusable). Pin the flag AND the
            # user-visible consequence: a real click on the select leaves
            # the node exactly where it was.
            flag = page.evaluate("() => window.__panel._editor.df.draggable_inputs")
            assert flag is False, (
                f"df.draggable_inputs must stay false — the vendor default true "
                f"makes the node-body pickers undraggable/unusable (R1#9): {flag}"
            )
            node_sel = page.evaluate(
                "() => { const out = %s.querySelectorAll('.drawflow .wha-out')[0];"
                " return '#node-' + out.id.slice(5); }" % canvas
            )
            tf_before = page.evaluate(
                "([sel]) => %s.querySelector(sel).style.transform" % canvas, [node_sel]
            )
            page.click(f"{node_sel} .wha-svc-domain")
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
            tf_after = page.evaluate(
                "([sel]) => %s.querySelector(sel).style.transform" % canvas, [node_sel]
            )
            assert tf_before == tf_after, (
                f"a real mousedown on the picker started a node DRAG "
                f"(draggable_inputs regression): {tf_before!r} -> {tf_after!r}"
            )
            print(f"[mouse] real click on the picker keeps the node planted ({node_sel})")

            # --- palette path: a freshly added service node carries the
            # picker body and starts on the hint face
            added = page.evaluate(
                "() => { const c = %s; const before = c.querySelectorAll('.wha-svc-pick').length;"
                " c.querySelector('[data-add-out=\"fumiha_service\"]').click();"
                " return c.querySelectorAll('.wha-svc-pick').length - before; }" % canvas
            )
            assert added == 1, f"palette click did not add a service node: {added}"
            page.wait_for_timeout(200)
            hint = page.evaluate(
                "() => { const all = %s.querySelectorAll('.drawflow .wha-svc-status');"
                " const el = all[all.length - 1];"
                " return el ? el.className : null; }" % canvas
            )
            assert hint is not None and hint.find("muted") >= 0, hint
            print("[palette] freshly added service node mounts the pickers (hint face)")

            # --- trip palette path: freshly added trip nodes are plain
            # leaves (input_3 visible, gate ports hidden)
            for tp in ("trip_day", "trip_duration"):
                added = page.evaluate(
                    "([tp]) => { const c = %s; const before = c.querySelectorAll('.cond-' + tp).length;"
                    " c.querySelector('[data-add-cond=\"' + tp + '\"]').click();"
                    " return c.querySelectorAll('.cond-' + tp).length - before; }" % canvas,
                    [tp],
                )
                assert added == 1, f"palette click did not add a {tp} node: {added}"
                page.wait_for_timeout(200)
                vis3 = page.evaluate(
                    "([tp]) => { const all = %s.querySelectorAll('.drawflow .cond-' + tp + ' .input_3');"
                    " const el = all[all.length - 1];"
                    " return el ? el.offsetParent !== null : null; }" % canvas,
                    [tp],
                )
                assert vis3 is True, f"palette-added {tp} input_3 not visible: {vis3}"
                print(f"[palette] freshly added {tp} node has a visible input_3")

            if errors:
                failures = len(errors)
                print("[FAIL] page errors:", errors)
    finally:
        server.shutdown()
        try:
            os.remove(page_path)
        except OSError:
            pass
    if failures:
        sys.exit(1)
    print("FUMIHA DOM OK")


if __name__ == "__main__":
    main()
