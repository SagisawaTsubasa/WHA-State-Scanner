"""Constants for Sensor Switch Controller."""

DOMAIN = "sensor_switch_controller"
PLATFORMS = ["switch", "binary_sensor"]

# Config Flow keys
CONF_SCAN_INTERVAL = "scan_interval"
CONF_LOGGING = "logging_enabled"
CONF_SENSORS = "sensors"
CONF_CONDITIONS = "conditions"
CONF_OUTPUTS = "outputs"

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
