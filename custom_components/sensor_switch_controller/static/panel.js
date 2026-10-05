/**
 * Whole-House State Scanner — sidebar panel (custom element).
 *
 * Loaded by HA as a panel_custom module (see web.py): the frontend creates
 * `document.createElement("sensor-switch-controller-panel")` and feeds it
 * hass / narrow / route properties. Zero build step, zero CDN.
 *
 * Views: overview | editor (Drawflow canvas) | decision logs.
 * All data flows through the integration REST API with fetchWithAuth.
 */

const TAG = "sensor-switch-controller-panel";
const API = "/api/sensor_switch_controller";
const STYLE_URL = "/sensor_switch_controller/style.css";
const DF_JS_URL = "/sensor_switch_controller/vendor/drawflow.min.js";
const DF_CSS_URL = "/sensor_switch_controller/vendor/drawflow.min.css";

/* ------------------------------------------------------------------ */
/* i18n                                                                */
/* ------------------------------------------------------------------ */

const LANG = {
  "zh-Hans": {
    appTitle: "全屋状态扫描",
    navOverview: "总览",
    navEditor: "编辑器",
    navLogs: "决策日志",
    createController: "新建控制器",
    refresh: "刷新",
    controllerPool: "传感器池总览",
    controllerPoolHint: "哪些传感器在喂养哪些控制器；蓝色行表示同一传感器被多个控制器共用。",
    noControllers: "还没有控制器。点「新建控制器」开始构建你的第一个中间层。",
    edit: "编辑",
    logs: "日志",
    evaluateNow: "立即评估",
    enable: "启用",
    disable: "停用",
    delete: "删除",
    confirmDelete: "删除控制器？其输出实体将一并移除。",
    outputs: "输出",
    lastEval: "上次评估",
    never: "从未",
    sensors: "传感器池",
    scanInterval: "扫描间隔",
    logging: "决策日志",
    enabled: "启用",
    controllerName: "控制器名称",
    save: "保存",
    back: "返回总览",
    trialRun: "试运行",
    trialWarn: "试运行与正式评估完全相同，会实际改变输出实体状态。",
    trialNeedSave: "试运行按已保存配置执行；当前有未保存的修改，先保存再试运行。",
    dirtyReload: "保存后控制器将重载，FOR 计时器会清零。",
    addCondition: "添加条件",
    addOutput: "添加输出",
    condNumeric: "数值比较",
    condState: "状态匹配",
    condTime: "时间范围",
    condSun: "日出日落",
    condTemplate: "模板表达式",
    condAnd: "AND 组",
    condOr: "OR 组",
    outSwitch: "开关输出",
    outBinary: "二进制传感器",
    paletteHint: "点选添加节点；从节点右侧圆点拖线到目标输入端口。",
    canvasHint: "拖线组成条件→组→输出的流程；点击节点在右侧编辑参数。",
    inspectorEmpty: "点击画布上的节点编辑参数。",
    entity: "实体",
    label: "标签",
    above: "高于",
    below: "低于",
    state: "状态（逗号分隔多值）",
    after: "开始",
    before: "结束",
    forDuration: "持续（时/分/秒，全 0 表示不启用）",
    template: "模板表达式",
    manualOverride: "手动覆盖（开启后控制器不再写此开关）",
    outputName: "输出名称",
    outputType: "输出类型",
    deleteSelected: "删除选中节点",
    conditionSink1: "满足则开（on_conditions）",
    conditionSink2: "满足则关（off_conditions，优先）",
    members: "成员（由连线决定）",
    logsTitle: "决策日志",
    date: "日期",
    decision: "决策",
    limit: "条数上限",
    query: "查询",
    time: "时间",
    readouts: "读数",
    all: "全部",
    saved: "已保存，控制器重载中",
    sensorEntity: "实体 ID",
    sensorAlias: "别名（可选）",
    addSensor: "添加传感器",
    savedOk: "已保存",
    deleteOk: "已删除",
    evalDone: "评估完成",
    loading: "加载中…",
    mobileNote: "查看模式：编辑请用电脑",
  },
  en: {
    appTitle: "Whole-House State Scanner",
    navOverview: "Overview",
    navEditor: "Editor",
    navLogs: "Decision logs",
    createController: "New controller",
    refresh: "Refresh",
    controllerPool: "Sensor pool overview",
    controllerPoolHint: "Which sensors feed which controllers; blue rows share sensors across controllers.",
    noControllers: "No controllers yet. Click \"New controller\" to build your first middle layer.",
    edit: "Edit",
    logs: "Logs",
    evaluateNow: "Evaluate now",
    enable: "Enable",
    disable: "Disable",
    delete: "Delete",
    confirmDelete: "Delete controller? Its output entities will be removed too.",
    outputs: "Outputs",
    lastEval: "Last evaluation",
    never: "never",
    sensors: "Sensor pool",
    scanInterval: "Scan interval",
    logging: "Decision log",
    enabled: "Enabled",
    controllerName: "Controller name",
    save: "Save",
    back: "Back to overview",
    trialRun: "Trial run",
    trialWarn: "A trial run is identical to a real evaluation and will change output entity states.",
    trialNeedSave: "Trial runs use the saved config; you have unsaved changes — save first.",
    dirtyReload: "Saving reloads the controller; FOR timers reset.",
    addCondition: "Add condition",
    addOutput: "Add output",
    condNumeric: "Numeric state",
    condState: "State match",
    condTime: "Time window",
    condSun: "Sun",
    condTemplate: "Template",
    condAnd: "AND group",
    condOr: "OR group",
    outSwitch: "Switch output",
    outBinary: "Binary sensor",
    paletteHint: "Click to add nodes; drag from the right dot to a target input port.",
    canvasHint: "Wire condition → group → output; click a node to edit it on the right.",
    inspectorEmpty: "Click a node on the canvas to edit it.",
    entity: "Entity",
    label: "Label",
    above: "Above",
    below: "Below",
    state: "State (comma-separated)",
    after: "After",
    before: "Before",
    forDuration: "For (h/m/s, all zero disables)",
    template: "Template expression",
    manualOverride: "Manual override (controller stops writing this switch)",
    outputName: "Output name",
    outputType: "Output type",
    deleteSelected: "Delete selected node",
    conditionSink1: "Met → on (on_conditions)",
    conditionSink2: "Met → off (off_conditions, wins)",
    members: "Members (wired)",
    logsTitle: "Decision logs",
    date: "Date",
    decision: "Decision",
    limit: "Limit",
    query: "Query",
    time: "Time",
    readouts: "Readings",
    all: "All",
    saved: "Saved, controller reloading",
    sensorEntity: "Entity ID",
    sensorAlias: "Alias (optional)",
    addSensor: "Add sensor",
    savedOk: "Saved",
    deleteOk: "Deleted",
    evalDone: "Evaluation done",
    loading: "Loading…",
    mobileNote: "Read-only view — edit on a desktop",
  },
};

/* ------------------------------------------------------------------ */
/* Small helpers                                                       */
/* ------------------------------------------------------------------ */

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

const uidHex = () =>
  (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Math.random().toString(16).slice(2).padEnd(32, "0")).slice(0, 32);

const newCondId = () => `cond_${uidHex()}`;
const newOutId = () => `ssc_${uidHex()}`;

const TYPE_LABEL_KEY = {
  numeric_state: "condNumeric",
  state: "condState",
  time: "condTime",
  sun: "condSun",
  template: "condTemplate",
  and: "condAnd",
  or: "condOr",
};

const TYPE_ICON = {
  numeric_state: "🔢",
  state: "🎚",
  time: "🕐",
  sun: "🌤",
  template: "ƒ",
  and: "⊕",
  or: "⊗",
};

function conditionSummary(cond) {
  let text = "";
  switch (cond.type) {
    case "numeric_state": {
      const parts = [];
      if (cond.above !== undefined && cond.above !== null) parts.push(`> ${cond.above}`);
      if (cond.below !== undefined && cond.below !== null) parts.push(`< ${cond.below}`);
      text = `${cond.entity_id} ${parts.join(" 且 ")}`;
      break;
    }
    case "state":
      text = `${cond.entity_id} = ${Array.isArray(cond.state) ? cond.state.join("/") : cond.state}`;
      break;
    case "time":
      text = [cond.after ? `自 ${cond.after}` : "", cond.before ? `至 ${cond.before}` : ""].filter(Boolean).join(" ");
      break;
    case "sun":
      text = [cond.after ? `${cond.after} 后` : "", cond.before ? `${cond.before} 前` : ""].filter(Boolean).join(" ");
      break;
    case "template":
      text = cond.value_template || "";
      break;
    default:
      text = `${(cond.conditions || []).length} 个成员`;
  }
  if (cond.for && (cond.for.hours || cond.for.minutes || cond.for.seconds)) {
    const f = cond.for;
    text += ` 持续 ${String(f.hours).padStart(2, "0")}:${String(f.minutes).padStart(2, "0")}:${String(f.seconds).padStart(2, "0")}`;
  }
  return cond.label ? `${cond.label}｜${text}` : text;
}

function forEnabled(f) {
  return f && (f.hours || f.minutes || f.seconds);
}

function loadScript(url) {
  return new Promise((resolve, reject) => {
    if (window.Drawflow) return resolve();
    const el = document.createElement("script");
    el.src = url;
    el.onload = resolve;
    el.onerror = () => reject(new Error(`Failed to load ${url}`));
    document.head.appendChild(el);
  });
}

/* ------------------------------------------------------------------ */
/* The panel element                                                   */
/* ------------------------------------------------------------------ */

class ScannerPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._view = "overview";
    this._data = null; // {controllers: {cid: {...config, runtime, active}}}
    this._cid = null; // controller selected for editor / logs
    this._editor = null; // {controller, df, maps..., dirty, isNew}
    this._logs = null;
    this._error = null;
    this._toastTimer = null;
    this._pollTimer = null;
    this._renderQueued = false;
    this._onHash = () => this._applyHash(true);
  }

  set hass(hass) {
    this._hass = hass;
  }

  set narrow(narrow) {
    this._narrow = !!narrow;
  }

  set route(route) {
    // HA drives routing; we keep our sub-views in location.hash.
    this._route = route;
  }

  connectedCallback() {
    const root = this.shadowRoot ?? this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <link rel="stylesheet" href="${STYLE_URL}">
      <link rel="stylesheet" href="${DF_CSS_URL}">
      <div class="wha-app"><main class="wha-main"><p class="wha-sub">${this.tr("loading")}</p></main></div>`
    window.addEventListener("hashchange", this._onHash);
    this._applyHash(false);
    this._boot();
    this._pollTimer = setInterval(() => this._poll(), 5000);
  }

  disconnectedCallback() {
    window.removeEventListener("hashchange", this._onHash);
    if (this._pollTimer) clearInterval(this._pollTimer);
    this._pollTimer = null;
  }

  tr(key) {
    const lang = this._hass?.language || "zh-Hans";
    const dict = LANG[lang] || LANG[String(lang).split("-")[0]] || LANG["zh-Hans"];
    return dict[key] ?? LANG["zh-Hans"][key] ?? key;
  }

  /* ---------------- data ---------------- */

  async _boot() {
    try {
      this._setData(await this._api("GET", "/config"));
      this._error = null;
      this._dataJson = JSON.stringify(this._data);
      this._applyHash(false);
      this._render();
    } catch (err) {
      this._error = String(err.message || err);
      this._render();
    }
  }

  async _api(method, path, body) {
    const hass = this._hass;
    if (!hass?.fetchWithAuth) throw new Error(" hass 未就绪");
    const res = await hass.fetchWithAuth(`${API}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = {};
    try {
      data = await res.json();
    } catch {
      /* empty body */
    }
    if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
    return data;
  }

  async _poll() {
    if (document.hidden || !this.isConnected || this._view === "editor") return;
    try {
      const data = await this._api("GET", "/config");
      const wasError = this._error !== null;
      this._error = null;
      const changed = JSON.stringify(data) !== this._dataJson;
      this._setData(data);
      if (wasError || (changed && this._view === "overview")) this._render();
    } catch {
      /* transient errors stay silent between polls */
    }
  }

  _setData(data) {
    this._data = data;
    this._dataJson = JSON.stringify(data);
  }

  toast(msg, isError = false) {
    const root = this.shadowRoot;
    root.querySelector(".wha-toast")?.remove();
    const el = document.createElement("div");
    el.className = `wha-toast${isError ? " error" : ""}`;
    el.textContent = msg;
    root.appendChild(el);
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => el.remove(), isError ? 6000 : 3000);
  }

  /* ---------------- routing ---------------- */

  _applyHash(rerender) {
    const hash = location.hash || "";
    const m = hash.match(/^#\/(editor|logs)\/?([A-Za-z0-9_]*)/);
    if (m) {
      this._view = m[1];
      if (m[2]) this._cid = m[2];
    } else {
      this._view = "overview";
    }
    if (rerender) this._render();
  }

  _nav(hash) {
    if (location.hash === hash) this._applyHash(true);
    else location.hash = hash;
  }

  /* ---------------- rendering ---------------- */

  _render() {
    if (this._renderQueued) return;
    this._renderQueued = true;
    requestAnimationFrame(() => {
      this._renderQueued = false;
      const root = this.shadowRoot;
      if (!root) return;
      if (this._error) {
        root.querySelector(".wha-app").innerHTML = `
          <main class="wha-main"><div class="wha-card"><b>加载失败</b><p class="wha-sub">${esc(this._error)}</p></div></main>`;
        return;
      }
      if (!this._data) return;
      const app = root.querySelector(".wha-app");
      app.innerHTML = `
        <header class="wha-topbar">
          <h1>${esc(this.tr("appTitle"))}</h1>
          <button class="wha-btn ${this._view === "overview" ? "active" : ""}" data-nav="overview">${esc(this.tr("navOverview"))}</button>
          <button class="wha-btn ${this._view === "editor" ? "active" : ""}" data-nav="editor">${esc(this.tr("navEditor"))}</button>
          <button class="wha-btn ${this._view === "logs" ? "active" : ""}" data-nav="logs">${esc(this.tr("navLogs"))}</button>
          <span class="spacer"></span>
          ${this._view === "overview" ? `<button class="wha-btn primary" data-action="new-controller">${esc(this.tr("createController"))}</button>` : ""}
          <button class="wha-btn" data-action="refresh">${esc(this.tr("refresh"))}</button>
        </header>
        <main class="wha-main" data-main></main>
        <div data-toast-slot></div>
      `;
      app.querySelectorAll("[data-nav]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const v = btn.dataset.nav;
          this._nav(v === "overview" ? "" : `#/${v}${v === "editor" && this._cid ? `/${this._cid}` : ""}`);
        });
      });
      app.querySelector('[data-action="refresh"]')?.addEventListener("click", () => this._boot());
      app.querySelector('[data-action="new-controller"]')?.addEventListener("click", () => this._createController());

      const main = app.querySelector("[data-main]");
      if (this._view === "editor") {
        this._renderEditor(main);
      } else if (this._view === "logs") {
        this._renderLogs(main);
      } else {
        this._renderOverview(main);
      }
    });
  }

  _controllerConfig(cid) {
    const c = this._data?.controllers?.[cid];
    if (!c) return null;
    const { runtime, active, ...config } = c;
    return config;
  }

  _friendlyName(eid) {
    const st = this._hass?.states?.[eid];
    return st?.attributes?.friendly_name || eid;
  }

  /* ---------------- overview ---------------- */

  _renderOverview(main) {
    const controllers = this._data?.controllers || {};
    const cids = Object.keys(controllers);
    const rows = cids
      .map((cid) => {
        const c = controllers[cid];
        const outputs = (c.outputs || [])
          .map((o) => {
            const rt = c.runtime?.outputs?.[o.entity_id];
            const state = rt?.state ?? this._hass?.states?.[rt?.entity_id || ""]?.state ?? "?";
            const dec = rt?.decision || "–";
            const cls = state === "on" ? "on" : state === "off" ? "off" : "";
            return `<span class="badge ${cls}">${esc(o.name)}: ${esc(state)}</span> <span class="badge ${dec}">${esc(dec)}</span>`;
          })
          .join(" ");
        return `
          <div class="wha-card" data-cid="${esc(cid)}">
            <div class="wha-row">
              <h2 style="margin:0">${esc(c.name)}</h2>
              <span class="badge ${c.enabled ? "on" : "hold"}">${c.enabled ? esc(this.tr("enabled")) : "off"}</span>
              <span class="badge meta">${esc(cid)}</span>
              <span class="spacer" style="flex:1"></span>
              <button class="wha-btn" data-act="edit">${esc(this.tr("edit"))}</button>
              <button class="wha-btn" data-act="logs">${esc(this.tr("logs"))}</button>
              <button class="wha-btn" data-act="eval">${esc(this.tr("evaluateNow"))}</button>
              <button class="wha-btn" data-act="toggle">${c.enabled ? esc(this.tr("disable")) : esc(this.tr("enable"))}</button>
              <button class="wha-btn danger" data-act="del">${esc(this.tr("delete"))}</button>
            </div>
            <div class="wha-row" style="margin-top:8px">${outputs || `<span class="wha-sub">—</span>`}</div>
            <p class="wha-sub">${esc(this.tr("lastEval"))}: ${esc(c.runtime?.last_cycle || this.tr("never"))}</p>
          </div>`;
      })
      .join("");

    // global sensor pool view
    const pool = new Map();
    for (const cid of cids) {
      const c = controllers[cid];
      for (const s of c.sensors || []) {
        if (!pool.has(s.entity_id)) pool.set(s.entity_id, { alias: s.alias, cids: [] });
        pool.get(s.entity_id).cids.push(c.name);
      }
    }
    const poolRows = [...pool.entries()]
      .sort((a, b) => a[1].cids.length - b[1].cids.length)
      .map(
        ([eid, info]) => `
        <tr class="${info.cids.length > 1 ? "overlap" : ""}">
          <td>${esc(eid)}</td>
          <td class="wha-sub">${esc(this._friendlyName(eid))}</td>
          <td>${esc(info.cids.join(", "))}</td>
        </tr>`
      )
      .join("");

    main.innerHTML = `
      ${cids.length === 0 ? `<div class="wha-card"><p class="wha-sub">${esc(this.tr("noControllers"))}</p></div>` : `<div class="wha-grid">${rows}</div>`}
      <div class="wha-card">
        <h2>${esc(this.tr("controllerPool"))}</h2>
        <p class="wha-sub">${esc(this.tr("controllerPoolHint"))}</p>
        ${poolRows ? `<table class="wha-table"><thead><tr><th>${esc(this.tr("sensorEntity"))}</th><th>${esc(this.tr("label"))}</th><th>${esc(this.tr("sensors"))}</th></tr></thead><tbody>${poolRows}</tbody></table>` : `<p class="wha-sub">—</p>`}
      </div>`;

    main.querySelectorAll("[data-cid]").forEach((card) => {
      const cid = card.dataset.cid;
      card.querySelectorAll("[data-act]").forEach((btn) =>
        btn.addEventListener("click", (ev) => this._overviewAction(ev.currentTarget.dataset.act, cid))
      );
    });
  }

  async _overviewAction(act, cid) {
    try {
      if (act === "edit") {
        this._nav(`#/editor/${cid}`);
        return;
      }
      if (act === "logs") {
        this._nav(`#/logs/${cid}`);
        return;
      }
      if (act === "eval") {
        await this._api("POST", `/controllers/${cid}/evaluate`);
        this.toast(this.tr("evalDone"));
        this._setData(await this._api("GET", "/config"));
        this._render();
        return;
      }
      if (act === "toggle") {
        const config = this._controllerConfig(cid);
        config.enabled = !config.enabled;
        await this._api("PUT", `/controllers/${cid}`, config);
        await this._sleepReload();
        return;
      }
      if (act === "del") {
        if (!confirm(this.tr("confirmDelete"))) return;
        await this._api("DELETE", `/controllers/${cid}`);
        this.toast(this.tr("deleteOk"));
        await this._sleepReload();
      }
    } catch (err) {
      this.toast(String(err.message || err), true);
    }
  }

  async _sleepReload() {
    this.toast(this.tr("saved"));
    await new Promise((r) => setTimeout(r, 1200));
    this._setData(await this._api("GET", "/config"));
    this._render();
  }

  async _createController() {
    try {
      const r = await this._api("POST", "/controllers", {
        name: `${this.tr("controllerName")} ${Object.keys(this._data?.controllers || {}).length + 1}`,
      });
      this.toast(this.tr("saved"));
      await new Promise((r2) => setTimeout(r2, 1200));
      this._setData(await this._api("GET", "/config"));
      this._nav(`#/editor/${r.id}`);
    } catch (err) {
      this.toast(String(err.message || err), true);
    }
  }

  /* ---------------- editor ---------------- */

  async _renderEditor(main) {
    const cid = this._cid;
    const isNew = !cid || !this._data?.controllers?.[cid];
    let config;
    if (isNew) {
      config = {
        name: "",
        enabled: true,
        scan_interval: 180,
        logging_enabled: true,
        sensors: [],
        conditions: [],
        outputs: [],
      };
    } else {
      config = JSON.parse(JSON.stringify(this._controllerConfig(cid)));
    }
    this._editor = {
      cid: isNew ? null : cid,
      isNew,
      controller: config,
      dirty: false,
      df: null,
      nodeToCond: new Map(),
      condToNode: new Map(),
      nodeToOut: new Map(),
      outToNode: new Map(),
      selected: null,
      trial: null,
    };

    main.innerHTML = `
      <div class="wha-editor">
        <div class="wha-editor-note">📱 ${esc(this.tr("mobileNote"))}</div>
        <div class="wha-editor-head">
          <label>${esc(this.tr("controllerName"))}<input class="wha-input" data-field="name" value="${esc(config.name)}" style="min-width:180px"></label>
          <label class="field-inline" style="justify-content:center"><input type="checkbox" data-field="enabled" ${config.enabled ? "checked" : ""}> ${esc(this.tr("enabled"))}</label>
          <label>${esc(this.tr("scanInterval"))}(s)<input class="wha-input" type="number" min="10" max="3600" data-field="scan_interval" value="${esc(config.scan_interval)}" style="width:90px"></label>
          <label class="field-inline" style="justify-content:center"><input type="checkbox" data-field="logging_enabled" ${config.logging_enabled ? "checked" : ""}> ${esc(this.tr("logging"))}</label>
          <span class="spacer" style="flex:1"></span>
          <button class="wha-btn" data-act="delete-node">${esc(this.tr("deleteSelected"))}</button>
          <button class="wha-btn" data-act="trial" ${isNew ? "disabled" : ""}>${esc(this.tr("trialRun"))}</button>
          <button class="wha-btn primary" data-act="save">${esc(this.tr("save"))}</button>
          <button class="wha-btn" data-act="back">${esc(this.tr("back"))}</button>
        </div>
        <details class="wha-card" style="flex:none">
          <summary>${esc(this.tr("sensors"))} (${config.sensors.length})</summary>
          <div data-sensors></div>
        </details>
        <div class="wha-editor-body">
          <div class="wha-palette">
            <h3>${esc(this.tr("addCondition"))}</h3>
            ${["numeric_state", "state", "time", "sun", "template", "and", "or"]
              .map((tp) => `<button class="wha-btn" data-add-cond="${tp}">${TYPE_ICON[tp]} ${esc(this.tr(TYPE_LABEL_KEY[tp]))}</button>`)
              .join("")}
            <h3>${esc(this.tr("addOutput"))}</h3>
            <button class="wha-btn" data-add-out="switch">⏻ ${esc(this.tr("outSwitch"))}</button>
            <button class="wha-btn" data-add-out="binary_sensor">◉ ${esc(this.tr("outBinary"))}</button>
            <p class="wha-sub" style="margin-top:10px">${esc(this.tr("paletteHint"))}</p>
            <p class="wha-sub">${esc(this.tr("conditionSink1"))}<br>${esc(this.tr("conditionSink2"))}</p>
          </div>
          <div class="wha-canvas-wrap">
            <div id="wha-drawflow"></div>
            <div class="wha-canvas-hint">${esc(this.tr("canvasHint"))}</div>
            <div class="wha-zoom-fab" data-zoom>
              <button type="button" data-z="in">＋</button>
              <button type="button" data-z="out">－</button>
              <button type="button" data-z="reset">⌂</button>
            </div>
          </div>
          <div class="wha-inspector" data-inspector>
            <p class="wha-sub">${esc(this.tr("inspectorEmpty"))}</p>
          </div>
        </div>
        <div class="wha-sub wha-reload-note" style="padding:4px 2px">${esc(this.tr("dirtyReload"))}</div>
      </div>`;

    this._renderSensorPool(main.querySelector("[data-sensors]"));

    // head field bindings
    main.querySelectorAll("[data-field]").forEach((input) => {
      input.addEventListener("change", () => {
        const f = input.dataset.field;
        if (f === "enabled" || f === "logging_enabled") this._editor.controller[f] = input.checked;
        else if (f === "scan_interval") this._editor.controller[f] = Number(input.value) || 180;
        else this._editor.controller[f] = input.value;
        this._editor.dirty = true;
      });
    });

    // palette
    main.querySelectorAll("[data-add-cond]").forEach((btn) =>
      btn.addEventListener("click", () => this._addConditionNode(btn.dataset.addCond))
    );
    main.querySelectorAll("[data-add-out]").forEach((btn) =>
      btn.addEventListener("click", () => this._addOutputNode(btn.dataset.addOut))
    );
    main.querySelector('[data-act="save"]')?.addEventListener("click", () => this._saveEditor());
    main.querySelector('[data-act="trial"]')?.addEventListener("click", () => this._trialRun());
    main.querySelector('[data-act="back"]')?.addEventListener("click", () => this._nav(""));
    main.querySelector('[data-act="delete-node"]')?.addEventListener("click", () => this._deleteSelected());
    main.querySelectorAll("[data-zoom] [data-z]").forEach((b) =>
      b.addEventListener("click", () => {
        const df = this._editor && this._editor.df;
        if (!df) return;
        if (b.dataset.z === "in") df.zoom_in();
        else if (b.dataset.z === "out") df.zoom_out();
        else df.zoom_reset();
      })
    );

    try {
      await loadScript(DF_JS_URL);
    } catch (err) {
      this.toast(String(err.message || err), true);
      return;
    }
    this._initCanvas(main.querySelector("#wha-drawflow"));
  }

  _renderSensorPool(container) {
    const sensors = this._editor.controller.sensors;
    const entities = Object.keys(this._hass?.states || {}).sort();
    container.innerHTML = `
      <table class="wha-table">
        <thead><tr><th>${esc(this.tr("sensorEntity"))}</th><th>${esc(this.tr("sensorAlias"))}</th><th></th></tr></thead>
        <tbody>
          ${sensors
            .map(
              (s, i) => `
            <tr>
              <td><input class="wha-input" list="wha-entities" data-si="${i}" data-sk="entity_id" value="${esc(s.entity_id)}" style="width:100%"></td>
              <td><input class="wha-input" data-si="${i}" data-sk="alias" value="${esc(s.alias || "")}" style="width:120px"></td>
              <td><button class="wha-btn danger" data-sdel="${i}">✕</button></td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
      <datalist id="wha-entities">${entities.map((e) => `<option value="${esc(e)}">${esc(this._friendlyName(e))}</option>`).join("")}</datalist>
      <button class="wha-btn" data-sadd style="margin-top:8px">＋ ${esc(this.tr("addSensor"))}</button>`;

    container.querySelectorAll("[data-si]").forEach((input) => {
      input.addEventListener("change", () => {
        sensors[Number(input.dataset.si)][input.dataset.sk] = input.value.trim();
        this._editor.dirty = true;
      });
    });
    container.querySelectorAll("[data-sdel]").forEach((btn) => {
      btn.addEventListener("click", () => {
        sensors.splice(Number(btn.dataset.sdel), 1);
        this._editor.dirty = true;
        this._renderSensorPool(container);
      });
    });
    container.querySelector("[data-sadd]")?.addEventListener("click", () => {
      sensors.push({ entity_id: "", alias: "" });
      this._editor.dirty = true;
      this._renderSensorPool(container);
    });
  }

  /* ----- drawflow wiring ----- */

  _initCanvas(container) {
    const ed = this._editor;
    const df = new window.Drawflow(container);
    df.start();
    ed.df = df;
    ed.importing = true;
    df.on("nodeSelected", (nodeId) => this._selectNode(Number(nodeId)));
    df.on("connectionCreated", () => {
      if (!ed.importing) ed.dirty = true;
    });
    df.on("connectionRemoved", () => {
      if (!ed.importing) ed.dirty = true;
    });
    df.on("nodeRemoved", (nodeId) => {
      const n = Number(nodeId);
      const condId = ed.nodeToCond.get(n);
      if (condId) {
        ed.nodeToCond.delete(n);
        ed.condToNode.delete(condId);
        ed.controller.conditions = ed.controller.conditions.filter((c) => c.id !== condId);
        // cascade: drop dangling references from groups and outputs
        for (const c of ed.controller.conditions) {
          if (c.conditions) c.conditions = c.conditions.filter((m) => m !== condId);
        }
        for (const o of ed.controller.outputs) {
          o.on_conditions = o.on_conditions.filter((m) => m !== condId);
          o.off_conditions = o.off_conditions.filter((m) => m !== condId);
        }
      }
      const outId = ed.nodeToOut.get(n);
      if (outId) {
        ed.nodeToOut.delete(n);
        ed.outToNode.delete(outId);
        ed.controller.outputs = ed.controller.outputs.filter((o) => o.entity_id !== outId);
      }
      ed.dirty = true;
    });

    // import existing model
    const conds = ed.controller.conditions;
    conds.forEach((cond, i) => {
      const isGroup = cond.type === "and" || cond.type === "or";
      const x = isGroup ? 420 : 20;
      this._dfAddCondNode(cond, x, 20 + i * 120);
    });
    ed.controller.outputs.forEach((out, i) => {
      this._dfAddOutNode(out, this._outX(), 30 + i * 140);
    });
    // connections
    for (const cond of conds) {
      if (cond.type !== "and" && cond.type !== "or") continue;
      const gid = ed.condToNode.get(cond.id);
      for (const m of cond.conditions || []) {
        const mid = ed.condToNode.get(m);
        if (mid && gid) df.addConnection(String(mid), String(gid), "output_1", "input_1");
      }
    }
    for (const out of ed.controller.outputs) {
      const oid = ed.outToNode.get(out.entity_id);
      if (!oid) continue;
      for (const m of out.on_conditions || []) {
        const mid = ed.condToNode.get(m);
        if (mid) df.addConnection(String(mid), String(oid), "output_1", "input_1");
      }
      for (const m of out.off_conditions || []) {
        const mid = ed.condToNode.get(m);
        if (mid) df.addConnection(String(mid), String(oid), "output_1", "input_2");
      }
    }
    ed.importing = false;
  }

  _outX() {
    const width = this._editor.df?.container?.clientWidth || 1000;
    return Math.max(520, width - 300);
  }

  _condNodeHtml(cond) {
    const group = cond.type === "and" || cond.type === "or";
    return `
      <div class="wha-node-body-wrap">
        <div class="wha-node-head">
          <span>${TYPE_ICON[cond.type] || "?"}</span>
          <span data-nhead>${esc(this.tr(TYPE_LABEL_KEY[cond.type]))}</span>
          ${group ? "" : `<span class="wha-node-tag">${esc(cond.type)}</span>`}
        </div>
        <div class="wha-node-body" data-nbody>${esc(conditionSummary(cond))}</div>
      </div>`;
  }

  _outNodeHtml(out) {
    return `
      <div class="wha-node-body-wrap">
        <div class="wha-node-head">
          <span>${out.type === "switch" ? "⏻" : "◉"}</span>
          <span data-nhead>${esc(out.name)}</span>
          <span class="wha-node-tag">${esc(out.type)}</span>
        </div>
        <div class="wha-node-body" data-nbody>
          ${out.manual_override ? "✋ " : ""}${esc(out.entity_id)}
        </div>
        <span class="decision-badge" data-badge style="display:none"></span>
      </div>`;
  }

  _dfAddCondNode(cond, x, y) {
    const ed = this._editor;
    const isGroup = cond.type === "and" || cond.type === "or";
    const nodeId = ed.df.addNode(
      cond.type,
      isGroup ? 1 : 0,
      1,
      x,
      y,
      `wha-node cond-${cond.type}`,
      { condId: cond.id },
      this._condNodeHtml(cond)
    );
    ed.nodeToCond.set(nodeId, cond.id);
    ed.condToNode.set(cond.id, nodeId);
    return nodeId;
  }

  _dfAddOutNode(out, x, y) {
    const ed = this._editor;
    const nodeId = ed.df.addNode(
      "output",
      2,
      0,
      x,
      y,
      "wha-node wha-out",
      { outId: out.entity_id },
      this._outNodeHtml(out)
    );
    ed.nodeToOut.set(nodeId, out.entity_id);
    ed.outToNode.set(out.entity_id, nodeId);
    return nodeId;
  }

  _addConditionNode(type) {
    const ed = this._editor;
    const cond = { id: newCondId(), type, label: "" };
    if (type === "numeric_state") {
      cond.entity_id = "";
      cond.above = 0;
    } else if (type === "state") {
      cond.entity_id = "";
      cond.state = "on";
    } else if (type === "time") {
      cond.after = "00:00";
    } else if (type === "sun") {
      cond.after = "sunset";
    } else if (type === "template") {
      cond.value_template = "{{ true }}";
    } else {
      cond.conditions = [];
    }
    ed.controller.conditions.push(cond);
    const count = ed.controller.conditions.length;
    const nodeId = this._dfAddCondNode(cond, type === "and" || type === "or" ? 420 : 20, 20 + (count - 1) * 120);
    this._selectNode(nodeId);
    ed.dirty = true;
  }

  _addOutputNode(type) {
    const ed = this._editor;
    const out = {
      name: type === "switch" ? this.tr("outSwitch") : this.tr("outBinary"),
      type,
      entity_id: newOutId(),
      on_conditions: [],
      off_conditions: [],
      manual_override: false,
    };
    ed.controller.outputs.push(out);
    const count = ed.controller.outputs.length;
    const nodeId = this._dfAddOutNode(out, this._outX(), 30 + (count - 1) * 140);
    this._selectNode(nodeId);
    ed.dirty = true;
  }

  _deleteSelected() {
    const ed = this._editor;
    if (!ed.selected) return;
    ed.df.removeNodeId(`node-${ed.selected.nodeId}`);
    // nodeRemoved handler updates the model
    ed.selected = null;
    this._renderInspector();
  }

  _selectNode(nodeId) {
    const ed = this._editor;
    const condId = ed.nodeToCond.get(nodeId);
    const outId = ed.nodeToOut.get(nodeId);
    ed.selected = { nodeId, condId: condId || null, outId: outId || null };
    this._renderInspector();
  }

  _refreshNodeBody(nodeId) {
    const ed = this._editor;
    if (!ed.df) return;
    const el = ed.df.container?.querySelector(`#node-${nodeId}`);
    if (!el) return;
    const condId = ed.nodeToCond.get(nodeId);
    const outId = ed.nodeToOut.get(nodeId);
    const body = el.querySelector("[data-nbody]");
    const head = el.querySelector("[data-nhead]");
    if (condId) {
      const cond = ed.controller.conditions.find((c) => c.id === condId);
      if (!cond) return;
      if (head) head.textContent = this.tr(TYPE_LABEL_KEY[cond.type]);
      if (body) body.textContent = conditionSummary(cond);
    } else if (outId) {
      const out = ed.controller.outputs.find((o) => o.entity_id === outId);
      if (!out) return;
      if (head) head.textContent = out.name;
      if (body) body.innerHTML = `${out.manual_override ? "✋ " : ""}${esc(out.entity_id)}`;
    }
  }

  /* ----- inspector ----- */

  _renderInspector() {
    const root = this.shadowRoot;
    const box = root.querySelector("[data-inspector]");
    if (!box) return;
    const ed = this._editor;
    const sel = ed.selected;
    if (!sel) {
      box.innerHTML = `<p class="wha-sub">${esc(this.tr("inspectorEmpty"))}</p>`;
      return;
    }
    const entities = Object.keys(this._hass?.states || {}).sort();
    const datalist = `<datalist id="wha-entities-insp">${entities.map((e) => `<option value="${esc(e)}">${esc(this._friendlyName(e))}</option>`).join("")}</datalist>`;

    if (sel.outId) {
      const out = ed.controller.outputs.find((o) => o.entity_id === sel.outId);
      if (!out) return;
      box.innerHTML = `
        ${datalist}
        <h3>${esc(this.tr("outSwitch"))} / ${esc(this.tr("outBinary"))}</h3>
        <label class="field"><span>${esc(this.tr("outputName"))}</span><input class="wha-input" data-insk="name" value="${esc(out.name)}"></label>
        <label class="field"><span>${esc(this.tr("outputType"))}</span>
          <select class="wha-input" data-insk="type">
            <option value="switch" ${out.type === "switch" ? "selected" : ""}>${esc(this.tr("outSwitch"))}</option>
            <option value="binary_sensor" ${out.type === "binary_sensor" ? "selected" : ""}>${esc(this.tr("outBinary"))}</option>
          </select>
        </label>
        <label class="field field-inline"><input type="checkbox" data-insk="manual_override" ${out.manual_override ? "checked" : ""}> ${esc(this.tr("manualOverride"))}</label>
        <p class="wha-sub">${esc(out.entity_id)}</p>
        ${this._trialHtml()}`;
      box.querySelectorAll("[data-insk]").forEach((input) =>
        input.addEventListener("change", () => {
          const k = input.dataset.insk;
          out[k] = input.type === "checkbox" ? input.checked : input.value;
          ed.dirty = true;
          this._refreshNodeBody(sel.nodeId);
        })
      );
      return;
    }

    const cond = ed.controller.conditions.find((c) => c.id === sel.condId);
    if (!cond) return;
    const isGroup = cond.type === "and" || cond.type === "or";
    const f = cond.for || { hours: 0, minutes: 0, seconds: 0 };
    box.innerHTML = `
      ${isGroup ? "" : datalist}
      <h3>${esc(this.tr(TYPE_LABEL_KEY[cond.type]))}</h3>
      <label class="field"><span>${esc(this.tr("label"))}</span><input class="wha-input" data-insk="label" value="${esc(cond.label || "")}"></label>
      ${isGroup
        ? `<p class="wha-sub">${esc(this.tr("members"))}: ${(cond.conditions || []).length}</p>`
        : this._condFieldsHtml(cond)}
      ${isGroup
        ? ""
        : `<label class="field"><span>${esc(this.tr("forDuration"))}</span><span class="wha-row">
            <input class="wha-input" type="number" min="0" max="24" style="width:64px" data-for="hours" value="${esc(f.hours)}">:
            <input class="wha-input" type="number" min="0" max="59" style="width:64px" data-for="minutes" value="${esc(f.minutes)}">:
            <input class="wha-input" type="number" min="0" max="59" style="width:64px" data-for="seconds" value="${esc(f.seconds)}">
          </span></label>`}
      ${this._trialHtml()}`;

    box.querySelectorAll("[data-insk]").forEach((input) =>
      input.addEventListener("change", () => {
        const k = input.dataset.insk;
        let v = input.value;
        if (k === "above" || k === "below" || k.endsWith("_offset")) {
          v = v === "" ? null : Number(v);
        } else if (k === "state") {
          const parts = String(v).split(",").map((s) => s.trim()).filter(Boolean);
          v = parts.length > 1 ? parts : parts[0] || "on";
        }
        cond[k] = v;
        ed.dirty = true;
        this._refreshNodeBody(sel.nodeId);
      })
    );
    box.querySelectorAll("[data-for]").forEach((input) =>
      input.addEventListener("change", () => {
        cond.for = {
          hours: Number(box.querySelector('[data-for="hours"]').value) || 0,
          minutes: Number(box.querySelector('[data-for="minutes"]').value) || 0,
          seconds: Number(box.querySelector('[data-for="seconds"]').value) || 0,
        };
        if (!forEnabled(cond.for)) cond.for = undefined;
        ed.dirty = true;
        this._refreshNodeBody(sel.nodeId);
      })
    );
  }

  _condFieldsHtml(cond) {
    const trk = (k) => this.tr(k);
    switch (cond.type) {
      case "numeric_state":
        return `
          <label class="field"><span>${esc(trk("entity"))}</span><input class="wha-input" list="wha-entities-insp" data-insk="entity_id" value="${esc(cond.entity_id || "")}"></label>
          <label class="field"><span>${esc(trk("above"))}</span><input class="wha-input" type="number" step="any" data-insk="above" value="${esc(cond.above ?? "")}"></label>
          <label class="field"><span>${esc(trk("below"))}</span><input class="wha-input" type="number" step="any" data-insk="below" value="${esc(cond.below ?? "")}"></label>`;
      case "state":
        return `
          <label class="field"><span>${esc(trk("entity"))}</span><input class="wha-input" list="wha-entities-insp" data-insk="entity_id" value="${esc(cond.entity_id || "")}"></label>
          <label class="field"><span>${esc(trk("state"))}</span><input class="wha-input" data-insk="state" value="${esc(Array.isArray(cond.state) ? cond.state.join(",") : cond.state || "")}"></label>`;
      case "time":
        return `
          <label class="field"><span>${esc(trk("after"))}(HH:MM)</span><input class="wha-input" placeholder="22:00" data-insk="after" value="${esc(cond.after || "")}"></label>
          <label class="field"><span>${esc(trk("before"))}(HH:MM)</span><input class="wha-input" placeholder="06:00" data-insk="before" value="${esc(cond.before || "")}"></label>`;
      case "sun":
        return `
          <label class="field"><span>${esc(trk("after"))}</span>
            <select class="wha-input" data-insk="after">
              ${["", "sunrise", "sunset"].map((v) => `<option value="${v}" ${cond.after === v ? "selected" : ""}>${v || "—"}</option>`).join("")}
            </select></label>
          <label class="field"><span>${esc(trk("before"))}</span>
            <select class="wha-input" data-insk="before">
              ${["", "sunrise", "sunset"].map((v) => `<option value="${v}" ${cond.before === v ? "selected" : ""}>${v || "—"}</option>`).join("")}
            </select></label>
          <label class="field"><span>after_offset(s)</span><input class="wha-input" type="number" step="1" data-insk="after_offset" value="${esc(cond.after_offset ?? "")}"></label>
          <label class="field"><span>before_offset(s)</span><input class="wha-input" type="number" step="1" data-insk="before_offset" value="${esc(cond.before_offset ?? "")}"></label>`;
      case "template":
        return `
          <label class="field"><span>${esc(trk("template"))}</span><textarea class="wha-input" rows="3" data-insk="value_template">${esc(cond.value_template || "")}</textarea></label>`;
      default:
        return "";
    }
  }

  _trialHtml() {
    if (!this._editor.trial) return "";
    const t = this._editor.trial;
    return `
      <details class="wha-json">
        <summary>readings / results</summary>
        <pre>${esc(JSON.stringify(t, null, 2))}</pre>
      </details>`;
  }

  /* ----- graph export / save / trial ----- */

  _exportGraph() {
    const ed = this._editor;
    if (!ed.df) return;
    const data = ed.df.export()?.drawflow?.Home?.data || {};
    const nodeRefs = (nodeId, inputClass) => {
      const node = data[`node-${nodeId}`];
      return (node?.inputs?.[inputClass]?.connections || [])
        .map((c) => ed.nodeToCond.get(Number(c.node)))
        .filter(Boolean);
    };
    for (const cond of ed.controller.conditions) {
      if (cond.type !== "and" && cond.type !== "or") continue;
      const nid = ed.condToNode.get(cond.id);
      cond.conditions = nid ? nodeRefs(nid, "input_1") : [];
    }
    for (const out of ed.controller.outputs) {
      const nid = ed.outToNode.get(out.entity_id);
      out.on_conditions = nid ? nodeRefs(nid, "input_1") : [];
      out.off_conditions = nid ? nodeRefs(nid, "input_2") : [];
    }
  }

  async _saveEditor() {
    const ed = this._editor;
    this._exportGraph();
    if (!ed.controller.name?.trim()) {
      this.toast(this.tr("controllerName"), true);
      return;
    }
    const payload = JSON.parse(JSON.stringify(ed.controller));
    try {
      if (ed.isNew) {
        const r = await this._api("POST", "/controllers", payload);
        ed.cid = r.id;
        ed.isNew = false;
      } else {
        await this._api("PUT", `/controllers/${ed.cid}`, payload);
      }
      ed.dirty = false;
      this.toast(this.tr("savedOk"));
      this._setData(await this._api("GET", "/config"));
      if (location.hash !== `#/editor/${ed.cid}`) this._nav(`#/editor/${ed.cid}`);
    } catch (err) {
      this.toast(String(err.message || err), true);
    }
  }

  async _trialRun() {
    const ed = this._editor;
    if (ed.isNew) {
      this.toast(this.tr("trialNeedSave"), true);
      return;
    }
    if (ed.dirty && !confirm(this.tr("trialNeedSave"))) return;
    try {
      const r = await this._api("POST", `/controllers/${ed.cid}/evaluate`);
      ed.trial = r;
      // color condition nodes by met/unmet
      for (const [condId, nodeId] of ed.condToNode) {
        const el = ed.df.container?.querySelector(`#node-${nodeId}`);
        if (!el) continue;
        const met = r.conditions[condId];
        el.classList.toggle("met", met === true);
        el.classList.toggle("unmet", met === false);
      }
      for (const [outId, nodeId] of ed.outToNode) {
        const el = ed.df.container?.querySelector(`#node-${nodeId}`);
        const detail = r.outputs[outId];
        if (!el || !detail) continue;
        const badge = el.querySelector("[data-badge]");
        if (badge) {
          badge.style.display = "";
          badge.className = `decision-badge ${detail.decision}`;
          badge.textContent = detail.decision + (detail.applied ? " ✓" : detail.override ? " ✋" : "");
        }
      }
      this._renderInspector();
      this.toast(this.tr("evalDone"));
    } catch (err) {
      this.toast(String(err.message || err), true);
    }
  }

  /* ---------------- logs ---------------- */

  async _renderLogs(main) {
    const controllers = this._data?.controllers || {};
    const cids = Object.keys(controllers);
    const cid = this._cid && controllers[this._cid] ? this._cid : cids[0] || "";
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    main.innerHTML = `
      <div class="wha-card">
        <h2>${esc(this.tr("logsTitle"))}</h2>
        <div class="wha-row">
          <select class="wha-input" data-lf="cid">
            ${cids.map((c) => `<option value="${esc(c)}" ${c === cid ? "selected" : ""}>${esc(controllers[c].name)}</option>`).join("")}
          </select>
          <input class="wha-input" type="date" data-lf="date" value="${today}">
          <select class="wha-input" data-lf="decision">
            <option value="">${esc(this.tr("all"))}</option>
            <option value="on">on</option>
            <option value="off">off</option>
            <option value="hold">hold</option>
          </select>
          <input class="wha-input" type="number" min="10" max="5000" value="500" data-lf="limit" style="width:90px">
          <button class="wha-btn primary" data-lact="query">${esc(this.tr("query"))}</button>
        </div>
      </div>
      <div class="wha-card" data-logresult><p class="wha-sub">—</p></div>`;

    const query = async () => {
      const box = main.querySelector("[data-logresult]");
      box.innerHTML = `<p class="wha-sub">${esc(this.tr("loading"))}</p>`;
      try {
        const params = new URLSearchParams({
          controller_id: main.querySelector('[data-lf="cid"]').value,
          date: main.querySelector('[data-lf="date"]').value,
          limit: main.querySelector('[data-lf="limit"]').value || "500",
        });
        const dec = main.querySelector('[data-lf="decision"]').value;
        if (dec) params.set("decision", dec);
        this._logs = await this._api("GET", `/logs?${params}`);
        this._renderLogTable(box);
      } catch (err) {
        box.innerHTML = `<p class="wha-sub">${esc(String(err.message || err))}</p>`;
      }
    };
    main.querySelector('[data-lact="query"]').addEventListener("click", query);
    query();
  }

  _renderLogTable(box) {
    const logs = this._logs || { records: [], truncated: false };
    const rows = (logs.records || [])
      .map((r) => {
        const cls = r.decision === "on" ? "on" : r.decision === "off" ? "off" : "hold";
        return `
        <tr>
          <td class="wha-sub">${esc((r.timestamp || "").replace("T", " ").slice(0, 19))}</td>
          <td>${esc(r.output || "")}</td>
          <td><span class="badge ${cls}">${esc(r.decision)}</span></td>
          <td>${r.on_met ? "✓" : "—"}</td>
          <td>${r.off_met ? "✓" : "—"}</td>
          <td>${r.applied ? "✓" : "—"}${r.override ? " ✋" : ""}</td>
          <td>
            <details class="wha-json"><summary>${esc(this.tr("readouts"))}</summary>
              <pre>${esc(JSON.stringify(r.readings || {}, null, 2))}</pre>
            </details>
          </td>
        </tr>`;
      })
      .join("");
    box.innerHTML = `
      ${logs.truncated ? `<p class="wha-sub">⚠ limit</p>` : ""}
      ${rows
        ? `<table class="wha-table"><thead><tr>
            <th>${esc(this.tr("time"))}</th><th>${esc(this.tr("outputs"))}</th><th>${esc(this.tr("decision"))}</th>
            <th>on_met</th><th>off_met</th><th>applied</th><th>${esc(this.tr("readouts"))}</th>
          </tr></thead><tbody>${rows}</tbody></table>`
        : `<p class="wha-sub">—</p>`}`;
  }
}

customElements.define(TAG, ScannerPanel);
