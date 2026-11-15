"""Constants for Sensor Switch Controller."""

DOMAIN = "sensor_switch_controller"
PLATFORMS = ["switch", "binary_sensor"]
ENTRY_TITLE = "HA 全屋状态扫描"

# ------------------------------------------------------------------
# Storage (single config entry, all controllers in one Store)
# ------------------------------------------------------------------
STORE_KEY = DOMAIN
# v9 (0.14.0): the stateful step nodes land their runtime values in a fifth
# table of the runtime (_flags) store; the main-store bump re-epochs the
# format (the v8→v9 controller chain is an empty passthrough — no controller
# config field changed — but every stored payload is re-saved at v9).
STORE_VERSION = 9
CONF_CONTROLLERS = "controllers"
CTRL_ID_PREFIX = "ctrl_"

# ------------------------------------------------------------------
# Web (panel + REST API + static assets)
# ------------------------------------------------------------------
URL_BASE = f"/{DOMAIN}"
API_BASE = f"/api/{DOMAIN}"
PANEL_URL_PATH = "wha-scanner"
PANEL_SIDEBAR_TITLE = "全屋状态扫描"
PANEL_SIDEBAR_ICON = "mdi:state-machine"
PANEL_ELEMENT = "sensor-switch-controller-panel"

# FumihaHub 页面接入契约（fumiha_hub/registry.py 模块文档）：两个字符串常量
# + 一个 dict，按契约在本仓复制字面量，绝不 import 壳包。探针 = 键存在 ⇔
# 壳条目已加载且未删除；绝不能自己 setdefault 创建该 dict（无壳环境下页面
# 会因此永久不可达）。已知边界（上游 FXH-F-026）：壳条目被「禁用」（仅
# unload，dict 保留）期间本页在壳内不可达、本条目重载也不回落独立面板——
# 恢复靠重新启用壳，或删除壳条目后本条目重载（WHA-F-260）。
HUB_REGISTRY_KEY = "fumiha_hub_registry"
HUB_BUS_EVENT_PAGE_CHANGED = "fumiha_hub_page_changed"
HUB_PAGE_ID = "sensorswitch.main"
HUB_PAGE_ORDER = 40

# ------------------------------------------------------------------
# Config flow keys (kept for the persisted controller schema)
# ------------------------------------------------------------------
CONF_SCAN_INTERVAL = "scan_interval"
CONF_LOGGING = "logging_enabled"
CONF_CONDITIONS = "conditions"
CONF_OUTPUTS = "outputs"
CONF_ENABLED = "enabled"

# Condition types
COND_NUMERIC_STATE = "numeric_state"
COND_STATE = "state"
COND_TIME = "time"
COND_SUN = "sun"
COND_TEMPLATE = "template"
COND_COOLDOWN = "cooldown"
COND_CALENDAR = "calendar"
COND_DURATION = "duration"
COND_DEBOUNCE = "debounce"
COND_FLAG = "flag"
COND_SNAPSHOT = "snapshot"
COND_LITERAL = "literal"
COND_COMPARE = "compare"
COND_COUNTDOWN = "countdown"
COND_QUOTA = "quota"
COND_TALLY = "tally"
COND_AND = "and"
COND_OR = "or"
COND_NOT = "not"

# Stateful step nodes (0.14.0): one step mechanism, three parameterizations.
# Each kind has a primary gate (rising edge) and the shared reset gate
# (rising edge, same-cycle reset wins); the verdict is stepped once per
# evaluation cycle and persists across restarts (fifth runtime table).
STATEFUL_TYPES = (COND_COUNTDOWN, COND_QUOTA, COND_TALLY)
# Primary-gate config key per kind — single source shared by the schema
# validation and the engine step so the two cannot drift.
STATEFUL_GATE_KEYS = {
    COND_COUNTDOWN: "start_conditions",
    COND_QUOTA: "consume_conditions",
    COND_TALLY: "count_conditions",
}

# Flag (latch) condition fields: set/reset reference condition ids, the
# verdict is a latched virtual boolean stepped once per evaluation cycle.
CONF_SET_CONDITIONS = "set_conditions"
CONF_RESET_CONDITIONS = "reset_conditions"
CONF_INITIAL = "initial"

# Stateful step-node gate fields (0.14.0): the primary gate per kind is
# keyed in STATEFUL_GATE_KEYS; every kind shares reset_conditions.
CONF_START_CONDITIONS = "start_conditions"
CONF_CONSUME_CONDITIONS = "consume_conditions"
CONF_COUNT_CONDITIONS = "count_conditions"

# Snapshot (memory) condition fields: capture/clear reference condition ids
# (capture = rising-edge of the capture gate, clear = level, reset wins);
# the latched value is the source entity's reading at capture time. Literal
# (constant) and compare (two-input verdict) fields follow.
CONF_CAPTURE = "capture"
CONF_CLEAR = "clear"
CONF_VALUE_TYPE = "value_type"
CONF_VALUE = "value"
CONF_INPUT_A = "a"
CONF_INPUT_B = "b"
CONF_OP = "op"

# Compare operators (op whitelist shared by schema validation and the engine).
COMPARE_OPS = (
    "equal",
    "not_equal",
    "above",
    "below",
    "above_equal",
    "below_equal",
)

# Trip condition leaves (0.16.0): read the trip_count trip binary sensor's
# state + attributes (day_n / since) — ordinary leaves (`for` applies, they
# are signal origins). trip_count missing/unreadable = loud unavailable face
# (rate-limited WARN + False), never a silent degrade (决策 5).
COND_TRIP_ON = "trip_on"
COND_TRIP_DAY = "trip_day"
COND_TRIP_DURATION = "trip_duration"
TRIP_TYPES = (COND_TRIP_ON, COND_TRIP_DAY, COND_TRIP_DURATION)
TRIP_DAY_MAX = 365
# 段时长 threshold cap: one year in hours (a trip longer than that is a
# config error, same spirit as the other timing caps).
TRIP_DURATION_HOURS_MAX = 8760
CONF_DAY = "day"
# Attribute keys the trip_count trip binary sensor carries (contract frozen
# by trip_count logic.py/binary_sensor.py; WHA only READS them).
TRIP_ATTR_DAY_N = "day_n"
TRIP_ATTR_SINCE = "since"

# "文羽服务" action output (0.16.0): an output type that calls a service on
# the service bus instead of flipping an entity. The domain is a CLOSED
# built-in list (决策 2: 内置名单，非 manifest 自声明) — the panel dropdown
# mirrors the same list and a pairing test pins the two faces equal.
# Extension point: append the domain here AND to FUMIHA_DOMAINS in
# static/panel.js (the pairing test fails otherwise).
FUMIHA_SERVICE_DOMAINS = (
    "fumiha_hub",
    "fumiha_lighting",
    "sensor_switch_controller",
    "stockroom",
    "trip_count",
    "auto_night_light",
    "glm_quota",
    "lux_balance",
    "filter_life_tracker",
    "deepseek_usage",
    "water_heater_optimizer",
)
CONF_DOMAIN = "domain"
CONF_SERVICE = "service"

# Trigger types
TRG_STATE = "state"
TRG_TIME = "time"
TRG_SUN = "sun"
TRG_HOMEASSISTANT = "homeassistant"
CONF_TRIGGERS = "triggers"
CONF_ATTRIBUTE = "attribute"
CONF_FROM = "from"
CONF_TO = "to"
CONF_WEEKDAYS = "weekdays"
CONF_AT = "at"
CONF_EVERY_SECONDS = "every_seconds"
CONF_HOURS = "hours"
CONF_SECONDS = "seconds"
CONF_OFFSET = "offset"
CONF_ROUTES = "routes"
CONF_START = "start"
CONF_ABORT = "abort"
TRG_ID_PREFIX = "trg_"

# Output types
OUTPUT_SWITCH = "switch"
OUTPUT_BINARY_SENSOR = "binary_sensor"
# "文羽服务" action output (0.16.0): no entity is registered for it; the
# evaluation calls {domain, service} on the service bus on the on-chain's
# rising edge (off chain wins / resets the edge, same precedence as flips).
OUTPUT_FUMIHA_SERVICE = "fumiha_service"

DEFAULT_SCAN_INTERVAL = 180
SUN_OFFSET_LIMIT = 86400
COOLDOWN_MAX = 86400
DURATION_MAX = 86400
DEBOUNCE_MAX = 86400
QUOTA_MAX = 86400
CALENDAR_HOURS_MAX = 168
EVAL_DEBOUNCE_SECONDS = 0.2
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
