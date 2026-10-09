"""Constants for Sensor Switch Controller."""

DOMAIN = "sensor_switch_controller"
PLATFORMS = ["switch", "binary_sensor"]
ENTRY_TITLE = "HA 全屋状态扫描"

# ------------------------------------------------------------------
# Storage (single config entry, all controllers in one Store)
# ------------------------------------------------------------------
STORE_KEY = DOMAIN
STORE_VERSION = 4
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
COND_AND = "and"
COND_OR = "or"
COND_NOT = "not"

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
