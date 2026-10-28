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
// inherit the panel module's version query (?ver=...) so style.css and
// panel.js always invalidate together (WHA-F-052)
const STYLE_URL = `/sensor_switch_controller/style.css${new URL(import.meta.url).search}`;
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
    edit: "编辑",
    logs: "日志",
    evaluateNow: "立即评估",
    enable: "启用",
    disable: "停用",
    delete: "删除",
    confirmDelete: "删除控制器？其输出实体将一并移除。",
    confirmTitle: "确认操作",
    confirmOk: "确定",
    confirmCancel: "取消",
    trialDirtyConfirm: "有未保存的修改。试运行将按已保存的配置执行，未保存的修改不会生效。继续？",
    evaluateConfirmBody: "的输出将按当前条件立即动作。确定执行？",
    logsEmpty: "该日无决策记录",
    logsTruncated: "已达单次查询上限，可缩小日期范围或调大条数",
    noControllers: "尚无控制器 — 点「新建控制器」开始",
    condFlag: "旗标",
    flagHint: "旗标=锁存记忆：任一置位条件满足→开；任一复位条件满足→关（复位优先）；其余保持。置位/复位口可接多根线，评估周期开始时统一步进。",
    flagInitial: "初始为开（无存档时）",
    summaryFlagIdle: "未配置置位/复位",
    portSet: "置位",
    portReset: "复位",
    trgBadgeLegacy: "全量",
    trgBadgeDead: "死",
    trgBadgeDeadHint: "该触发器已定向但未连任何条件：它不会评估任何输出。请在画布把信号线连到条件。",
    trgDeadConfirm: "有已启用但未连任何条件的定向触发器（保存后不会评估任何输出）。仍要保存吗？\n确定=保存；取消=返回修改。",
    outputs: "输出",
    lastEval: "上次评估",
    never: "从未",
    sensors: "传感器池",
    logging: "决策日志",
    enabled: "启用",
    controllerName: "控制器名称",
    save: "保存",
    back: "返回总览",
    trialRun: "试运行",
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
    canvasHint: "⚡触发器信号线（琥珀）拉到条件的「信号」口开始评估流程；结果只由条件链（灰蓝）决定；点节点编辑参数。",
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
    decision: "决策",
    query: "查询",
    time: "时间",
    readouts: "读数",
    logConditions: "条件明细",
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
    triggersTitle: "触发器",
    addTrigger: "添加触发器",
    triggerState: "状态触发",
    triggerTime: "时间触发",
    triggerSun: "太阳触发",
    triggerSunEvent: "太阳事件",
    triggerStart: "HA 启动（重载也会触发）",
    triggerEntity: "触发实体（必填）",
    triggerEntityHint: "支持逗号分隔多个实体",
    triggerNEntities: "%d 个实体",
    triggerAttribute: "attribute",
    triggerFrom: "从状态（可选）",
    triggerTo: "到状态（可选）",
    triggerAt: "每日时刻 HH:MM",
    triggerEvery: "每 N 秒",
    triggerOffset: "偏移（秒，可负）",
    condCooldown: "翻转冷却",
    condCalendar: "日历",
    condNot: "NOT 组",
    condDuration: "持续（满 N 秒）",
    condDebounce: "防抖（静默 N 秒）",
    cooldownSeconds: "冷却秒数",
    calendarHours: "未来小时数",
    durationSeconds: "持续秒数",
    debounceSeconds: "静默秒数",
    debounceEntity: "静默实体",
    wiredStart: "开始（由连线决定）",
    wiredAbort: "中止（可选，由连线决定）",
    conditionSink3: "信号口：触发器信号线连到这里（普通条件与逻辑组有；持续/输出没有；组上与成员口互斥）",
    trgRoutesLabel: "信号覆盖条件（由信号线决定）",
    trgLegacyLabel: "遗留触发器：全量评估（保存并连线后改为定向）",
    badConnection: "连线被拒：琥珀信号线从触发器拖到条件或逻辑组的「信号」口；持续与输出没有信号口。",
    portSignal: "信号",
    portOn: "满足则开",
    portOff: "满足则关",
    portStart: "开始",
    portAbort: "中止",
    portMembers: "成员",
    portOut: "出",
    logicGroups: "逻辑组",
    logicGroupHint: "统筹条件逻辑（连成员线）或触发逻辑（连信号线，可多条=任一触发放行）——二选一，先连先得；空组也可直接连信号",
    trgGateMutexMembers: "该组是条件逻辑组（已连成员）：信号口已隐藏，不能再连信号",
    trgGateMutexSignal: "该组是触发逻辑组（已连信号）：成员口已隐藏，不能再连成员",
    passthrough: "触发合并 · 贯通",
    observeUnavailable: "实时状态不可用（观察端点失败），请查看日志",
    observeUnavailableShort: "观察不可用",
    weekdaysLabel: "星期几",
    byLabel: "触发来源",
    enabledLabel: "启用",
    summaryAnd: " 且 ",
    summaryFrom: "自",
    summaryTo: "至",
    summarySunAfter: "后",
    summarySunBefore: "前",
    summaryCooldown: "距上次翻转 ≥",
    summaryDuration: "开始后持续",
    summaryDebounce: "静默 ≥",
    summaryCalendarLead: "未来",
    summaryCalendarTail: "h 有事件",
    summaryMembers: " 个成员",
    summaryFor: " 持续 ",
    loadFailed: "加载失败",
    invalidBadge: "配置无效",
    invalidStoredLead: "存储中的配置无法载入：",
    invalidStoredTail: "请删除后重新创建控制器。",
    triggerErrorBadge: "触发器错误",
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
    edit: "Edit",
    logs: "Logs",
    evaluateNow: "Evaluate now",
    enable: "Enable",
    disable: "Disable",
    delete: "Delete",
    confirmDelete: "Delete controller? Its output entities will be removed too.",
    confirmTitle: "Confirm",
    confirmOk: "OK",
    confirmCancel: "Cancel",
    trialDirtyConfirm: "You have unsaved changes. The trial runs the SAVED config — unsaved changes will not apply. Continue?",
    evaluateConfirmBody: " will act on current conditions immediately. Run it now?",
    logsEmpty: "No decision records for this day",
    logsTruncated: "Query limit reached — narrow the date range or raise the limit",
    noControllers: "No controllers yet — create one to start",
    condFlag: "Flag",
    flagHint: "A latch: any set condition → on; any reset condition → off (reset wins); otherwise it holds. Set/reset ports accept multiple wires; flags step once per evaluation cycle.",
    flagInitial: "Initial value is on (when nothing saved)",
    summaryFlagIdle: "no set/reset wired",
    portSet: "set",
    portReset: "reset",
    trgBadgeLegacy: "ALL",
    trgBadgeDead: "DEAD",
    trgBadgeDeadHint: "This directed trigger has no conditions wired: it evaluates nothing. Wire a condition on the canvas.",
    trgDeadConfirm: "An enabled directed trigger has no conditions wired (it will evaluate nothing). Save anyway?\nOK = save; Cancel = go back.",
    outputs: "Outputs",
    lastEval: "Last evaluation",
    never: "never",
    sensors: "Sensor pool",
    logging: "Decision log",
    enabled: "Enabled",
    controllerName: "Controller name",
    save: "Save",
    back: "Back to overview",
    trialRun: "Trial run",
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
    canvasHint: "⚡Trigger signal wires (amber) land on a condition's signal port to start evaluation; results come from the condition chains (blue) alone; click a node to edit it.",
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
    decision: "Decision",
    query: "Query",
    time: "Time",
    readouts: "Readings",
    logConditions: "Conditions",
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
    triggersTitle: "Triggers",
    addTrigger: "Add trigger",
    triggerState: "State",
    triggerTime: "Time",
    triggerSun: "Sun",
    triggerSunEvent: "Sun event",
    triggerStart: "HA start (also fires on reload)",
    triggerEntity: "Trigger entity (required)",
    triggerEntityHint: "Comma-separate multiple entities",
    triggerNEntities: "%d entities",
    triggerAttribute: "attribute",
    triggerFrom: "From state (optional)",
    triggerTo: "To state (optional)",
    triggerAt: "Daily at HH:MM",
    triggerEvery: "Every N seconds",
    triggerOffset: "Offset (seconds, may be negative)",
    condCooldown: "Flip cooldown",
    condCalendar: "Calendar",
    condNot: "NOT group",
    condDuration: "Hold duration",
    condDebounce: "Debounce",
    cooldownSeconds: "Cooldown seconds",
    calendarHours: "Upcoming hours",
    durationSeconds: "Hold seconds",
    debounceSeconds: "Quiet seconds",
    debounceEntity: "Quiet entity",
    wiredStart: "Start (wired)",
    wiredAbort: "Abort (optional, wired)",
    conditionSink3: "Signal port: trigger wires land here (plain conditions and logic groups; not duration/outputs; exclusive with the members port on groups)",
    trgRoutesLabel: "Covered conditions (from signal wires)",
    trgLegacyLabel: "Legacy trigger: full sweep (wire it up and save to go directed)",
    badConnection: "Wire rejected: amber signal wires go from a trigger to the signal port of a condition or logic group; duration and outputs have no signal port.",
    portSignal: "signal",
    portOn: "met → on",
    portOff: "met → off",
    portStart: "start",
    portAbort: "abort",
    portMembers: "members",
    portOut: "out",
    logicGroups: "Logic groups",
    logicGroupHint: "Coordinate condition logic (member wires) or trigger logic (signal wires, multiple allowed = any-trigger passes) — pick one, first wire wins; empty groups may take signals directly",
    trgGateMutexMembers: "This is a condition-logic group (members wired): its signal port is hidden — no signal wires",
    trgGateMutexSignal: "This is a trigger-logic group (signal wired): its members port is hidden — no member wires",
    passthrough: "trigger merge · pass-through",
    observeUnavailable: "Live status unavailable (observe endpoint failed) — check the log",
    observeUnavailableShort: "observe unavailable",
    weekdaysLabel: "Weekdays",
    byLabel: "By",
    enabledLabel: "Enabled",
    summaryAnd: " and ",
    summaryFrom: "from",
    summaryTo: "until",
    summarySunAfter: "onwards",
    summarySunBefore: "or earlier",
    summaryCooldown: "≥ since last flip",
    summaryDuration: "held for",
    summaryDebounce: "quiet ≥",
    summaryCalendarLead: "events within",
    summaryCalendarTail: "h",
    summaryMembers: " member(s)",
    summaryFor: " for ",
    loadFailed: "Failed to load",
    invalidBadge: "Invalid config",
    invalidStoredLead: "Stored config failed to load: ",
    invalidStoredTail: "Delete and recreate the controller.",
    triggerErrorBadge: "Trigger errors",
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
  cooldown: "condCooldown",
  calendar: "condCalendar",
  duration: "condDuration",
  debounce: "condDebounce",
  flag: "condFlag",
  and: "condAnd",
  or: "condOr",
  not: "condNot",
};

const TYPE_ICON = {
  numeric_state: "🔢",
  state: "🎚",
  time: "🕐",
  sun: "🌤",
  template: "ƒ",
  cooldown: "⏱",
  calendar: "📅",
  duration: "⏳",
  debounce: "🕯",
  flag: "🚩",
  and: "⊕",
  or: "⊗",
  not: "¬",
};

const TRIGGER_ICON = { state: "⚡", time: "🕐", sun: "🌤", homeassistant: "🏠" };
const TRIGGER_LABEL_KEY = { state: "triggerState", time: "triggerTime", sun: "triggerSun", homeassistant: "triggerStart" };
const isGroupType = (t) => t === "and" || t === "or" || t === "not";

function conditionSummary(cond, tr) {
  // `tr` is the panel's translation fn — node summaries follow hass.language
  const trk = tr || ((k) => k);
  let text = "";
  switch (cond.type) {
    case "numeric_state": {
      const parts = [];
      if (cond.above !== undefined && cond.above !== null) parts.push(`> ${cond.above}`);
      if (cond.below !== undefined && cond.below !== null) parts.push(`< ${cond.below}`);
      text = `${cond.entity_id} ${parts.join(trk("summaryAnd"))}`;
      break;
    }
    case "state":
      text = `${cond.entity_id} = ${Array.isArray(cond.state) ? cond.state.join("/") : cond.state}`;
      break;
    case "time": {
      text = [cond.after ? `${trk("summaryFrom")} ${cond.after}` : "", cond.before ? `${trk("summaryTo")} ${cond.before}` : ""].filter(Boolean).join(" ");
      break;
    }
    case "sun":
      text = [cond.after ? `${cond.after} ${trk("summarySunAfter")}` : "", cond.before ? `${cond.before} ${trk("summarySunBefore")}` : ""].filter(Boolean).join(" ");
      break;
    case "template":
      text = cond.value_template || "";
      break;
    case "cooldown":
      text = `${trk("summaryCooldown")} ${cond.seconds}s`;
      break;
    case "duration":
      text = `${trk("summaryDuration")} ${cond.seconds}s`;
      break;
    case "debounce":
      text = `${cond.entity_id || "?"} ${trk("summaryDebounce")} ${cond.seconds}s`;
      break;
    case "calendar":
      text = `${cond.entity_id} ${trk("summaryCalendarLead")} ${cond.hours}${trk("summaryCalendarTail")}`;
      break;
    case "flag": {
      const s = (cond.set_conditions || []).length;
      const r = (cond.reset_conditions || []).length;
      const parts = [];
      if (s) parts.push(`set×${s}`);
      if (r) parts.push(`reset×${r}`);
      text = `🚩 ${parts.join(" / ") || trk("summaryFlagIdle")}`;
      break;
    }
    default:
      text = `${(cond.conditions || []).length}${trk("summaryMembers")}`;
  }
  if (cond.for && (cond.for.hours || cond.for.minutes || cond.for.seconds)) {
    const f = cond.for;
    text += `${trk("summaryFor")}${String(f.hours).padStart(2, "0")}:${String(f.minutes).padStart(2, "0")}:${String(f.seconds).padStart(2, "0")}`;
  }
  if (cond.weekdays && cond.weekdays.length) {
    text += ` [${cond.weekdays.join(",")}]`;
  }
  if (cond.enabled === false) {
    text = `⏸ ${text}`;
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
    this._observeTimer = null;
    this._onHash = () => this._applyHash(true);
  }

  set hass(hass) {
    this._hass = hass;
    // keep every mounted native picker's entity list current
    this.shadowRoot?.querySelectorAll("ha-entity-picker").forEach((p) => {
      if (p.hass !== hass) p.hass = hass;
    });
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
    this._getEntityPickerClass(); // warm up the lazy-loaded native picker
    this._applyHash(false);
    this._boot();
    this._pollTimer = setInterval(() => this._poll(), 5000);
  }

  disconnectedCallback() {
    window.removeEventListener("hashchange", this._onHash);
    if (this._pollTimer) clearInterval(this._pollTimer);
    this._pollTimer = null;
    this._stopObserveLoopImpl();
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

  async _api(method, path, body, timeoutMs) {
    const hass = this._hass;
    if (!hass?.fetchWithAuth) throw new Error(" hass 未就绪");
    const controller = timeoutMs ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      const res = await hass.fetchWithAuth(`${API}${path}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller?.signal,
      });
      // the guard covers the body read too - a stalled body would otherwise
      // keep _observeBusy latched forever (WHA-F-140)
      // any parse failure propagates: the caller's catch distinguishes
      // transient (AbortError) from persistent episodes (WHA-F-210/211).
      // There is NO empty-body fallback: parse errors always throw, so
      // callers never see a fabricated {} (WHA-F-236)
      let data;
      try {
        data = await res.json();
      } catch (err) {
        // an aborted body read stays transient regardless of res.ok
        // (WHA-F-241) — wrapping it into a status error would make the
        // observe matcher treat a timeout as a persistent episode
        if (err?.name === "AbortError") throw err;
        // a non-JSON error body (proxy/框架层) must keep its HTTP status
        // for the observe transient matcher (WHA-F-222)
        if (!res.ok) {
          const oerr = new Error(`${res.status} ${res.statusText}`);
          oerr.status = res.status;
          throw oerr;
        }
        throw err;
      }
      if (!res.ok) {
        const err = new Error(data.error || `${res.status} ${res.statusText}`);
        err.status = res.status; // semantic matching (WHA-F-204)
        throw err;
      }
      return data;
    } finally {
      if (timer) clearTimeout(timer);
    }
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

  // True when this element is mounted inside the FumihaHub shell (the page
  // host lives in the hub's shadow root). Standalone mounts sit in the
  // document, so the root check discriminates cleanly.
  _inShell() {
    const root = this.getRootNode();
    return (
      root instanceof ShadowRoot &&
      root.host instanceof HTMLElement &&
      root.host.tagName === "FUMIHA-HUB-PANEL"
    );
  }

  _applyHash(rerender) {
    if (this._inShell()) {
      // The shell owns location.hash with its own single route (#pn=…) and
      // normalizes anything else away (WHA-F-253): our #/editor sub-route
      // would be rewritten and the view reset. In-shell navigation is
      // memory-state only (see _nav); deep links/refresh persistence of
      // sub-views remain a standalone-mode capability.
      return;
    }
    this._applyRoute(location.hash || "", rerender);
  }

  _applyRoute(hash, rerender) {
    const m = hash.match(/^#\/(editor|logs)\/?([A-Za-z0-9_]*)/);
    if (m) {
      this._view = m[1];
      if (m[2]) this._cid = m[2];
    } else {
      this._view = "overview";
    }
    if (this._view !== "editor") this._stopObserveLoopImpl();
    if (rerender) this._render();
  }

  _nav(hash) {
    if (this._inShell()) {
      // Never write location.hash in-shell (WHA-F-253) — switch the view
      // from the requested route string directly.
      this._applyRoute(String(hash), true);
      return;
    }
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
          <main class="wha-main"><div class="wha-card"><b>${esc(this.tr("loadFailed"))}</b><p class="wha-sub">${esc(this._error)}</p></div></main>`;
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
        if (c._invalid) {
          return `
          <div class="wha-card" data-cid="${esc(cid)}">
            <div class="wha-row">
              <h2 style="margin:0">${esc(cid)}</h2>
              <span class="badge off">${esc(this.tr("invalidBadge"))}</span>
              <span class="spacer" style="flex:1"></span>
              <button class="wha-btn danger" data-act="del">${esc(this.tr("delete"))}</button>
            </div>
            <p class="wha-sub" style="margin-top:8px">${esc(this.tr("invalidStoredLead"))}${esc(c.invalid_error || "")}${esc(this.tr("invalidStoredTail"))}</p>
          </div>`;
        }
        const busyAttr = this._toggleBusy === cid ? "disabled" : "";
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
              ${c._invalid ? `<span class="badge off">${esc(this.tr("invalidBadge"))}</span>` : `<span class="badge ${c.enabled ? "on" : "hold"}">${c.enabled ? esc(this.tr("enabled")) : "off"}</span>`}
              <span class="badge meta">${esc(cid)}</span>
              <span class="badge meta">${esc(this.tr("triggersTitle"))} ${c.triggers ? c.triggers.length : 0}${c.triggers && c.triggers.length === 0 ? " ⚠" : ""}</span>
              ${c.runtime?.trigger_errors ? `<span class="badge off">${esc(this.tr("triggerErrorBadge"))} ${c.runtime.trigger_errors}</span>` : ""}
              <span class="spacer" style="flex:1"></span>
              <button class="wha-btn" data-act="edit" ${busyAttr}>${esc(this.tr("edit"))}</button>
              <button class="wha-btn" data-act="logs" ${busyAttr}>${esc(this.tr("logs"))}</button>
              <button class="wha-btn" data-act="eval" ${busyAttr}>${esc(this.tr("evaluateNow"))}</button>
              <button class="wha-btn" data-act="toggle" ${busyAttr}>${c.enabled ? esc(this.tr("disable")) : esc(this.tr("enable"))}</button>
              <button class="wha-btn danger" data-act="del" ${busyAttr}>${esc(this.tr("delete"))}</button>
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
        // UX-M-03: 真实应用输出（与 FL-UX-03 同判据）——确认 + 忙碌态
        const cfg = this._controllerConfig(cid);
        this._openConfirm(
          this.tr("confirmTitle"),
          '"' + cfg.name + '"' + this.tr("evaluateConfirmBody"),
          async () => {
            if (this._toggleBusy === cid) return; // WHA-IMP-15: 入口守卫
            this._toggleBusy = cid; // 与 toggle 共用控制器级忙碌面
            try {
              await this._api("POST", `/controllers/${cid}/evaluate`);
              this.toast(this.tr("evalDone"));
              this._setData(await this._api("GET", "/config"));
            } catch (err) {
              this.toast(String(err.message || err), true);
            } finally {
              if (this._toggleBusy === cid) {
                this._toggleBusy = null;
              }
              // WHA-IMP-16: 用户可能已切到编辑器/日志——只有仍在总览才重渲染
              if (this._view === "overview") this._render();
            }
          }
        );
        return;
      }
      if (act === "toggle") {
        // WHA-UX-03+WHA-IMP-03: 忙碌态记在控制器级——5s 轮询重渲染会重建
        // 整卡 DOM，仅禁当次 DOM 会被抹掉，造成二次 PUT 翻转竞态。
        if (this._toggleBusy === cid) return; // WHA-IMP-15: 首渲染前的入口守卫
        this._toggleBusy = cid;
        try {
          const config = this._controllerConfig(cid);
          config.enabled = !config.enabled;
          await this._api("PUT", `/controllers/${cid}`, config);
          await this._sleepReload();
        } catch (err) {
          this.toast(String(err.message || err), true);
        } finally {
          if (this._toggleBusy === cid) {
            this._toggleBusy = null;
            // WHA-IMP-16: 仅总览视图重渲染（编辑器未保存修改/日志结果保护）
            if (this._view === "overview") this._render();
          }
        }
        return;
      }
      if (act === "del") {
        this._openConfirm(this.tr("confirmTitle"), this.tr("confirmDelete"), async () => {
          try {
            await this._api("DELETE", `/controllers/${cid}`);
            this.toast(this.tr("deleteOk"));
            this._setData(await this._api("GET", "/config"));
            // WHA-IMP-21: 与 IMP-20 同判据——仅总览视图收尾渲染
            if (this._view === "overview") this._render();
          } catch (err) {
            this.toast(String(err.message || err), true);
          }
        });
        return;
      }
    } catch (err) {
      this.toast(String(err.message || err), true);
    }
  }

  async _sleepReload() {
    this.toast(this.tr("saved"));
    await new Promise((r) => setTimeout(r, 1200));
    this._setData(await this._api("GET", "/config"));
    // WHA-IMP-20: 等待窗口内用户可能已切到编辑器（未保存修改会被以已保存
    // 配置重建）或日志（查询结果会被重置）——只在总览视图收尾渲染。
    if (this._view === "overview") this._render();
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
        logging_enabled: true,
        triggers: [],
        sensors: [],
        conditions: [],
        outputs: [],
      };
    } else {
      config = JSON.parse(JSON.stringify(this._controllerConfig(cid)));
      config.triggers = config.triggers || [];
    }
    const ed = {
      cid: isNew ? null : cid,
      isNew,
      controller: config,
      dirty: false,
      df: null,
      nodeToCond: new Map(),
      condToNode: new Map(),
      nodeToOut: new Map(),
      outToNode: new Map(),
      nodeToTrg: new Map(),
      portWireCount: new Map(), // "nodeId:portClass" -> wire count
      // (the observe cache resets below — verdicts are per-controller)
      // triggers that loaded WITHOUT routes keep their legacy
      // evaluate-everything semantics across canvas saves (WHA-F-070/071);
      // triggers created this session are NOT in this set
      legacyTrgIds: new Set((config.triggers || [])
        .filter((x) => x.routes === undefined)
        .map((x) => x.id)),
      selected: null,
      trial: null,
      deadTrgConfirmed: false,
    };
    this._editor = ed;

    main.innerHTML = `
      <div class="wha-editor">
        <div class="wha-editor-note">📱 ${esc(this.tr("mobileNote"))}</div>
        <div class="wha-editor-head">
          <label>${esc(this.tr("controllerName"))}<input class="wha-input" data-field="name" value="${esc(config.name)}" style="min-width:180px"></label>
          <label class="field-inline" style="justify-content:center"><input type="checkbox" data-field="enabled" ${config.enabled ? "checked" : ""}> ${esc(this.tr("enabled"))}</label>
          <label class="field-inline" style="justify-content:center"><input type="checkbox" data-field="logging_enabled" ${config.logging_enabled ? "checked" : ""}> ${esc(this.tr("logging"))}</label>
          <span class="spacer" style="flex:1"></span>
          <button class="wha-btn" data-act="delete-node">${esc(this.tr("deleteSelected"))}</button>
          <button class="wha-btn" data-act="trial" ${isNew ? "disabled" : ""}>${esc(this.tr("trialRun"))}</button>
          <button class="wha-btn primary" data-act="save">${esc(this.tr("save"))}</button>
          <button class="wha-btn" data-act="back">${esc(this.tr("back"))}</button>
        </div>
        <details class="wha-card wha-edit-only" style="flex:none">
          <summary>${esc(this.tr("sensors"))} (${config.sensors.length})</summary>
          <div data-sensors></div>
        </details>
        <div class="wha-editor-body">
          <div class="wha-palette">
            <h3>${esc(this.tr("addTrigger"))}</h3>
            ${["state", "time", "sun", "homeassistant"]
              .map((tp) => `<button class="wha-btn" data-add-trg="${tp}">${TRIGGER_ICON[tp]} ${esc(this.tr(TRIGGER_LABEL_KEY[tp]))}</button>`)
              .join("")}
            <h3>${esc(this.tr("addCondition"))}</h3>
            ${["numeric_state", "state", "time", "sun", "template", "cooldown", "calendar", "duration", "debounce", "flag"]
              .map((tp) => `<button class="wha-btn" data-add-cond="${tp}">${TYPE_ICON[tp]} ${esc(this.tr(TYPE_LABEL_KEY[tp]))}</button>`)
              .join("")}
            <h3>${esc(this.tr("logicGroups"))}</h3>
            <p class="wha-sub" style="margin:0 0 6px">${esc(this.tr("logicGroupHint"))}</p>
            ${["and", "or", "not"]
              .map((tp) => `<button class="wha-btn" data-add-cond="${tp}">${TYPE_ICON[tp]} ${esc(this.tr(TYPE_LABEL_KEY[tp]))}</button>`)
              .join("")}
            <h3>${esc(this.tr("addOutput"))}</h3>
            <button class="wha-btn" data-add-out="switch">⏻ ${esc(this.tr("outSwitch"))}</button>
            <button class="wha-btn" data-add-out="binary_sensor">◉ ${esc(this.tr("outBinary"))}</button>
            <p class="wha-sub" style="margin-top:10px">${esc(this.tr("paletteHint"))}</p>
            <p class="wha-sub">${esc(this.tr("conditionSink1"))}<br>${esc(this.tr("conditionSink2"))}<br>${esc(this.tr("conditionSink3"))}</p>
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
        else this._editor.controller[f] = input.value;
        this._editor.dirty = true;
      });
    });

    // palette
    main.querySelectorAll("[data-add-trg]").forEach((btn) =>
      btn.addEventListener("click", () => {
        if (!this._editor?.df) return; // vendor script not loaded yet (WHA-F-244)
        this._addTriggerNode(btn.dataset.addTrg);
      })
    );
    main.querySelectorAll("[data-add-cond]").forEach((btn) =>
      btn.addEventListener("click", () => {
        if (!this._editor?.df) return; // vendor script not loaded yet (WHA-F-244)
        this._addConditionNode(btn.dataset.addCond);
      })
    );
    main.querySelectorAll("[data-add-out]").forEach((btn) =>
      btn.addEventListener("click", () => {
        if (!this._editor?.df) return; // vendor script not loaded yet (WHA-F-244)
        this._addOutputNode(btn.dataset.addOut);
      })
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
    if (this._editor !== ed || !main.isConnected) {
      return; // user navigated away while the vendor script loaded
    }
    this._initCanvas(main.querySelector("#wha-drawflow"));
    this._lastObserve = null; // verdicts are per-controller (WHA-F-145)
    this._lastObservedIds = null; // mirror reset (WHA-F-248)
    this._startObserveLoop();
  }

  _startObserveLoop() {
    // live condition status: poll the read-only observe endpoint while the
    // editor is open and the tab visible
    this._stopObserveLoopImpl();
    this._observeWarned = false; // per-editor session (WHA-F-176)
    this._observeHealthy = null;
    const tick = async () => {
      if (this._observeBusy) return; // previous round still in flight
      if (document.hidden || !this.isConnected || this._view !== "editor") {
        return;
      }
      const cid = this._editor?.cid;
      if (!cid) return;
      if (this._data?.controllers?.[cid]?.enabled === false) {
        // disabled controller: observe would 409 forever — remove the stale
        // status lines entirely instead of borrowing the failure sentinel
        // (a disabled controller is not "observe failing", WHA-F-228)
        this._lastObserve = null;
        this._lastObservedIds = null;
        this._observeHealthy = null;
        this._observeWarned = false; // reset the episode so re-enabling
        // doesn't leave a persistently-failing observe permanently silent
        this._clearStaleVerdicts();
        this._editor?.df?.container
          ?.querySelectorAll("[data-observe]")
          .forEach((el) => el.remove());
        // trial artifacts too, symmetric with the success path (WHA-F-232)
        if (this._editor?.trial) {
          this._editor.trial = null;
          this.shadowRoot
            ?.querySelector("[data-inspector] details.wha-json")
            ?.remove();
          for (const nodeId of this._editor.outToNode.values()) {
            const badge = this._editor.df?.container?.querySelector(
              `#node-${nodeId} [data-badge]`
            );
            if (badge) badge.style.display = "none";
          }
        }
        return;
      }
      const ed = this._editor;
      this._observeBusy = true;
      try {
        const r = await this._api("GET", `/controllers/${cid}/observe`, undefined, 8000);
        if (this._editor !== ed || !ed.df?.container) {
          return; // user switched editors mid-await (WHA-F-184)
        }

        this._observeWarned = false;
        if (ed.trial) {
          ed.trial = null; // fresh round supersedes trial (WHA-F-182)
          // drop the stale trial artifacts: the details box AND the output
          // decision badges (WHA-F-189 — the other half of the mixed state)
          this.shadowRoot
            ?.querySelector("[data-inspector] details.wha-json")
            ?.remove();
          for (const nodeId of ed.outToNode.values()) {
            const badge = ed.df.container
              ?.querySelector(`#node-${nodeId} [data-badge]`);
            if (badge) badge.style.display = "none";
          }
        }
        this._applyObserve(r);
      } catch (err) {
        if (this._editor !== ed) return; // stale round on a foreign view (WHA-F-196)
        if (ed.trial) return; // trial coloring wins (WHA-F-217)
        // transient: no status (browser-level fetch rejection, e.g. HA
        // restarting — WHA-F-239), 409 reload/disabled, 503 during reload,
        // or a slow-observe timeout. Only a real 5xx from observe itself
        // counts as a failure episode.
        const status = err?.status;
        if (
          status === undefined ||
          status === 409 ||
          status === 503 ||
          status < 500 ||
          err?.name === "AbortError"
        ) {
          return;
        }
        // persistent failures (500 etc) must not be fully silent
        if (!this._observeWarned) {
          this._observeWarned = true;
          console.debug("[wha] observe unavailable:", String(err.message || err));
          // mark the live status as stale instead of leaving old verdicts
          // looking current (WHA-F-191); also drop the cached response so
          // redraws cannot replay it (WHA-F-195)
          this._lastObserve = null;
          if (ed.df?.container) {
            this._observeHealthy = false; // redraws must keep the ⚠ mark (WHA-F-224)
            this._clearStaleVerdicts();
            this._stampObserveUnavailable(ed.df.container);
            // _lastObserve is cleared unconditionally at :1046 (before the
            // container check); _lastObservedIds is KEPT for the whole
            // episode so redraws re-stamp with the same filter (WHA-F-250)
            // one visible hint per failure episode (WHA-F-193/198)
            this.toast(this.tr("observeUnavailable"), true);
          }
        }
      } finally {
        this._observeBusy = false;
      }
    };
    tick();
    this._observeTimer = setInterval(tick, 5000);
  }

  _stopObserveLoopImpl() {
    if (this._observeTimer) {
      clearInterval(this._observeTimer);
      this._observeTimer = null;
    }
  }

  _clearStaleVerdicts() {
    this._editor?.df?.container
      ?.querySelectorAll(".wha-node.met, .wha-node.unmet")
      .forEach((el) => el.classList.remove("met", "unmet"));
  }

  _stampObserveUnavailable(container) {
    // ensure-then-write: redraws wipe [data-nbody] textContent and take the
    // .wha-observe line with them, so every redraw point during a failure
    // episode must CREATE the line when missing, not just restyle (WHA-F-226).
    // Nodes whose condition had a verdict in the last successful observe get
    // the ⚠, mirroring the success path's coverage (WHA-F-243). Cold start
    // (no successful observe yet, _lastObservedIds===null) stamps ALL nodes:
    // the whole live-status feature is unavailable, which is the honest
    // signal (WHA-F-252).
    const covered = this._lastObservedIds || null;
    for (const [condId, nodeId] of this._editor?.condToNode || []) {
      const node = container.querySelector(`#node-${nodeId}`);
      if (!node) continue;
      let line = node.querySelector(".wha-observe");
      if (covered && !covered.has(condId)) {
        // was never observed (not chain-reachable): no status line at all,
        // mirroring the success path (WHA-F-243)
        line?.remove();
        continue;
      }
      if (!line) {
        line = document.createElement("div");
        line.className = "wha-observe";
        line.setAttribute("data-observe", "");
        node.querySelector(".wha-node-body")?.appendChild(line);
      }
      line.textContent = `⚠ ${this.tr("observeUnavailableShort")}`;
      line.classList.remove("ok", "bad");
    }
  }

  _refreshPassthroughBadges() {
    // pass-through badges are PURELY topological (trigger coverage + empty
    // group) — they must survive observe failures and trials (WHA-F-229)
    const ed = this._editor;
    for (const [condId, nodeId] of ed.condToNode) {
      const cond = ed.controller.conditions.find((c) => c.id === condId);
      if (!cond || !isGroupType(cond.type)) continue;
      const covered = (ed.controller.triggers || []).some((trg) =>
        (trg.routes?.conditions || []).includes(condId)
      );
      const empty = !(cond.conditions || []).length;
      const el = ed.df.container?.querySelector(`#node-${nodeId}`);
      if (!el) continue;
      let badge = el.querySelector("[data-passthrough]");
      if (covered && empty) {
        if (!badge) {
          badge = document.createElement("div");
          badge.className = "wha-passthrough";
          badge.setAttribute("data-passthrough", "");
          el.querySelector(".wha-node-body")?.appendChild(badge);
        }
        badge.textContent = this.tr("passthrough");
      } else if (badge) {
        badge.remove();
      }
    }
  }

  _applyObserve(r) {
    // color condition nodes by their live verdict and append a status line
    if (this._editor?.trial) return; // trial coloring wins until next tick (WHA-F-213)
    this._observeHealthy = true;
    this._lastObserve = r; // body redraws re-apply this (status line survives)
    // snapshot the observed condition-id set for the failure path's ⚠ filter
    // (WHA-F-243: failure stamps must mirror the success path's coverage)
    this._lastObservedIds = new Set(Object.keys(r.conditions || {}));
    const ed = this._editor;
    if (!ed?.df?.container) return;
    for (const [condId, nodeId] of ed.condToNode) {
      const met = r.conditions?.[condId];
      const el = ed.df.container.querySelector(`#node-${nodeId}`);
      if (!el) continue;
      if (met === undefined) {
        // no longer on any output chain: clear the stale verdict (WHA-F-180)
        el.classList.remove("met", "unmet");
        el.querySelector("[data-observe]")?.remove();
        continue;
      }
      el.classList.toggle("met", met === true);
      el.classList.toggle("unmet", met === false);
      let status = el.querySelector("[data-observe]");
      if (!status) {
        status = document.createElement("div");
        status.className = "wha-observe";
        status.setAttribute("data-observe", "");
        el.querySelector(".wha-node-body")?.appendChild(status);
      }
      // entity id from the SAVED config snapshot (F-199: the editor object
      // may hold unsaved edits that would mismatch the observed verdict);
      // the value prefers the observe readings and falls back to hass.states
      // for entities outside the sensor pool (WHA-F-200)
      const savedCond = this._data?.controllers?.[ed.cid]?.conditions?.find(
        (c) => c.id === condId
      );
      const eid = savedCond?.entity_id;
      let st = eid ? r.readings?.[eid] : undefined;
      if (st === undefined && eid) {
        st = this._hass?.states?.[eid]?.state;
      }
      const live =
        eid && st !== undefined && st !== null
          ? ` · ${String(st).slice(0, 24)}`
          : "";
      status.textContent = `${met ? "✓" : "✗"}${live}`;
      status.classList.toggle("ok", met === true);
      status.classList.toggle("bad", met === false);
    }
    this._refreshPassthroughBadges();
  }

  static _PORT_LABELS = {
    trigger: { output_1: "portSignal" },
    output: { input_1: "portOn", input_2: "portOff" },
    duration: { input_1: "portStart", input_2: "portAbort", output_1: "portOut" },
    flag: { input_1: "portSet", input_2: "portReset", output_1: "portOut" },
    group: { input_1: "portMembers", input_3: "portSignal", output_1: "portOut" },
    leaf: { input_3: "portSignal", output_1: "portOut" },
  };

  _labelNodePorts(nodeId, kind) {
    // Blender-style socket labels: a small tag next to every port dot, so
    // "which dot is which" never depends on trial and error.
    const el = this._editor?.df?.container?.querySelector(`#node-${nodeId}`);
    if (!el) {
      console.debug("[wha] port labels skipped: node DOM not found", nodeId);
      return;
    }
    const spec = ScannerPanel._PORT_LABELS[kind];
    if (!spec) {
      console.debug("[wha] port labels skipped: unregistered kind", kind);
      return;
    }
    for (const [port, key] of Object.entries(spec)) {
      const portEl = el.querySelector(`.${port}`);
      if (!portEl || portEl.querySelector(".wha-port-label")) continue;
      const span = document.createElement("span");
      span.className = "wha-port-label";
      span.textContent = this.tr(key);
      portEl.appendChild(span);
    }
  }

  _rebuildPortWireCount() {
    const ed = this._editor;
    if (!ed.df) return;
    ed.portWireCount = new Map();
    const data = ed.df.export()?.drawflow?.Home?.data || {};
    for (const node of Object.values(data)) {
      const nid = Number(node?.id);
      if (!Number.isFinite(nid)) continue;
      for (const [port, def] of Object.entries(node.inputs || {})) {
        for (const c of def?.connections || []) {
          this._bumpPortCount(nid, port, 1);
          void c;
        }
      }
      for (const [port, def] of Object.entries(node.outputs || {})) {
        for (const c of def?.connections || []) {
          this._bumpPortCount(nid, port, 1);
          void c;
        }
      }
    }
    for (const [nid] of ed.nodeToCond) {
      this._updateGroupPortState(nid);
    }
  }

  _bumpPortCount(nodeId, portClass, delta) {
    const ed = this._editor;
    if (!ed.portWireCount) ed.portWireCount = new Map();
    const key = `${nodeId}:${portClass}`;
    const next = (ed.portWireCount.get(key) || 0) + delta;
    if (next > 0) ed.portWireCount.set(key, next);
    else ed.portWireCount.delete(key);
  }

  _groupExclusiveWired(nodeId, portClass) {
    // true when the OPPOSITE port of a group node already carries wires
    const opposite = portClass === "input_3" ? "input_1" : "input_3";
    const ed = this._editor;
    return (ed.portWireCount?.get(`${nodeId}:${opposite}`) || 0) > 0;
  }

  _updateGroupPortState(nodeId) {
    // Logic groups: strict symmetric mutual exclusion (0.7.3). Wiring the
    // members port = condition-logic mode (signal port hides); wiring the
    // signal port = trigger-logic mode (members port hides - trigger mode
    // groups carry no member wires, so display:none is endpoint-safe).
    const ed = this._editor;
    const condId = ed?.nodeToCond?.get(nodeId);
    if (!condId) return;
    const cond = ed.controller.conditions.find((c) => c.id === condId);
    if (!cond || !isGroupType(cond.type)) return;
    const el = ed.df?.container?.querySelector(`#node-${nodeId}`);
    if (!el) return;
    const signal = (ed.portWireCount?.get(`${nodeId}:input_3`) || 0) > 0;
    const members = (ed.portWireCount?.get(`${nodeId}:input_1`) || 0) > 0;
    // deterministic priority when an API-constructed store has both wired:
    // members win (condition-logic), the signal port stays hidden
    el.classList.toggle("gate-has-members", members);
    el.classList.toggle("gate-has-signal", signal && !members);
  }

  _rejectReason(e) {
    const ed = this._editor;
    const condId = ed?.nodeToCond?.get(Number(e.input_id));
    if (!condId) return null;
    const cond = ed.controller.conditions.find((c) => c.id === condId);
    if (!cond || !isGroupType(cond.type)) return null;
    // Judge the group's PRE-EXISTING wiring from the live drawflow data,
    // excluding the attempted wire itself — immune to vendor rollback
    // timing (WHA-F-144/148)
    const data = ed.df?.export()?.drawflow?.Home?.data || {};
    const countOther = (portClass) =>
      // drawflow data keys are the BARE node id — "node-<id>" exists only on
      // DOM ids (the exact WHA-F-014 trap, do not repeat it here)
      (data[String(Number(e.input_id))]?.inputs?.[portClass]?.connections || [])
        .filter(
          (c) =>
            !(
              Number(c.node) === Number(e.output_id) &&
              e.output_class === "output_1"
            )
        )
        .length;
    const membersWired = countOther("input_1") > 0;
    const signalWired = countOther("input_3") > 0;
    if (ed.nodeToTrg.has(Number(e.output_id)) && membersWired) {
      // trigger wire onto a condition-logic group
      return this.tr("trgGateMutexMembers");
    }
    if (!ed.nodeToTrg.has(Number(e.output_id)) && signalWired) {
      // condition wire onto a trigger-logic group
      return this.tr("trgGateMutexSignal");
    }
    return null;
  }

  async _getEntityPickerClass() {
    // Resolve HA's native entity picker. It lives in a lazily-loaded
    // frontend chunk, so loading card helpers is the community-standard
    // way to pull it in. Only a POSITIVE resolution is cached: a failed
    // probe (helpers not ready, 4s race lost) clears itself so the next
    // upgrade pass retries instead of silently staying on datalist for the
    // whole session (WHA-F-039). Concurrent callers share one probe.
    if (this._epickTag) return this._epickTag;
    if (!this._epickProbe) {
      this._epickProbe = this._probeEntityPicker();
    }
    const tag = await this._epickProbe;
    if (tag) {
      this._epickTag = tag;
      // self-heal: the picker may have arrived long after this view
      // rendered - upgrade whatever is on screen without waiting for a
      // re-render (WHA-F-043)
      this._upgradeEntityPickers(this.shadowRoot);
    } else {
      this._epickProbe = null;
      if (!this._epickWarned) {
        this._epickWarned = true;
        console.debug("[wha] native ha-entity-picker unavailable; using datalist fallback");
      }
    }
    return this._epickTag || null;
  }

  async _probeEntityPicker() {
    if (customElements.get("ha-entity-picker")) return "ha-entity-picker";
    try {
      if (typeof window.loadCardHelpers === "function") {
        const helpers = await window.loadCardHelpers();
        try { helpers.createEntityPicker?.(); } catch { /* optional */ }
        await new Promise((resolve) => {
          const timer = setTimeout(resolve, 4000);
          customElements.whenDefined("ha-entity-picker").then(() => {
            clearTimeout(timer);
            resolve();
          });
        });
      }
    } catch { /* helpers unavailable - datalist fallback stays */ }
    return customElements.get("ha-entity-picker") ? "ha-entity-picker" : null;
  }

  async _upgradeEntityPickers(root) {
    // Swap every input carrying data-epick for a native ha-entity-picker.
    // The picker's value-changed is bridged back onto the original input
    // (value + change event), so all existing change-to-model wiring keeps
    // working unchanged. Fallback: inputs stay as-is (datalist).
    if (!root) return;
    const tag = await this._getEntityPickerClass();
    if (!tag) return;
    let replaced = 0;
    root.querySelectorAll("input[data-epick]").forEach((input) => {
      if (!input.isConnected) return;
      const picker = document.createElement(tag);
      picker.hass = this._hass;
      picker.value = input.value || "";
      picker.allowCustomEntity = true;
      picker.style.width = "100%";
      const domain = input.dataset.epick;
      if (domain) {
        picker.includeDomains = [domain];
      }
      picker.addEventListener("value-changed", (ev) => {
        const v = (ev.detail && ev.detail.value) || "";
        if (input.value === v) return;
        input.value = v;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
      input.replaceWith(picker);
      replaced += 1;
    });
    if (replaced) {
      root.querySelectorAll("datalist").forEach((d) => d.remove());
    }
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
              <td><input class="wha-input" list="wha-entities" data-si="${i}" data-sk="entity_id" data-epick value="${esc(s.entity_id)}" style="width:100%"></td>
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
    this._upgradeEntityPickers(container);
  }

  _triggerSummary(t) {
    let detail = "";
    if (t.type === "state") {
      detail = Array.isArray(t.entity_id)
        ? this.tr("triggerNEntities").replace("%d", String(t.entity_id.length))
        : t.entity_id || this.tr("triggerEntity");
      if (t.attribute) detail += ` · ${t.attribute}`;
    } else if (t.type === "time") {
      detail = t.at
        ? `${this.tr("triggerAt")} ${t.at}`
        : t.every_seconds >= 10
          ? `${this.tr("triggerEvery")} ${t.every_seconds}`
          : this.tr("triggerEvery");
    } else if (t.type === "sun") {
      detail = `${t.event || "sunrise"} ${t.offset ? (t.offset > 0 ? "+" : "") + t.offset + "s" : ""}`;
    } else {
      detail = "start";
    }
    return detail;
  }

  _addTriggerNode(type) {
    const ed = this._editor;
    // 0.10.0: legacy full-sweep (routes absent) is rejected by the schema,
    // so panel-created triggers are born directed-empty — the red badge and
    // the save confirm point at the missing wire until one is drawn
    // (explicit causality; supersedes the 0.9.0 M4 born-legacy choice).
    const t = {
      id: `trg_${uidHex()}`,
      type,
      label: "",
      enabled: true,
      routes: { conditions: [] },
    };
    if (type === "time") t.every_seconds = 300;
    if (type === "sun") t.event = "sunrise";
    if (type === "state") t.entity_id = "";
    ed.controller.triggers = ed.controller.triggers || [];
    ed.controller.triggers.push(t);
    const count = ed.controller.triggers.length;
    const nodeId = this._dfAddTriggerNode(t, 20, 20 + (count - 1) * 120);
    this._selectNode(nodeId);
    ed.dirty = true;
  }

  _dfAddTriggerNode(t, x, y) {
    const ed = this._editor;
    const nodeId = ed.df.addNode(
      "trigger_" + t.type,
      0,
      1,
      x,
      y,
      `wha-node trg-node trg-${t.type}${t.enabled === false ? " trg-off" : ""}`,
      { trgId: t.id },
      this._triggerNodeHtml(t)
    );
    ed.nodeToTrg.set(nodeId, t.id);
    this._labelNodePorts(nodeId, "trigger");
    return nodeId;
  }

  _triggerNodeHtml(t) {
    return `
      <div class="wha-node-body-wrap">
        <div class="wha-node-head">
          <span>${TRIGGER_ICON[t.type] || "?"}</span>
          <span data-nhead>${esc(this.tr(TRIGGER_LABEL_KEY[t.type] || t.type))}</span>
          <span class="wha-node-tag">trigger</span>
        </div>
        <div class="wha-node-body" data-nbody>${esc(this._triggerSummary(t))}</div>
      </div>`;
  }

  _refreshTriggerNode(nodeId) {
    const ed = this._editor;
    const trgId = ed.nodeToTrg.get(nodeId);
    if (trgId === undefined) return;
    const el = ed.df.container ? ed.df.container.querySelector(`#node-${nodeId}`) : null;
    const t = (ed.controller.triggers || []).find((x) => x.id === trgId);
    if (!el || !t) return;
    const head = el.querySelector("[data-nhead]");
    const body = el.querySelector("[data-nbody]");
    if (head) head.textContent = this.tr(TRIGGER_LABEL_KEY[t.type] || t.type);
    if (body) body.textContent = this._triggerSummary(t);
    el.classList.toggle("trg-off", t.enabled === false);
    this._refreshTriggerBadges();
  }

  _refreshTriggerBadges() {
    // M4 (0.9.0): three trigger modes must be visible on the node itself —
    // legacy (routes absent = evaluate-everything, amber), directed-n, and
    // directed-empty ("dead": wakes nothing, red). Until now only the
    // inspector hinted at the mode, and panel-created triggers defaulted to
    // the dead state invisibly.
    const ed = this._editor;
    if (!ed.df?.container) return;
    for (const [nid, tid] of ed.nodeToTrg) {
      const t = (ed.controller.triggers || []).find((x) => x.id === tid);
      const el = ed.df.container.querySelector(`#node-${nid}`);
      if (!el || !t) continue;
      const legacy = ed.legacyTrgIds.has(t.id);
      const dead =
        !legacy && t.routes !== undefined && !(t.routes?.conditions || []).length;
      el.classList.toggle("trg-legacy", legacy);
      el.classList.toggle("trg-dead", dead);
      let badge = el.querySelector(".trg-mode-badge");
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "trg-mode-badge";
        el.querySelector(".wha-node-head")?.appendChild(badge);
      }
      if (legacy) {
        badge.textContent = this.tr("trgBadgeLegacy");
        badge.title = this.tr("trgLegacyLabel");
      } else if (dead) {
        badge.textContent = this.tr("trgBadgeDead");
        badge.title = this.tr("trgBadgeDeadHint");
      } else {
        badge.textContent = `→${(t.routes?.conditions || []).length}`;
        badge.title = this.tr("trgRoutesLabel");
      }
    }
  }

  _triggerInspectorHtml(t) {
    const ed = this._editor;
    // numeric limits mirror schema.py (EVERY_SECONDS 10..86400, SUN_OFFSET ±86400)
    const NUM_LIMITS = {
      every_seconds: ' min="10" max="86400"',
      offset: ' min="-86400" max="86400"',
    };
    const fi = (key, label, placeholder, value, type = "text") =>
      `<label class="field"><span>${esc(label)}</span><input class="wha-input" type="${type}"${NUM_LIMITS[key] || ""} data-trgsk="${key}" placeholder="${esc(placeholder)}" value="${esc(value ?? "")}"></label>`;
    const ents = Object.keys(this._hass?.states || {}).sort();
    let fields = "";
    if (t.type === "state") {
      const entVal = Array.isArray(t.entity_id)
        ? t.entity_id.join(", ")
        : t.entity_id ?? "";
      fields = `
        <div class="field"><span>${esc(this.tr("triggerEntity"))}</span>
          <input class="wha-input" list="wha-trg-ents-insp" data-trgsk="entity_id" data-epick value="${esc(entVal)}">
          <datalist id="wha-trg-ents-insp">${ents.map((e) => `<option value="${esc(e)}">`).join("")}</datalist>
          <p class="wha-sub">${esc(this.tr("triggerEntityHint"))}</p>
        </div>
        ${fi("attribute", this.tr("triggerAttribute"), "", t.attribute ?? "")}
        ${fi("from", this.tr("triggerFrom"), "", t.from ?? "")}
        ${fi("to", this.tr("triggerTo"), "", t.to ?? "")}`;
    } else if (t.type === "time") {
      fields = `
        ${fi("at", this.tr("triggerAt"), "", t.at || "", "time")}
        ${fi("every_seconds", this.tr("triggerEvery"), "", t.every_seconds ?? "", "number")}`;
    } else if (t.type === "sun") {
      fields = `
        <label class="field"><span>${esc(this.tr("triggerSunEvent"))}</span>
          <select class="wha-input" data-trgsk="event">
            <option value="sunrise" ${t.event !== "sunset" ? "selected" : ""}>sunrise</option>
            <option value="sunset" ${t.event === "sunset" ? "selected" : ""}>sunset</option>
          </select></label>
        ${fi("offset", this.tr("triggerOffset"), "", t.offset ?? "", "number")}`;
    }
    return `
      <label class="field field-inline"><input type="checkbox" data-trgsk="enabled" ${t.enabled !== false ? "checked" : ""}> ${esc(this.tr("enabledLabel"))}</label>
      ${fields}
      ${ed.legacyTrgIds.has(t.id)
        ? `<p class="wha-sub">${esc(this.tr("trgLegacyLabel"))}</p>`
        : t.routes !== undefined && !(t.routes?.conditions || []).length
        ? `<p class="wha-sub" style="color:#c62828">⚠ ${esc(this.tr("trgBadgeDeadHint"))}</p>`
        : `<p class="wha-sub">${esc(this.tr("trgRoutesLabel"))}: ${(t.routes?.conditions || []).length}</p>`}
      <p class="wha-sub">${esc(t.id)}</p>`;
  }

  /* ----- drawflow wiring ----- */

  _initCanvas(container) {
    const ed = this._editor;
    const df = new window.Drawflow(container);
    df.start();
    ed.df = df;
    ed.importing = true;
    df.on("nodeSelected", (nodeId) => this._selectNode(Number(nodeId)));
    df.on("connectionCreated", (e) => {
      this._bumpPortCount(Number(e.output_id), e.output_class, 1);
      this._bumpPortCount(Number(e.input_id), e.input_class, 1);
      this._updateGroupPortState(Number(e.input_id));
      this._updateGroupPortState(Number(e.output_id));
      if (ed.importing) return;
      if (!this._connectionAllowed(e)) {
        // removeSingleConnection re-fires connectionRemoved, which rolls
        // the counters back
        try {
          df.removeSingleConnection(
            String(e.output_id), String(e.input_id), e.output_class, e.input_class
          );
        } catch {
          /* already refused by the canvas */
        }
        this.toast(this._rejectReason(e) || this.tr("badConnection"), true);
        return;
      }
      ed.dirty = true;
      this._styleConnections();
      this._syncFromWires();
    });
    df.on("connectionRemoved", (e) => {
      this._bumpPortCount(Number(e.output_id), e.output_class, -1);
      this._bumpPortCount(Number(e.input_id), e.input_class, -1);
      this._updateGroupPortState(Number(e.input_id));
      this._updateGroupPortState(Number(e.output_id));
      if (!ed.importing) {
        ed.dirty = true;
        this._styleConnections();
        this._syncFromWires();
      }
    });
    df.on("nodeRemoved", (nodeId) => {
      const n = Number(nodeId);
      const trgId = ed.nodeToTrg.get(n);
      if (trgId !== undefined && trgId !== null) {
        ed.nodeToTrg.delete(n);
        ed.controller.triggers = (ed.controller.triggers || []).filter((t) => t.id !== trgId);
      }
      const condId = ed.nodeToCond.get(n);
      if (condId) {
        ed.nodeToCond.delete(n);
        ed.condToNode.delete(condId);
        ed.controller.conditions = ed.controller.conditions.filter((c) => c.id !== condId);
        // cascade: drop dangling references from groups, outputs and routes
        for (const c of ed.controller.conditions) {
          if (c.conditions) c.conditions = c.conditions.filter((m) => m !== condId);
          if (c.start === condId) delete c.start;
          if (c.abort === condId) delete c.abort;
        }
        for (const o of ed.controller.outputs) {
          o.on_conditions = o.on_conditions.filter((m) => m !== condId);
          o.off_conditions = o.off_conditions.filter((m) => m !== condId);
        }
        for (const t of ed.controller.triggers || []) {
          if (!t.routes) continue;
          t.routes.conditions = (t.routes.conditions || []).filter((m) => m !== condId);
        }
      }
      const outId = ed.nodeToOut.get(n);
      if (outId) {
        ed.nodeToOut.delete(n);
        ed.outToNode.delete(outId);
        ed.controller.outputs = ed.controller.outputs.filter((o) => o.entity_id !== outId);
      }
      // vendor may not per-wire dispatch connectionRemoved on node removal
      // — rebuild the counters from the drawflow data (WHA-F-087)
      this._rebuildPortWireCount();
      this._syncFromWires();
      ed.dirty = true;
    });

    // import existing model
    // triggers live on the leftmost column, each with one signal output
    const trgNodeById = new Map();
    (ed.controller.triggers || []).forEach((t, i) => {
      const nid = this._dfAddTriggerNode(t, 20, 20 + i * 120);
      trgNodeById.set(t.id, nid);
    });
    const conds = ed.controller.conditions;
    conds.forEach((cond, i) => {
      this._dfAddCondNode(cond, 20 + i * 120);
    });
    ed.controller.outputs.forEach((out, i) => {
      this._dfAddOutNode(out, this._outX(), 30 + i * 140);
    });
    // gate wires: group members, output chains, duration start/abort
    for (const cond of conds) {
      if (!isGroupType(cond.type)) continue;
      const gid = ed.condToNode.get(cond.id);
      for (const m of cond.conditions || []) {
        const mid = ed.condToNode.get(m);
        if (mid && gid) df.addConnection(String(mid), String(gid), "output_1", "input_1");
      }
    }
    for (const cond of conds) {
      if (cond.type !== "duration") continue;
      const did = ed.condToNode.get(cond.id);
      const sid = cond.start ? ed.condToNode.get(cond.start) : null;
      if (did && sid) df.addConnection(String(sid), String(did), "output_1", "input_1");
      const aid = cond.abort ? ed.condToNode.get(cond.abort) : null;
      if (did && aid) df.addConnection(String(aid), String(did), "output_1", "input_2");
    }
    for (const cond of conds) {
      if (cond.type !== "flag") continue;
      const fid = ed.condToNode.get(cond.id);
      for (const [key, port] of [["set_conditions", "input_1"], ["reset_conditions", "input_2"]]) {
        for (const m of cond[key] || []) {
          const mid = ed.condToNode.get(m);
          if (mid && fid) df.addConnection(String(mid), String(fid), "output_1", port);
        }
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
    // signal wires: trigger routes → condition signal ports. Coverage is
    // topological (0.7.3 F-155 resolution, superseding F-135): disabled
    // triggers keep drawing their wires — the trg-off class dims the node —
    // so the canvas, schema and engine all agree on what is wired.
    for (const trg of ed.controller.triggers || []) {
      const srcNode = trgNodeById.get(trg.id);
      if (srcNode === undefined) continue;
      for (const cid of trg.routes?.conditions || []) {
        const dst = ed.condToNode.get(cid);
        if (dst === undefined) continue;
        const dstCond = ed.controller.conditions.find((c) => c.id === cid);
        if (dstCond?.type === "duration" || dstCond?.type === "flag") continue; // neither has input_3
        df.addConnection(String(srcNode), String(dst), "output_1", "input_3");
      }
    }
    ed.importing = false;
    // rebuild counters from the drawflow data instead of trusting vendor
    // connectionCreated dispatch during import (R12 待确认项的消解)
    this._rebuildPortWireCount(); // also refreshes every group's port state
    this._refreshPassthroughBadges();
    this._refreshTriggerBadges();
    this._styleConnections();
  }

  _syncFromWires() {
    // keep trigger routes AND group membership in step with the wires while
    // editing, so inspector counts are live rather than save-lagged
    const ed = this._editor;
    if (!ed.df || ed.importing) return;
    const data = ed.df.export()?.drawflow?.Home?.data || {};
    for (const trg of ed.controller.triggers || []) {
      let srcNode = null;
      for (const [nid, tid] of ed.nodeToTrg) {
        if (tid === trg.id) {
          srcNode = nid;
          break;
        }
      }
      if (trg.routes === undefined) continue; // legacy: stays absent until saved
      const conns =
        srcNode !== null
          ? data[String(srcNode)]?.outputs?.output_1?.connections || []
          : [];
      trg.routes = {
        conditions: conns
          .map((c) => ed.nodeToCond.get(Number(c.node)))
          .filter(Boolean),
      };
    }
    for (const cond of ed.controller.conditions || []) {
      if (cond.type === "duration") {
        // live sync for duration start/abort too (WHA-F-214): single-value
        // ports, first wire wins
        const nid = ed.condToNode.get(cond.id);
        if (nid === undefined) continue;
        const inputs = data[String(nid)]?.inputs || {};
        cond.start =
          (inputs.input_1?.connections || [])
            .map((c) => ed.nodeToCond.get(Number(c.node)))
            .find(Boolean) || null;
        cond.abort =
          (inputs.input_2?.connections || [])
            .map((c) => ed.nodeToCond.get(Number(c.node)))
            .find(Boolean) || null;
        continue;
      }
      if (cond.type === "flag") {
        const nid = ed.condToNode.get(cond.id);
        if (nid === undefined) continue;
        const inputs = data[String(nid)]?.inputs || {};
        cond.set_conditions = (inputs.input_1?.connections || [])
          .map((c) => ed.nodeToCond.get(Number(c.node)))
          .filter(Boolean);
        cond.reset_conditions = (inputs.input_2?.connections || [])
          .map((c) => ed.nodeToCond.get(Number(c.node)))
          .filter(Boolean);
        const fbody = ed.df.container?.querySelector(`#node-${nid} [data-nbody]`);
        if (fbody) fbody.textContent = conditionSummary(cond, (k) => this.tr(k));
        continue;
      }
      if (!isGroupType(cond.type)) continue;
      const nid = ed.condToNode.get(cond.id);
      if (nid === undefined) continue;
      cond.conditions = (data[String(nid)]?.inputs?.input_1?.connections || [])
        .map((c) => ed.nodeToCond.get(Number(c.node)))
        .filter(Boolean);
      const head = ed.df.container?.querySelector(`#node-${nid} [data-nbody]`);
      if (head) head.textContent = conditionSummary(cond, (k) => this.tr(k));
    }
    // keep an open duration inspector's start/abort indicators live (WHA-F-218)
    if (ed.selected?.condId) {
      const selCond = ed.controller.conditions.find(
        (c) => c.id === ed.selected.condId
      );
      if (selCond?.type === "duration") this._renderInspector();
    }
    if (this._editor?.trial) {
      // trial active: its coloring wins — no ⚠ stamping, no observe replay
      // (WHA-F-245: the guard must precede the stamp block)
      this._refreshPassthroughBadges();
      return;
    }
    if (this._observeHealthy === false) {
      // observe failing: rebuild the ⚠ lines a redraw just wiped (WHA-F-226)
      this._clearStaleVerdicts();
      this._stampObserveUnavailable(ed.df?.container);
    } else if (this._lastObserve) {
      this._applyObserve(this._lastObserve);
    }
    this._refreshPassthroughBadges(); // topological — survives all states
    this._refreshTriggerBadges();
  }

  _connectionAllowed(e) {
    // Wire legality: signal wires only from a trigger output into input_3
    // of a condition gate; gate wires only from a condition into input_1/2.
    const ed = this._editor;
    const srcIsTrg = ed.nodeToTrg.has(Number(e.output_id));
    const srcIsCond = ed.nodeToCond.has(Number(e.output_id));
    const dstIsTrg = ed.nodeToTrg.has(Number(e.input_id));
    const dstIsCond = ed.nodeToCond.has(Number(e.input_id));
    const dstIsOut = ed.nodeToOut.has(Number(e.input_id));
    if (srcIsTrg) {
      // 0.7.0: signals start evaluation through conditions only; outputs
      // expose just the on/off verdict ports. 0.7.3: groups carry a signal
      // port too (dual mode, symmetric exclusion); duration stays a pure
      // gate (start/abort, no signal).
      if (!dstIsCond || e.input_class !== "input_3") return false;
      const dst = ed.controller.conditions.find(
        (c) => c.id === ed.nodeToCond.get(Number(e.input_id))
      );
      if (!dst) return false;
      if (dst.type === "duration" || dst.type === "flag") return false;
      if (isGroupType(dst.type)) {
        // dual mode (0.7.3): trigger wires make the group a trigger-logic
        // merger; symmetric exclusion hides the members port instead
        return !this._groupExclusiveWired(Number(e.input_id), "input_3");
      }
      return true;
    }
    if (srcIsCond) {
      if (dstIsTrg) return false;
      if (e.input_class === "input_3") return false;
      if (dstIsCond) {
        const dst = ed.controller.conditions.find(
          (c) => c.id === ed.nodeToCond.get(Number(e.input_id))
        );
        if (dst && isGroupType(dst.type)) {
          if (e.input_class !== "input_1") return false;
          // signal-frozen: a signal-wired group takes no more members
          if (this._groupExclusiveWired(Number(e.input_id), "input_1")) {
            return false;
          }
          return true;
        }
        if (dst && dst.type === "flag") {
          // flag set/reset ports: multiple wires, each side evaluated as OR
          return e.input_class === "input_1" || e.input_class === "input_2";
        }
        if (dst && dst.type === "duration") {
          // start/abort are single-value ports: a second wire into the same
          // input would be silently dropped on export (WHA-F-024)
          if (e.input_class !== "input_1" && e.input_class !== "input_2") {
            return false;
          }
          try {
            const nd = ed.df.getNodeFromId(String(e.input_id));
            return (nd?.inputs?.[e.input_class]?.connections || []).length <= 1;
          } catch {
            return true;
          }
        }
        // leaf gates have no gate-input semantics: a wire here would be
        // silently dropped on export (WHA-F-019)
        return false;
      }
      if (dstIsOut) return e.input_class === "input_1" || e.input_class === "input_2";
    }
    return false;
  }

  _styleConnections() {
    // Amber signal wires: connections whose source node is a trigger.
    // Vendor renders connections with class `node_out_node-<id>` (the DOM
    // id form), so strip the full "node_out_node-" prefix (WHA-F-015).
    const ed = this._editor;
    if (!ed.df?.container) return;
    ed.df.container.querySelectorAll(".connection").forEach((g) => {
      let signal = false;
      for (const cls of g.classList) {
        if (cls.startsWith("node_out_node-")) {
          signal = ed.nodeToTrg.has(Number(cls.slice(14)));
          break;
        }
      }
      g.classList.toggle("signal", signal);
    });
  }

  _outX() {
    const width = this._editor.df?.container?.clientWidth || 1000;
    // floor = group column x (560) + node max width (240) + 20px gap — keep
    // the output column clear of group nodes on narrow canvases (WHA-F-009)
    return Math.max(820, width - 300);
  }

  _condNodeHtml(cond) {
    const group = isGroupType(cond.type);
    return `
      <div class="wha-node-body-wrap">
        <div class="wha-node-head">
          <span>${TYPE_ICON[cond.type] || "?"}</span>
          <span data-nhead>${esc(this.tr(TYPE_LABEL_KEY[cond.type]))}</span>
          ${group ? "" : `<span class="wha-node-tag">${esc(cond.type)}</span>`}
        </div>
        <div class="wha-node-body" data-nbody>${esc(conditionSummary(cond, (k) => this.tr(k)))}</div>
      </div>`;
  }

  _outNodeHtml(out) {
    return `
      <div class="wha-node-body-wrap">
        <div class="wha-node-head">
          <span data-nicon>${out.type === "switch" ? "⏻" : "◉"}</span>
          <span data-nhead>${esc(out.name)}</span>
          <span class="wha-node-tag" data-ntag>${esc(out.type)}</span>
        </div>
        <div class="wha-node-body" data-nbody>
          ${out.type === "switch" && out.manual_override ? "✋ " : ""}${esc(out.entity_id)}
        </div>
        <span class="decision-badge" data-badge style="display:none"></span>
      </div>`;
  }

  _dfAddCondNode(cond, y) {
    const ed = this._editor;
    // Port model (0.7.3): groups carry BOTH the members port (input_1)
    // and the trigger signal port (input_3) — dual mode, symmetric mutual
    // exclusion, empty groups may take signals directly. Duration keeps
    // start/abort only.
    const isGroup = isGroupType(cond.type);
    const isFlag = cond.type === "flag";
    const inputs = cond.type === "duration" || isFlag ? 2 : 3;
    const nodeId = ed.df.addNode(
      cond.type,
      inputs,
      1,
      isGroup ? 560 : 280,
      y,
      `wha-node cond-node cond-${cond.type}`,
      { condId: cond.id },
      this._condNodeHtml(cond)
    );
    ed.nodeToCond.set(nodeId, cond.id);
    ed.condToNode.set(cond.id, nodeId);
    const kind = cond.type === "duration" ? "duration" : isFlag ? "flag" : isGroupType(cond.type) ? "group" : "leaf";
    this._labelNodePorts(nodeId, kind);
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
    this._labelNodePorts(nodeId, "output");
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
    } else if (type === "cooldown") {
      cond.seconds = 60;
    } else if (type === "duration") {
      cond.seconds = 60;
      cond.start = null;
      cond.abort = null;
    } else if (type === "debounce") {
      cond.seconds = 60;
      cond.entity_id = "";
    } else if (type === "calendar") {
      cond.entity_id = "";
      cond.hours = 24;
    } else if (type === "flag") {
      cond.set_conditions = [];
      cond.reset_conditions = [];
      cond.initial = false;
    } else {
      cond.conditions = [];
    }
    ed.controller.conditions.push(cond);
    const count = ed.controller.conditions.length;
    const nodeId = this._dfAddCondNode(cond, 20 + (count - 1) * 120);
    this._updateGroupPortState(nodeId); // new groups start member-less (WHA-F-101)
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
    const trgId = ed.nodeToTrg.get(nodeId);
    ed.selected = { nodeId, condId: condId || null, outId: outId || null, trgId: trgId ?? null };
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
      if (body) body.textContent = conditionSummary(cond, (k) => this.tr(k));
    } else if (outId) {
      const out = ed.controller.outputs.find((o) => o.entity_id === outId);
      if (!out) return;
      if (head) head.textContent = out.name;
      // head icon/type tag must follow a type switch too (WHA-F-265)
      const nicon = el.querySelector("[data-nicon]");
      if (nicon) nicon.textContent = out.type === "switch" ? "⏻" : "◉";
      const ntag = el.querySelector("[data-ntag]");
      if (ntag) ntag.textContent = out.type;
      if (body)
        body.innerHTML = `${out.type === "switch" && out.manual_override ? "✋ " : ""}${esc(out.entity_id)}`;
    } else {
      const trgId = ed.nodeToTrg.get(nodeId);
      if (trgId === undefined) return;
      this._refreshTriggerNode(nodeId);
    }
    // a body redraw wipes the live status line — re-apply the last verdict
    if (this._editor?.trial) {
      // trial active: its coloring wins, stamp nothing (WHA-F-245)
      this._refreshPassthroughBadges();
      return;
    }
    if (this._observeHealthy === false) {
      // observe failing: rebuild the ⚠ lines a redraw just wiped (WHA-F-226)
      this._clearStaleVerdicts();
      this._stampObserveUnavailable(ed.df?.container);
    } else if (this._lastObserve) {
      this._applyObserve(this._lastObserve);
    }
    this._refreshPassthroughBadges(); // topological — survives all states
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

    if (sel.trgId !== null && sel.trgId !== undefined) {
      const t = (ed.controller.triggers || []).find((x) => x.id === sel.trgId);
      if (!t) return;
      box.innerHTML = `
        <h3>${esc(this.tr(TRIGGER_LABEL_KEY[t.type] || t.type))}</h3>
        ${this._triggerInspectorHtml(t)}
        ${this._trialHtml()}`;
      box.querySelectorAll("[data-trgsk]").forEach((input) =>
        input.addEventListener("change", () => {
          const k = input.dataset.trgsk;
          let v = input.type === "checkbox" ? input.checked : input.value.trim();
          if (k === "entity_id") {
            // 0.10.0 multi-entity: a comma-separated input becomes a list
            // (a single entity stays a string so existing stores round-trip)
            const parts = String(v)
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean);
            v = parts.length > 1 ? parts : parts[0] || "";
          }
          if (k === "every_seconds" || k === "offset") {
            if (v === "") {
              delete t[k];
              ed.dirty = true;
              this._refreshTriggerNode(sel.nodeId);
              return;
            }
            v = Number(v);
            if (!Number.isFinite(v)) return;
          }
          if (v === "" && k !== "entity_id") {
            delete t[k];
          } else {
            if (k === "at") delete t.every_seconds;
            if (k === "every_seconds") delete t.at;
            t[k] = v;
          }
          ed.dirty = true;
          this._refreshTriggerNode(sel.nodeId);
        })
      );
      this._upgradeEntityPickers(box);
      return;
    }

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
        <p class="wha-sub">${esc(out.entity_id)}</p>
        ${out.type === "switch"
          ? `<label class="field field-inline"><input type="checkbox" data-insk="manual_override" ${out.manual_override ? "checked" : ""}> ${esc(this.tr("manualOverride"))}</label>`
          : ""}
        ${/* manual override is a switch-only capability (README; the binary_sensor entity has no control surface to lock, WHA-F-262) */ ""}
        ${this._trialHtml()}`;
      box.querySelectorAll("[data-insk]").forEach((input) =>
        input.addEventListener("change", () => {
          const k = input.dataset.insk;
          out[k] = input.type === "checkbox" ? input.checked : input.value;
          ed.dirty = true;
          if (k === "type") {
            // The type gates the inspector's manual-override checkbox and the
            // node head icon/tag — rebuild the inspector so the gate is
            // re-evaluated (WHA-F-264) instead of leaving a stale checkbox
            // that can still write the flag on the new type.
            this._renderInspector();
          }
          this._refreshNodeBody(sel.nodeId);
        })
      );
      return;
    }

    const cond = ed.controller.conditions.find((c) => c.id === sel.condId);
    if (!cond) return;
    const isGroup = isGroupType(cond.type);
    const f = cond.for || { hours: 0, minutes: 0, seconds: 0 };
    box.innerHTML = `
      ${isGroup ? "" : datalist}
      <h3>${esc(this.tr(TYPE_LABEL_KEY[cond.type]))}</h3>
      <label class="field field-inline"><input type="checkbox" data-insk="enabled" ${cond.enabled !== false ? "checked" : ""}> ${esc(this.tr("enabledLabel"))}</label>
      <label class="field"><span>${esc(this.tr("label"))}</span><input class="wha-input" data-insk="label" value="${esc(cond.label || "")}"></label>
      ${isGroup
        ? `<p class="wha-sub">${esc(this.tr("members"))}: ${(cond.conditions || []).length}</p>`
        : this._condFieldsHtml(cond)}
      ${isGroup || cond.type === "duration" || cond.type === "debounce" || cond.type === "flag"
        ? ""
        : `<label class="field"><span>${esc(this.tr("forDuration"))}</span><span class="wha-row">
            <input class="wha-input" type="number" min="0" max="24" style="width:64px" data-for="hours" value="${esc(f.hours)}">:
            <input class="wha-input" type="number" min="0" max="59" style="width:64px" data-for="minutes" value="${esc(f.minutes)}">:
            <input class="wha-input" type="number" min="0" max="59" style="width:64px" data-for="seconds" value="${esc(f.seconds)}">
          </span></label>`}
      ${cond.type === "duration"
        ? `<p class="wha-sub">${esc(this.tr("wiredStart"))}：${cond.start ? "✓" : "—"}<br>${esc(this.tr("wiredAbort"))}：${cond.abort ? "✓" : "—"}</p>`
        : ""}
      ${this._trialHtml()}`;

    box.querySelectorAll("[data-insk]").forEach((input) =>
      input.addEventListener("change", () => {
        const k = input.dataset.insk;
        let v = input.type === "checkbox" ? input.checked : input.value;
        if (k === "above" || k === "below" || k.endsWith("_offset") || k === "hours") {
          v = v === "" ? null : Number(v);
        } else if (k === "seconds") {
          v = Number(v) || 60;
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
    box.querySelectorAll("[data-wd]").forEach((input) =>
      input.addEventListener("change", () => {
        const set = new Set(cond.weekdays || []);
        if (input.checked) set.add(input.dataset.wd);
        else set.delete(input.dataset.wd);
        cond.weekdays = set.size ? [...set] : undefined;
        ed.dirty = true;
        this._refreshNodeBody(sel.nodeId);
      })
    );
    this._upgradeEntityPickers(box);
  }

  _condFieldsHtml(cond) {
    const trk = (k) => this.tr(k);
    switch (cond.type) {
      case "numeric_state":
        return `
          <div class="field"><span>${esc(trk("entity"))}</span><input class="wha-input" list="wha-entities-insp" data-insk="entity_id" data-epick value="${esc(cond.entity_id || "")}"></div>
          <label class="field"><span>${esc(trk("above"))}</span><input class="wha-input" type="number" step="any" data-insk="above" value="${esc(cond.above ?? "")}"></label>
          <label class="field"><span>${esc(trk("below"))}</span><input class="wha-input" type="number" step="any" data-insk="below" value="${esc(cond.below ?? "")}"></label>`;
      case "state":
        return `
          <div class="field"><span>${esc(trk("entity"))}</span><input class="wha-input" list="wha-entities-insp" data-insk="entity_id" data-epick value="${esc(cond.entity_id || "")}"></div>
          <label class="field"><span>${esc(trk("state"))}</span><input class="wha-input" data-insk="state" value="${esc(Array.isArray(cond.state) ? cond.state.join(",") : cond.state || "")}"></label>`;
      case "time": {
        const wd = cond.weekdays || [];
        return `
          <label class="field"><span>${esc(trk("after"))}(HH:MM)</span><input class="wha-input" placeholder="22:00" data-insk="after" value="${esc(cond.after || "")}"></label>
          <label class="field"><span>${esc(trk("before"))}(HH:MM)</span><input class="wha-input" placeholder="06:00" data-insk="before" value="${esc(cond.before || "")}"></label>
          <label class="field"><span>${esc(trk("weekdaysLabel"))}</span><span class="wha-row">
            ${["mon","tue","wed","thu","fri","sat","sun"].map((d) => `<label class="field-inline" style="font-size:12px"><input type="checkbox" data-wd="${d}" ${wd.includes(d) ? "checked" : ""}>${d}</label>`).join("")}
          </span></label>`;
      }
      case "cooldown":
        return `
          <label class="field"><span>${esc(trk("cooldownSeconds"))}</span><input class="wha-input" type="number" min="1" max="86400" data-insk="seconds" value="${esc(cond.seconds ?? 60)}"></label>`;
      case "duration":
        return `
          <label class="field"><span>${esc(trk("durationSeconds"))}</span><input class="wha-input" type="number" min="1" max="86400" data-insk="seconds" value="${esc(cond.seconds ?? 60)}"></label>`;
      case "debounce":
        return `
          <div class="field"><span>${esc(trk("debounceEntity"))}</span><input class="wha-input" list="wha-entities-insp" data-insk="entity_id" data-epick value="${esc(cond.entity_id || "")}"></div>
          <label class="field"><span>${esc(trk("debounceSeconds"))}</span><input class="wha-input" type="number" min="1" max="86400" data-insk="seconds" value="${esc(cond.seconds ?? 60)}"></label>`;
      case "calendar":
        return `
          <div class="field"><span>${esc(trk("entity"))}</span><input class="wha-input" list="wha-entities-insp" data-insk="entity_id" data-epick="calendar" value="${esc(cond.entity_id || "")}"></div>
          <label class="field"><span>${esc(trk("calendarHours"))}</span><input class="wha-input" type="number" min="1" max="168" data-insk="hours" value="${esc(cond.hours ?? 24)}"></label>`;
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
      case "flag":
        return `
          <p class="wha-sub">${esc(trk("flagHint"))}</p>
          <label class="field field-inline"><input type="checkbox" data-insk="initial" ${cond.initial ? "checked" : ""}> ${esc(trk("flagInitial"))}</label>`;
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
    // Drawflow stores nodes under the bare node id ("1", "2", ...) — NOT
    // "node-<id>" (that prefix only exists on DOM ids and connection
    // classes). Verified against vendor: addNode does `data[a]=w` with the
    // bare id, drag-move reads `data[id.slice(5)]`. Using "node-" here
    // silently exported empty graphs (WHA-F-014, latent since 0.5.0).
    const data = ed.df.export()?.drawflow?.Home?.data || {};
    const nodeRefs = (nodeId, inputClass) => {
      const node = data[String(nodeId)];
      return (node?.inputs?.[inputClass]?.connections || [])
        .map((c) => ed.nodeToCond.get(Number(c.node)))
        .filter(Boolean);
    };
    const singleRef = (nodeId, inputClass) => {
      const refs = nodeRefs(nodeId, inputClass);
      return refs.length ? refs[0] : null;
    };
    for (const cond of ed.controller.conditions) {
      const nid = ed.condToNode.get(cond.id);
      if (!nid) continue;
      if (isGroupType(cond.type)) {
        cond.conditions = nodeRefs(nid, "input_1");
      } else if (cond.type === "flag") {
        cond.set_conditions = nodeRefs(nid, "input_1");
        cond.reset_conditions = nodeRefs(nid, "input_2");
      } else if (cond.type === "duration") {
        cond.start = singleRef(nid, "input_1");
        const abort = singleRef(nid, "input_2");
        if (abort) cond.abort = abort;
        else cond.abort = null;
      }
    }
    for (const out of ed.controller.outputs) {
      const nid = ed.outToNode.get(out.entity_id);
      out.on_conditions = nid ? nodeRefs(nid, "input_1") : [];
      out.off_conditions = nid ? nodeRefs(nid, "input_2") : [];
    }
    // trigger routes from signal wires leaving each trigger node. A legacy
    // trigger (no routes key: evaluate-everything) that has no signal wires
    // keeps its routes absent — saving the canvas must not silently demote
    // it to "wake nothing" (WHA-F-070).
    for (const trg of ed.controller.triggers || []) {
      let srcNode = null;
      for (const [nid, tid] of ed.nodeToTrg) {
        if (tid === trg.id) {
          srcNode = nid;
          break;
        }
      }
      const conns =
        srcNode !== null
          ? data[String(srcNode)]?.outputs?.output_1?.connections || []
          : [];
      if (
        trg.routes === undefined &&
        conns.length === 0 &&
        ed.legacyTrgIds.has(trg.id)
      ) {
        // loaded as legacy (evaluate-everything), still unwired: keep the
        // routes key absent so saving never demotes the semantics
        continue;
      }
      const routes = { conditions: [] };
      for (const c of conns) {
        const dstId = Number(c.node);
        if (ed.nodeToCond.has(dstId)) {
          routes.conditions.push(ed.nodeToCond.get(dstId));
        }
      }
      trg.routes = routes;
    }
  }

  async _saveEditor() {
    const ed = this._editor;
    this._exportGraph();
    if (!ed.controller.name?.trim()) {
      this.toast(this.tr("controllerName"), true);
      return;
    }
    // M4 (0.9.0): an enabled directed trigger with empty coverage wakes
    // nothing — usually a wire that was drawn and then deleted. Block the
    // silent demotion once per editor session; legacy (routes absent) and
    // disabled triggers are exempt.
    const deadTrg = (ed.controller.triggers || []).filter(
      (t) =>
        t.enabled !== false &&
        t.routes !== undefined &&
        !(t.routes?.conditions || []).length
    );
    if (deadTrg.length && !ed.deadTrgConfirmed) {
      if (!window.confirm(this.tr("trgDeadConfirm"))) return;
      ed.deadTrgConfirmed = true;
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
      // Memory-state comparison (WHA-F-259): location.hash is shell-owned
      // (#pn=…) so a hash comparison would re-render — and reset the canvas
      // layout — on every in-shell save; standalone already skips when the
      // view is already on this controller's editor.
      if (this._view !== "editor" || this._cid !== ed.cid) {
        this._nav(`#/editor/${ed.cid}`);
      }
    } catch (err) {
      this.toast(String(err.message || err), true);
    }
  }

  async _trialRun() {
    const ed = this._editor;
    if (ed.isNew) {
      // 从未保存过：阻断（WHA-UX-02——与 dirty 确认拆键）
      this.toast(this.tr("trialNeedSave"), true);
      return;
    }
    if (ed.dirty) {
      // 有未保存修改：明示"按已保存配置执行"，自绘确认（WHA-UX-01）
      this._openConfirm(this.tr("confirmTitle"), this.tr("trialDirtyConfirm"), () => {
        this._runTrial();
      });
      return;
    }
    await this._runTrial();
  }

  async _runTrial() {
    const ed = this._editor;
    let r;
    try {
      r = await this._api("POST", `/controllers/${ed.cid}/evaluate`);
      // trial supersedes observe this cycle: drop the live status lines so
      // trial coloring isn't mixed with observe ✓/✗ rows (WHA-F-242)
      ed.df?.container
        ?.querySelectorAll("[data-observe]")
        .forEach((el) => el.remove());
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
      // trial failure: drop the stale artifacts too (WHA-F-234) — a stale
      // snapshot next to a failure toast contradicts itself
      ed.trial = null;
      this.shadowRoot
        ?.querySelector("[data-inspector] details.wha-json")
        ?.remove();
      for (const nodeId of ed.outToNode.values()) {
        const badge = ed.df?.container?.querySelector(
          `#node-${nodeId} [data-badge]`
        );
        if (badge) badge.style.display = "none";
      }
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
        // UX-M-04: 失败与"该日无记录"分态展示
        box.innerHTML = `<p class="wha-sub" style="color:#c62828">${esc(
          String(err.message || err)
        )}（可点「查询」重试）</p>`;
      }
    };
    main.querySelector('[data-lact="query"]').addEventListener("click", query);
    query();
  }

  // 自绘确认对话框（WHA-UX-01）：原生 confirm 在壳内/移动端观感突兀且按钮
  // 序不可控；仅此一处组件，删除控制器与试运行 dirty 确认共用。
  _openConfirm(title, text, onOk) {
    const root = this.shadowRoot;
    root.querySelector(".wha-confirm")?.remove();
    const wrap = document.createElement("div");
    wrap.className = "wha-confirm";
    wrap.style.cssText =
      "position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:60;";
    const box = document.createElement("div");
    box.className = "wha-card";
    box.style.cssText = "max-width:420px;margin:16px;padding:16px;";
    box.innerHTML = `
      <h2 style="margin:0 0 8px">${esc(title)}</h2>
      <p class="wha-sub" style="margin:0 0 12px">${esc(text)}</p>
      <div class="wha-row" style="justify-content:flex-end;gap:8px">
        <button class="wha-btn" data-wc="cancel">${esc(this.tr("confirmCancel"))}</button>
        <button class="wha-btn danger" data-wc="ok">${esc(this.tr("confirmOk"))}</button>
      </div>`;
    wrap.appendChild(box);
    wrap.addEventListener("click", (ev) => {
      const c = ev.target?.dataset?.wc;
      if (c || ev.target === wrap) {
        wrap.remove();
        if (c === "ok") onOk();
      }
    });
    root.appendChild(wrap);
  }

  _toggleBusy = null; // 正在启停/评估的控制器 id（WHA-IMP-03：跨重渲染保持禁用）

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
          <td class="wha-sub">${esc(r.triggered_by || "—")}</td>
          <td>
            ${r.conditions && Object.keys(r.conditions).length
              ? `<details class="wha-json"><summary>${esc(this.tr("logConditions"))}</summary>
                  <pre>${esc(JSON.stringify(r.conditions, null, 2))}</pre>
                </details>`
              : "—"}
          </td>
          <td>
            <details class="wha-json"><summary>${esc(this.tr("readouts"))}</summary>
              <pre>${esc(JSON.stringify(r.readings || {}, null, 2))}</pre>
            </details>
          </td>
        </tr>`;
      })
      .join("");
    box.innerHTML = `
      ${logs.truncated ? `<p class="wha-sub">${esc(this.tr("logsTruncated"))}</p>` : ""}
      ${rows
        ? `<table class="wha-table"><thead><tr>
            <th>${esc(this.tr("time"))}</th><th>${esc(this.tr("outputs"))}</th><th>${esc(this.tr("decision"))}</th>
            <th>on_met</th><th>off_met</th><th>applied</th><th>${esc(this.tr("byLabel"))}</th><th>${esc(this.tr("logConditions"))}</th><th>${esc(this.tr("readouts"))}</th>
          </tr></thead><tbody>${rows}</tbody></table>`
        : `<p class="wha-sub">${esc(this.tr("logsEmpty"))}</p>`}`;
  }
}

// Guarded define: a re-import under a new ?ver= (deploy while the tab is
// open) must not throw "already defined" — the shell detects version drift
// itself and asks for a refresh.
if (!customElements.get(TAG)) {
  customElements.define(TAG, ScannerPanel);
} else {
  console.warn(
    `[${TAG}] already defined — skipping re-register (module re-import under a new ?ver=; ` +
      "the shell shows its own refresh card on version drift)"
  );
}
