"""Constants for Sensor Switch Controller."""

DOMAIN = "sensor_switch_controller"
PLATFORMS = ["switch", "binary_sensor"]
ENTRY_TITLE = "HA 全屋状态扫描"

# ------------------------------------------------------------------
# Storage (single config entry, all controllers in one Store)
# ------------------------------------------------------------------
STORE_KEY = DOMAIN
STORE_VERSION = 6
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
CONF_SENSORS = "sensors"
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
COND_AND = "and"
COND_OR = "or"
COND_NOT = "not"

# Flag (latch) condition fields: set/reset reference condition ids, the
# verdict is a latched virtual boolean stepped once per evaluation cycle.
CONF_SET_CONDITIONS = "set_conditions"
CONF_RESET_CONDITIONS = "reset_conditions"
CONF_INITIAL = "initial"

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

DEFAULT_SCAN_INTERVAL = 180
SUN_OFFSET_LIMIT = 86400
COOLDOWN_MAX = 86400
DURATION_MAX = 86400
DEBOUNCE_MAX = 86400
CALENDAR_HOURS_MAX = 168
EVAL_DEBOUNCE_SECONDS = 0.2
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
