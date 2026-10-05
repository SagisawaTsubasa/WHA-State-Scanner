"""Constants for Sensor Switch Controller."""

DOMAIN = "sensor_switch_controller"
PLATFORMS = ["switch", "binary_sensor"]
ENTRY_TITLE = "HA 全屋状态扫描"

# ------------------------------------------------------------------
# Storage (single config entry, all controllers in one Store)
# ------------------------------------------------------------------
STORE_KEY = DOMAIN
STORE_VERSION = 2
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
COND_AND = "and"
COND_OR = "or"

# Output types
OUTPUT_SWITCH = "switch"
OUTPUT_BINARY_SENSOR = "binary_sensor"

DEFAULT_SCAN_INTERVAL = 180
SCAN_INTERVAL_MIN = 10
SCAN_INTERVAL_MAX = 3600
SUN_OFFSET_LIMIT = 86400
