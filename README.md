# HA Whole-House State Scanner

A fully visual, zero-YAML whole-house state scanner and logic controller for Home Assistant. Define any number of sensors, compose any number of condition rules, and generate any number of output entities (switches or binary sensors) — all through the UI. No YAML editing required.

> **Programmer:** [Kimi](https://kimi.moonshot.cn) (Moonshot AI) · Author: [@SagizawaTsubasa](https://github.com/SagisawaTsubasa)

---

## Features

- **Pure UI Configuration** — 5-step wizard, no YAML required
- **Sensor Pool** — Reference any number of entities in a single controller
- **Condition Library** — `numeric_state`, `state`, `time`, `sun`, `template`, plus `AND`/`OR` nesting
- **Incremental Editing** — Add, edit, or delete conditions and outputs after creation without rebuilding the controller
- **Multiple Outputs** — One controller can drive multiple switches or binary sensors
- **FOR Duration** — Built-in state-persistence timer support
- **Independent Logging** — Decision logs are written to dedicated JSONL files (daily rotation), never mixed into `home-assistant.log`
- **Manual Override** — Optional per-switch manual control lock
- **Hot Reload** — Options changes take effect immediately without restart

---

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS.
2. Install **HA Whole-House State Scanner**.
3. Restart Home Assistant.

### Manual

1. Copy `custom_components/sensor_switch_controller` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **HA Whole-House State Scanner**.

---

## Configuration Wizard

### Step 1: Basic Settings
- **Name**: e.g. `Bathroom Humidity Control`
- **Scan Interval**: Polling frequency in seconds (default: 180)
- **Enable Logging**: Toggle independent decision logging

### Step 2: Sensor Pool
- Multi-select any entities that will participate in logic evaluation.

### Step 3: Condition Rules
Click **Add Condition** and choose a type:

| Type | Description |
|------|-------------|
| **Numeric State** | Compare sensor value against `above` / `below` thresholds |
| **State** | Match exact state string(s). Multiple states supported via comma separation. Optional `FOR` duration. |
| **Time** | Restrict to a time range (`after` / `before`) |
| **Sun** | Sunrise / sunset based with offset in seconds (negative for before) |
| **Template** | Full Jinja2 template expression |
| **AND / OR Group** | Nest existing conditions into composite logic |

Top-level conditions are evaluated with **OR** logic (any one satisfied triggers).

### Step 4: Output Entities
Each controller can generate multiple outputs:
- **Switch**: Toggleable entity with optional manual override
- **Binary Sensor**: Read-only state indicator
- Bind `on_conditions` and `off_conditions` from your rule library
- `off_conditions` always take priority over `on_conditions` (hysteresis)

### Step 5: Confirm
Review the full configuration summary before creation.

---

## Editing After Creation

Go to **Settings → Devices & Services → HA Whole-House State Scanner → Configure → Options**.

| Item | Supported Operations |
|------|---------------------|
| Scan Interval | Direct edit |
| Logging | Toggle on/off |
| Sensor Pool | Direct edit (note: may invalidate existing conditions) |
| **Condition Rules** | **Add / Edit / Delete** with pre-filled forms |
| **Output Entities** | **Add / Delete** |

All changes are hot-reloaded. No restart required.

---

## Independent Logging

When enabled, every evaluation cycle is appended to a dedicated JSONL file:

```
<HA_CONFIG>/sensor_switch_controller_logs/<entry_id>/<controller_name>_<YYYY-MM-DD>.jsonl
```

**Example record:**
```json
{"timestamp":"2026-07-16T14:30:00+08:00","controller":"Bathroom Humidity Control","output":"Dehumidifier Enable","decision":"on","on_met":true,"off_met":false,"readings":{"sensor.humidity_diff":"25.3","switch.ventilation":"off"}}
```

**Properties:**
- Daily file rotation
- JSON Lines format — parseable with `jq`, Python, or any text tool
- Completely isolated from Home Assistant system logs

---

## Architecture

```
Config Entry (One Controller)
├── Sensor Pool          → Any entity references
├── Condition Engine     → Modular evaluation + FOR timer support
├── Output Entities      → switch / binary_sensor (any quantity)
└── Decision Logger      → Dedicated JSONL file logs (daily rotation)
```

**Key Components:**

| File | Purpose |
|------|---------|
| `controller.py` | Orchestrates polling, evaluation, entity registration, and hot reload |
| `condition_engine.py` | Recursive condition evaluator supporting 6 leaf types + AND/OR nesting + FOR timers |
| `logbook.py` | File-based JSONL logger with daily rotation |
| `config_flow.py` | 5-step setup wizard + full incremental Options Flow |
| `switch.py` / `binary_sensor.py` | Output platforms with controller-driven state updates |

---

## Service

### `sensor_switch_controller.force_evaluate`

Manually trigger an evaluation cycle for a specific controller.

```yaml
service: sensor_switch_controller.force_evaluate
target:
  entity_id: switch.bathroom_humidity_control_dehumidifier_enable
```

---

## Extensibility

The framework is designed for easy extension:

- **New Condition Types**: Add a branch in `condition_engine.py::_evaluate_leaf()`
- **New Output Types**: Register in `const.py` and implement the corresponding platform file
- **Action Outputs** (future): Direct service calls (e.g. `fan.set_percentage`) without intermediate entities

---

## Compatibility

- Home Assistant **2024.1+**
- Python **3.12+**

---

## License

MIT

---

*Built with [Kimi](https://kimi.moonshot.cn) by Moonshot AI · Author: [@SagizawaTsubasa](https://github.com/SagisawaTsubasa)*
