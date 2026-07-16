"""Config flow with visual wizard and incremental condition editing."""

from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    COND_AND,
    COND_NUMERIC_STATE,
    COND_OR,
    COND_STATE,
    COND_SUN,
    COND_TEMPLATE,
    COND_TIME,
    CONF_CONDITIONS,
    CONF_LOGGING,
    CONF_OUTPUTS,
    CONF_SCAN_INTERVAL,
    CONF_SENSORS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OUTPUT_BINARY_SENSOR,
    OUTPUT_SWITCH,
)

# ------------------------------------------------------------------
# Shared helper: build sensor options from sensor pool
# ------------------------------------------------------------------

def _sensor_options(sensors: list[dict]) -> list[dict]:
    return [
        {"value": s["entity_id"], "label": f"{s.get('alias', s['entity_id'])} ({s['entity_id']})"}
        for s in sensors
    ]

def _condition_options(conditions: list[dict]) -> list[dict]:
    return [
        {"value": c["id"], "label": f"{c.get('label', c['id'])} [{c['type']}]"}
        for c in conditions
    ]


# ------------------------------------------------------------------
# Config Flow
# ------------------------------------------------------------------

class SensorSwitchControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, Any] = {}

    def _get_store(self) -> dict:
        self.hass.data.setdefault(DOMAIN, {})
        if self.flow_id not in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN][self.flow_id] = {}
        return self.hass.data[DOMAIN][self.flow_id]

    def _clear_store(self) -> None:
        self.hass.data[DOMAIN].pop(self.flow_id, None)

    # ---------- Step 1: Basic ----------
    async def async_step_user(self, user_input=None):
        errors = {}
        store = self._get_store()
        if user_input is not None:
            store["name"] = user_input[CONF_NAME]
            store["scan_interval"] = user_input[CONF_SCAN_INTERVAL]
            store["logging"] = user_input[CONF_LOGGING]
            return await self.async_step_sensors()
        schema = vol.Schema({
            vol.Required(CONF_NAME): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                vol.Coerce(int), vol.Range(min=10, max=3600)
            ),
            vol.Optional(CONF_LOGGING, default=False): bool,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    # ---------- Step 2: Sensors ----------
    async def async_step_sensors(self, user_input=None):
        errors = {}
        store = self._get_store()
        current = store.get("sensors", [])
        if user_input is not None:
            selected = user_input.get("entities", [])
            existing = {s["entity_id"]: s.get("alias", "") for s in current}
            store["sensors"] = [
                {"entity_id": eid, "alias": existing.get(eid, "")}
                for eid in selected
            ]
            return await self.async_step_conditions_menu()
        schema = vol.Schema({
            vol.Optional("entities", default=[s["entity_id"] for s in current]): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
        })
        return self.async_show_form(step_id="sensors", data_schema=schema, errors=errors)

    # ---------- Step 3: Conditions Menu ----------
    async def async_step_conditions_menu(self, user_input=None):
        store = self._get_store()
        conditions = store.get("conditions", [])
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_add_condition()
            if action == "done":
                return await self.async_step_outputs()
        menu_items = [f"{i+1}. [{c['type']}] {c.get('label', c['id'])}" for i, c in enumerate(conditions)]
        schema = vol.Schema({
            vol.Optional("action", default="done"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "add", "label": "➕ 添加条件"},
                        {"value": "done", "label": "✅ 完成条件配置"},
                    ],
                    mode="list",
                )
            ),
        })
        return self.async_show_form(
            step_id="conditions_menu",
            data_schema=schema,
            description_placeholders={
                "conditions_list": "\n".join(menu_items) if menu_items else "（暂无条件）",
            },
        )

    # ---------- Step 3a: Choose condition type ----------
    async def async_step_add_condition(self, user_input=None):
        if user_input is not None:
            ctype = user_input["condition_type"]
            store = self._get_store()
            store["_pending_cond_type"] = ctype
            if ctype == COND_NUMERIC_STATE:
                return await self.async_step_cond_numeric()
            if ctype == COND_STATE:
                return await self.async_step_cond_state()
            if ctype == COND_TIME:
                return await self.async_step_cond_time()
            if ctype == COND_SUN:
                return await self.async_step_cond_sun()
            if ctype == COND_TEMPLATE:
                return await self.async_step_cond_template()
            if ctype in (COND_AND, COND_OR):
                return await self.async_step_cond_group()
        schema = vol.Schema({
            vol.Required("condition_type"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": COND_NUMERIC_STATE, "label": "数值比较 (numeric_state)"},
                        {"value": COND_STATE, "label": "状态匹配 (state)"},
                        {"value": COND_TIME, "label": "时间范围 (time)"},
                        {"value": COND_SUN, "label": "日出日落 (sun)"},
                        {"value": COND_TEMPLATE, "label": "模板表达式 (template)"},
                        {"value": COND_AND, "label": "AND 组合"},
                        {"value": COND_OR, "label": "OR 组合"},
                    ],
                    mode="list",
                )
            ),
        })
        return self.async_show_form(step_id="add_condition", data_schema=schema)

    # ---------- Step 3b-f: Condition forms ----------
    async def async_step_cond_numeric(self, user_input=None):
        store = self._get_store()
        sensors = store.get("sensors", [])
        sensor_options = _sensor_options(sensors)
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_NUMERIC_STATE,
                "label": user_input.get("label", "数值条件"),
                "entity_id": user_input["entity_id"],
                "above": user_input.get("above"),
                "below": user_input.get("below"),
            }
            if user_input.get("for_enabled"):
                cond["for"] = {
                    "hours": user_input.get("for_hours", 0),
                    "minutes": user_input.get("for_minutes", 0),
                    "seconds": user_input.get("for_seconds", 0),
                }
            store.setdefault("conditions", []).append(cond)
            return await self.async_step_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="数值条件"): str,
            vol.Required("entity_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=sensor_options, mode="dropdown")
            ),
            vol.Optional("above"): vol.Any(vol.Coerce(float), None),
            vol.Optional("below"): vol.Any(vol.Coerce(float), None),
            vol.Optional("for_enabled", default=False): bool,
            vol.Optional("for_hours", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=24)),
            vol.Optional("for_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
            vol.Optional("for_seconds", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        })
        return self.async_show_form(step_id="cond_numeric", data_schema=schema)

    async def async_step_cond_state(self, user_input=None):
        store = self._get_store()
        sensors = store.get("sensors", [])
        sensor_options = _sensor_options(sensors)
        if user_input is not None:
            state_val = user_input["state"]
            states = [s.strip() for s in state_val.split(",")] if "," in state_val else state_val
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_STATE,
                "label": user_input.get("label", "状态条件"),
                "entity_id": user_input["entity_id"],
                "state": states if isinstance(states, list) and len(states) > 1 else state_val,
            }
            if user_input.get("for_enabled"):
                cond["for"] = {
                    "hours": user_input.get("for_hours", 0),
                    "minutes": user_input.get("for_minutes", 0),
                    "seconds": user_input.get("for_seconds", 0),
                }
            store.setdefault("conditions", []).append(cond)
            return await self.async_step_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="状态条件"): str,
            vol.Required("entity_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=sensor_options, mode="dropdown")
            ),
            vol.Required("state"): str,
            vol.Optional("for_enabled", default=False): bool,
            vol.Optional("for_hours", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=24)),
            vol.Optional("for_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
            vol.Optional("for_seconds", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        })
        return self.async_show_form(step_id="cond_state", data_schema=schema)

    async def async_step_cond_time(self, user_input=None):
        store = self._get_store()
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_TIME,
                "label": user_input.get("label", "时间条件"),
            }
            if user_input.get("after"):
                cond["after"] = user_input["after"]
            if user_input.get("before"):
                cond["before"] = user_input["before"]
            store.setdefault("conditions", []).append(cond)
            return await self.async_step_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="时间条件"): str,
            vol.Optional("after"): selector.TimeSelector(),
            vol.Optional("before"): selector.TimeSelector(),
        })
        return self.async_show_form(step_id="cond_time", data_schema=schema)

    async def async_step_cond_sun(self, user_input=None):
        store = self._get_store()
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_SUN,
                "label": user_input.get("label", "日出日落条件"),
            }
            if user_input.get("after"):
                cond["after"] = user_input["after"]
                off = user_input.get("after_offset", 0)
                if off != 0:
                    cond["after_offset"] = off
            if user_input.get("before"):
                cond["before"] = user_input["before"]
                off = user_input.get("before_offset", 0)
                if off != 0:
                    cond["before_offset"] = off
            store.setdefault("conditions", []).append(cond)
            return await self.async_step_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="日出日落条件"): str,
            vol.Optional("after"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "", "label": "（不限制）"},
                        {"value": "sunrise", "label": "日出后"},
                        {"value": "sunset", "label": "日落后"},
                    ],
                    mode="dropdown",
                )
            ),
            vol.Optional("after_offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=-86400, max=86400)),
            vol.Optional("before"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "", "label": "（不限制）"},
                        {"value": "sunrise", "label": "日出前"},
                        {"value": "sunset", "label": "日落前"},
                    ],
                    mode="dropdown",
                )
            ),
            vol.Optional("before_offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=-86400, max=86400)),
        })
        return self.async_show_form(step_id="cond_sun", data_schema=schema)

    async def async_step_cond_template(self, user_input=None):
        store = self._get_store()
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_TEMPLATE,
                "label": user_input.get("label", "模板条件"),
                "value_template": user_input["template"],
            }
            store.setdefault("conditions", []).append(cond)
            return await self.async_step_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="模板条件"): str,
            vol.Required("template"): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        })
        return self.async_show_form(step_id="cond_template", data_schema=schema)

    async def async_step_cond_group(self, user_input=None):
        store = self._get_store()
        conditions = store.get("conditions", [])
        cond_options = _condition_options(conditions)
        ctype = store.get("_pending_cond_type", COND_AND)
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": ctype,
                "label": user_input.get("label", f"{ctype.upper()} 组合"),
                "conditions": user_input.get("members", []),
            }
            store.setdefault("conditions", []).append(cond)
            return await self.async_step_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default=f"{ctype.upper()} 组合"): str,
            vol.Required("members", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cond_options, multiple=True, mode="list")
            ),
        })
        return self.async_show_form(step_id="cond_group", data_schema=schema)

    # ---------- Step 4: Outputs ----------
    async def async_step_outputs(self, user_input=None):
        store = self._get_store()
        outputs = store.get("outputs", [])
        conditions = store.get("conditions", [])
        cond_options = _condition_options(conditions)
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                out = {
                    "name": user_input["name"],
                    "type": user_input["output_type"],
                    "entity_id": f"ssc_{uuid.uuid4().hex[:6]}",
                    "on_conditions": user_input.get("on_conditions", []),
                    "off_conditions": user_input.get("off_conditions", []),
                    "manual_override": user_input.get("manual_override", False),
                }
                outputs.append(out)
                store["outputs"] = outputs
                return await self.async_step_outputs()
            if action == "done":
                if not outputs:
                    return await self.async_step_outputs()
                return await self.async_step_confirm()
        out_lines = []
        for i, o in enumerate(outputs):
            out_lines.append(f"{i+1}. {o['name']} ({o['type']}) | ON:{len(o['on_conditions'])} OFF:{len(o['off_conditions'])}")
        schema = vol.Schema({
            vol.Optional("action", default="add"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "add", "label": "➕ 添加输出实体"},
                        {"value": "done", "label": "✅ 完成输出配置"},
                    ],
                    mode="list",
                )
            ),
            vol.Optional("name", default="逻辑开关"): str,
            vol.Optional("output_type", default=OUTPUT_SWITCH): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": OUTPUT_SWITCH, "label": "开关 (Switch)"},
                        {"value": OUTPUT_BINARY_SENSOR, "label": "二进制传感器 (Binary Sensor)"},
                    ],
                    mode="dropdown",
                )
            ),
            vol.Optional("on_conditions", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cond_options, multiple=True, mode="list")
            ),
            vol.Optional("off_conditions", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cond_options, multiple=True, mode="list")
            ),
            vol.Optional("manual_override", default=False): bool,
        })
        return self.async_show_form(
            step_id="outputs",
            data_schema=schema,
            description_placeholders={
                "outputs_list": "\n".join(out_lines) if out_lines else "（暂无输出实体）",
            },
        )

    # ---------- Step 5: Confirm ----------
    async def async_step_confirm(self, user_input=None):
        store = self._get_store()
        if user_input is not None:
            data = {
                CONF_SCAN_INTERVAL: store["scan_interval"],
                CONF_LOGGING: store["logging"],
                CONF_SENSORS: store.get("sensors", []),
                CONF_CONDITIONS: store.get("conditions", []),
                CONF_OUTPUTS: store.get("outputs", []),
            }
            self._clear_store()
            return self.async_create_entry(title=store["name"], data={}, options=data)
        sensors = store.get("sensors", [])
        conditions = store.get("conditions", [])
        outputs = store.get("outputs", [])
        summary = f"**传感器 ({len(sensors)} 个):**\n"
        for s in sensors:
            summary += f"- {s.get('alias', s['entity_id'])} ({s['entity_id']})\n"
        summary += f"\n**条件规则 ({len(conditions)} 条):**\n"
        for c in conditions:
            summary += f"- [{c['type']}] {c.get('label', c['id'])}\n"
        summary += f"\n**输出实体 ({len(outputs)} 个):**\n"
        for o in outputs:
            summary += f"- {o['name']} ({o['type']})\n"
        summary += f"\n**轮询间隔:** {store['scan_interval']} 秒"
        summary += f"\n**日志:** {'开启' if store['logging'] else '关闭'}"
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"summary": summary},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SensorSwitchControllerOptionsFlow(config_entry)


# ------------------------------------------------------------------
# Options Flow – incremental editing
# ------------------------------------------------------------------

class SensorSwitchControllerOptionsFlow(config_entries.OptionsFlow):
    """Options flow with full incremental condition editing."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry
        self._opts = dict(config_entry.options)

    # ---------- Main menu ----------
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            action = user_input["action"]
            if action == "interval":
                return await self.async_step_edit_interval()
            if action == "logging":
                return await self.async_step_edit_logging()
            if action == "sensors":
                return await self.async_step_edit_sensors()
            if action == "conditions":
                return await self.async_step_opt_conditions_menu()
            if action == "outputs":
                return await self.async_step_opt_outputs_menu()
        schema = vol.Schema({
            vol.Required("action"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "interval", "label": "修改轮询间隔"},
                        {"value": "logging", "label": "修改日志设置"},
                        {"value": "sensors", "label": "修改传感器池"},
                        {"value": "conditions", "label": "修改条件规则"},
                        {"value": "outputs", "label": "修改输出实体"},
                    ],
                    mode="list",
                )
            ),
        })
        return self.async_show_form(step_id="init", data_schema=schema)

    # ---------- Edit interval ----------
    async def async_step_edit_interval(self, user_input=None):
        if user_input is not None:
            self._opts[CONF_SCAN_INTERVAL] = user_input[CONF_SCAN_INTERVAL]
            return self.async_create_entry(title="", data=self._opts)
        schema = vol.Schema({
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=self._opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
        })
        return self.async_show_form(step_id="edit_interval", data_schema=schema)

    # ---------- Edit logging ----------
    async def async_step_edit_logging(self, user_input=None):
        if user_input is not None:
            self._opts[CONF_LOGGING] = user_input[CONF_LOGGING]
            return self.async_create_entry(title="", data=self._opts)
        schema = vol.Schema({
            vol.Optional(
                CONF_LOGGING,
                default=self._opts.get(CONF_LOGGING, False),
            ): bool,
        })
        return self.async_show_form(step_id="edit_logging", data_schema=schema)

    # ---------- Edit sensors ----------
    async def async_step_edit_sensors(self, user_input=None):
        current = self._opts.get(CONF_SENSORS, [])
        if user_input is not None:
            selected = user_input.get("entities", [])
            existing = {s["entity_id"]: s.get("alias", "") for s in current}
            sensors = [
                {"entity_id": eid, "alias": existing.get(eid, "")}
                for eid in selected
            ]
            self._opts[CONF_SENSORS] = sensors
            return self.async_create_entry(title="", data=self._opts)
        schema = vol.Schema({
            vol.Optional("entities", default=[s["entity_id"] for s in current]): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
        })
        return self.async_show_form(step_id="edit_sensors", data_schema=schema)

    # ================================================================
    # Conditions – incremental editing
    # ================================================================

    async def async_step_opt_conditions_menu(self, user_input=None):
        """Main condition editing hub."""
        conditions = self._opts.get(CONF_CONDITIONS, [])
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_opt_add_cond_type()
            if action == "edit":
                return await self.async_step_opt_edit_select()
            if action == "delete":
                return await self.async_step_opt_delete_select()
            if action == "done":
                return self.async_create_entry(title="", data=self._opts)
        menu_items = [f"{i+1}. [{c['type']}] {c.get('label', c['id'])}" for i, c in enumerate(conditions)]
        schema = vol.Schema({
            vol.Optional("action", default="done"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "add", "label": "➕ 添加条件"},
                        {"value": "edit", "label": "✏️ 编辑条件"},
                        {"value": "delete", "label": "🗑️ 删除条件"},
                        {"value": "done", "label": "✅ 保存并返回"},
                    ],
                    mode="list",
                )
            ),
        })
        return self.async_show_form(
            step_id="opt_conditions_menu",
            data_schema=schema,
            description_placeholders={
                "conditions_list": "\n".join(menu_items) if menu_items else "（暂无条件）",
            },
        )

    # ---------- Add condition (Options Flow) ----------
    async def async_step_opt_add_cond_type(self, user_input=None):
        if user_input is not None:
            ctype = user_input["condition_type"]
            self._opts["_pending_cond_type"] = ctype
            if ctype == COND_NUMERIC_STATE:
                return await self.async_step_opt_cond_numeric()
            if ctype == COND_STATE:
                return await self.async_step_opt_cond_state()
            if ctype == COND_TIME:
                return await self.async_step_opt_cond_time()
            if ctype == COND_SUN:
                return await self.async_step_opt_cond_sun()
            if ctype == COND_TEMPLATE:
                return await self.async_step_opt_cond_template()
            if ctype in (COND_AND, COND_OR):
                return await self.async_step_opt_cond_group()
        schema = vol.Schema({
            vol.Required("condition_type"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": COND_NUMERIC_STATE, "label": "数值比较 (numeric_state)"},
                        {"value": COND_STATE, "label": "状态匹配 (state)"},
                        {"value": COND_TIME, "label": "时间范围 (time)"},
                        {"value": COND_SUN, "label": "日出日落 (sun)"},
                        {"value": COND_TEMPLATE, "label": "模板表达式 (template)"},
                        {"value": COND_AND, "label": "AND 组合"},
                        {"value": COND_OR, "label": "OR 组合"},
                    ],
                    mode="list",
                )
            ),
        })
        return self.async_show_form(step_id="opt_add_cond_type", data_schema=schema)

    # ---------- Edit condition – select which one ----------
    async def async_step_opt_edit_select(self, user_input=None):
        conditions = self._opts.get(CONF_CONDITIONS, [])
        cond_options = _condition_options(conditions)
        if user_input is not None:
            cid = user_input["cond_id"]
            self._opts["_editing_cond_id"] = cid
            cond = next((c for c in conditions if c["id"] == cid), None)
            if not cond:
                return await self.async_step_opt_conditions_menu()
            ctype = cond["type"]
            if ctype == COND_NUMERIC_STATE:
                return await self.async_step_opt_edit_numeric()
            if ctype == COND_STATE:
                return await self.async_step_opt_edit_state()
            if ctype == COND_TIME:
                return await self.async_step_opt_edit_time()
            if ctype == COND_SUN:
                return await self.async_step_opt_edit_sun()
            if ctype == COND_TEMPLATE:
                return await self.async_step_opt_edit_template()
            if ctype in (COND_AND, COND_OR):
                return await self.async_step_opt_edit_group()
        schema = vol.Schema({
            vol.Required("cond_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cond_options, mode="dropdown")
            ),
        })
        return self.async_show_form(step_id="opt_edit_select", data_schema=schema)

    # ---------- Delete condition ----------
    async def async_step_opt_delete_select(self, user_input=None):
        conditions = self._opts.get(CONF_CONDITIONS, [])
        cond_options = _condition_options(conditions)
        if user_input is not None:
            cid = user_input["cond_id"]
            self._opts[CONF_CONDITIONS] = [c for c in conditions if c["id"] != cid]
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Required("cond_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cond_options, mode="dropdown")
            ),
        })
        return self.async_show_form(step_id="opt_delete_select", data_schema=schema)

    # ================================================================
    # Options Flow – Add condition forms
    # ================================================================

    async def async_step_opt_cond_numeric(self, user_input=None):
        sensors = self._opts.get(CONF_SENSORS, [])
        sensor_options = _sensor_options(sensors)
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_NUMERIC_STATE,
                "label": user_input.get("label", "数值条件"),
                "entity_id": user_input["entity_id"],
                "above": user_input.get("above"),
                "below": user_input.get("below"),
            }
            if user_input.get("for_enabled"):
                cond["for"] = {
                    "hours": user_input.get("for_hours", 0),
                    "minutes": user_input.get("for_minutes", 0),
                    "seconds": user_input.get("for_seconds", 0),
                }
            self._opts.setdefault(CONF_CONDITIONS, []).append(cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="数值条件"): str,
            vol.Required("entity_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=sensor_options, mode="dropdown")
            ),
            vol.Optional("above"): vol.Any(vol.Coerce(float), None),
            vol.Optional("below"): vol.Any(vol.Coerce(float), None),
            vol.Optional("for_enabled", default=False): bool,
            vol.Optional("for_hours", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=24)),
            vol.Optional("for_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
            vol.Optional("for_seconds", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        })
        return self.async_show_form(step_id="opt_cond_numeric", data_schema=schema)

    async def async_step_opt_cond_state(self, user_input=None):
        sensors = self._opts.get(CONF_SENSORS, [])
        sensor_options = _sensor_options(sensors)
        if user_input is not None:
            state_val = user_input["state"]
            states = [s.strip() for s in state_val.split(",")] if "," in state_val else state_val
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_STATE,
                "label": user_input.get("label", "状态条件"),
                "entity_id": user_input["entity_id"],
                "state": states if isinstance(states, list) and len(states) > 1 else state_val,
            }
            if user_input.get("for_enabled"):
                cond["for"] = {
                    "hours": user_input.get("for_hours", 0),
                    "minutes": user_input.get("for_minutes", 0),
                    "seconds": user_input.get("for_seconds", 0),
                }
            self._opts.setdefault(CONF_CONDITIONS, []).append(cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="状态条件"): str,
            vol.Required("entity_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=sensor_options, mode="dropdown")
            ),
            vol.Required("state"): str,
            vol.Optional("for_enabled", default=False): bool,
            vol.Optional("for_hours", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=24)),
            vol.Optional("for_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
            vol.Optional("for_seconds", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        })
        return self.async_show_form(step_id="opt_cond_state", data_schema=schema)

    async def async_step_opt_cond_time(self, user_input=None):
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_TIME,
                "label": user_input.get("label", "时间条件"),
            }
            if user_input.get("after"):
                cond["after"] = user_input["after"]
            if user_input.get("before"):
                cond["before"] = user_input["before"]
            self._opts.setdefault(CONF_CONDITIONS, []).append(cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="时间条件"): str,
            vol.Optional("after"): selector.TimeSelector(),
            vol.Optional("before"): selector.TimeSelector(),
        })
        return self.async_show_form(step_id="opt_cond_time", data_schema=schema)

    async def async_step_opt_cond_sun(self, user_input=None):
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_SUN,
                "label": user_input.get("label", "日出日落条件"),
            }
            if user_input.get("after"):
                cond["after"] = user_input["after"]
                off = user_input.get("after_offset", 0)
                if off != 0:
                    cond["after_offset"] = off
            if user_input.get("before"):
                cond["before"] = user_input["before"]
                off = user_input.get("before_offset", 0)
                if off != 0:
                    cond["before_offset"] = off
            self._opts.setdefault(CONF_CONDITIONS, []).append(cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="日出日落条件"): str,
            vol.Optional("after"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "", "label": "（不限制）"},
                        {"value": "sunrise", "label": "日出后"},
                        {"value": "sunset", "label": "日落后"},
                    ],
                    mode="dropdown",
                )
            ),
            vol.Optional("after_offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=-86400, max=86400)),
            vol.Optional("before"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "", "label": "（不限制）"},
                        {"value": "sunrise", "label": "日出前"},
                        {"value": "sunset", "label": "日落前"},
                    ],
                    mode="dropdown",
                )
            ),
            vol.Optional("before_offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=-86400, max=86400)),
        })
        return self.async_show_form(step_id="opt_cond_sun", data_schema=schema)

    async def async_step_opt_cond_template(self, user_input=None):
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": COND_TEMPLATE,
                "label": user_input.get("label", "模板条件"),
                "value_template": user_input["template"],
            }
            self._opts.setdefault(CONF_CONDITIONS, []).append(cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default="模板条件"): str,
            vol.Required("template"): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        })
        return self.async_show_form(step_id="opt_cond_template", data_schema=schema)

    async def async_step_opt_cond_group(self, user_input=None):
        conditions = self._opts.get(CONF_CONDITIONS, [])
        cond_options = _condition_options(conditions)
        ctype = self._opts.get("_pending_cond_type", COND_AND)
        if user_input is not None:
            cond = {
                "id": f"cond_{uuid.uuid4().hex[:6]}",
                "type": ctype,
                "label": user_input.get("label", f"{ctype.upper()} 组合"),
                "conditions": user_input.get("members", []),
            }
            self._opts.setdefault(CONF_CONDITIONS, []).append(cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default=f"{ctype.upper()} 组合"): str,
            vol.Required("members", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cond_options, multiple=True, mode="list")
            ),
        })
        return self.async_show_form(step_id="opt_cond_group", data_schema=schema)

    # ================================================================
    # Options Flow – Edit condition forms (pre-filled)
    # ================================================================

    def _get_editing_cond(self) -> dict | None:
        cid = self._opts.get("_editing_cond_id")
        conditions = self._opts.get(CONF_CONDITIONS, [])
        return next((c for c in conditions if c["id"] == cid), None)

    def _replace_cond(self, new_cond: dict) -> None:
        conditions = self._opts.get(CONF_CONDITIONS, [])
        self._opts[CONF_CONDITIONS] = [
            new_cond if c["id"] == new_cond["id"] else c for c in conditions
        ]

    async def async_step_opt_edit_numeric(self, user_input=None):
        cond = self._get_editing_cond()
        if not cond:
            return await self.async_step_opt_conditions_menu()
        sensors = self._opts.get(CONF_SENSORS, [])
        sensor_options = _sensor_options(sensors)
        for_cfg = cond.get("for", {})
        if user_input is not None:
            new_cond = dict(cond)
            new_cond["label"] = user_input.get("label", cond.get("label", ""))
            new_cond["entity_id"] = user_input["entity_id"]
            new_cond["above"] = user_input.get("above")
            new_cond["below"] = user_input.get("below")
            if user_input.get("for_enabled"):
                new_cond["for"] = {
                    "hours": user_input.get("for_hours", 0),
                    "minutes": user_input.get("for_minutes", 0),
                    "seconds": user_input.get("for_seconds", 0),
                }
            else:
                new_cond.pop("for", None)
            self._replace_cond(new_cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default=cond.get("label", "数值条件")): str,
            vol.Required("entity_id", default=cond.get("entity_id")): selector.SelectSelector(
                selector.SelectSelectorConfig(options=sensor_options, mode="dropdown")
            ),
            vol.Optional("above", default=cond.get("above")): vol.Any(vol.Coerce(float), None),
            vol.Optional("below", default=cond.get("below")): vol.Any(vol.Coerce(float), None),
            vol.Optional("for_enabled", default=bool(for_cfg)): bool,
            vol.Optional("for_hours", default=for_cfg.get("hours", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=24)),
            vol.Optional("for_minutes", default=for_cfg.get("minutes", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
            vol.Optional("for_seconds", default=for_cfg.get("seconds", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        })
        return self.async_show_form(step_id="opt_edit_numeric", data_schema=schema)

    async def async_step_opt_edit_state(self, user_input=None):
        cond = self._get_editing_cond()
        if not cond:
            return await self.async_step_opt_conditions_menu()
        sensors = self._opts.get(CONF_SENSORS, [])
        sensor_options = _sensor_options(sensors)
        for_cfg = cond.get("for", {})
        state_val = cond.get("state", "")
        default_state = ",".join(state_val) if isinstance(state_val, list) else state_val
        if user_input is not None:
            new_cond = dict(cond)
            new_cond["label"] = user_input.get("label", cond.get("label", ""))
            new_cond["entity_id"] = user_input["entity_id"]
            sval = user_input["state"]
            states = [s.strip() for s in sval.split(",")] if "," in sval else sval
            new_cond["state"] = states if isinstance(states, list) and len(states) > 1 else sval
            if user_input.get("for_enabled"):
                new_cond["for"] = {
                    "hours": user_input.get("for_hours", 0),
                    "minutes": user_input.get("for_minutes", 0),
                    "seconds": user_input.get("for_seconds", 0),
                }
            else:
                new_cond.pop("for", None)
            self._replace_cond(new_cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default=cond.get("label", "状态条件")): str,
            vol.Required("entity_id", default=cond.get("entity_id")): selector.SelectSelector(
                selector.SelectSelectorConfig(options=sensor_options, mode="dropdown")
            ),
            vol.Required("state", default=default_state): str,
            vol.Optional("for_enabled", default=bool(for_cfg)): bool,
            vol.Optional("for_hours", default=for_cfg.get("hours", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=24)),
            vol.Optional("for_minutes", default=for_cfg.get("minutes", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
            vol.Optional("for_seconds", default=for_cfg.get("seconds", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        })
        return self.async_show_form(step_id="opt_edit_state", data_schema=schema)

    async def async_step_opt_edit_time(self, user_input=None):
        cond = self._get_editing_cond()
        if not cond:
            return await self.async_step_opt_conditions_menu()
        if user_input is not None:
            new_cond = dict(cond)
            new_cond["label"] = user_input.get("label", cond.get("label", ""))
            if user_input.get("after"):
                new_cond["after"] = user_input["after"]
            else:
                new_cond.pop("after", None)
            if user_input.get("before"):
                new_cond["before"] = user_input["before"]
            else:
                new_cond.pop("before", None)
            self._replace_cond(new_cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default=cond.get("label", "时间条件")): str,
            vol.Optional("after", default=cond.get("after")): selector.TimeSelector(),
            vol.Optional("before", default=cond.get("before")): selector.TimeSelector(),
        })
        return self.async_show_form(step_id="opt_edit_time", data_schema=schema)

    async def async_step_opt_edit_sun(self, user_input=None):
        cond = self._get_editing_cond()
        if not cond:
            return await self.async_step_opt_conditions_menu()
        if user_input is not None:
            new_cond = dict(cond)
            new_cond["label"] = user_input.get("label", cond.get("label", ""))
            if user_input.get("after"):
                new_cond["after"] = user_input["after"]
                off = user_input.get("after_offset", 0)
                if off != 0:
                    new_cond["after_offset"] = off
                else:
                    new_cond.pop("after_offset", None)
            else:
                new_cond.pop("after", None)
                new_cond.pop("after_offset", None)
            if user_input.get("before"):
                new_cond["before"] = user_input["before"]
                off = user_input.get("before_offset", 0)
                if off != 0:
                    new_cond["before_offset"] = off
                else:
                    new_cond.pop("before_offset", None)
            else:
                new_cond.pop("before", None)
                new_cond.pop("before_offset", None)
            self._replace_cond(new_cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default=cond.get("label", "日出日落条件")): str,
            vol.Optional("after", default=cond.get("after", "")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "", "label": "（不限制）"},
                        {"value": "sunrise", "label": "日出后"},
                        {"value": "sunset", "label": "日落后"},
                    ],
                    mode="dropdown",
                )
            ),
            vol.Optional("after_offset", default=cond.get("after_offset", 0)): vol.All(vol.Coerce(int), vol.Range(min=-86400, max=86400)),
            vol.Optional("before", default=cond.get("before", "")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "", "label": "（不限制）"},
                        {"value": "sunrise", "label": "日出前"},
                        {"value": "sunset", "label": "日落前"},
                    ],
                    mode="dropdown",
                )
            ),
            vol.Optional("before_offset", default=cond.get("before_offset", 0)): vol.All(vol.Coerce(int), vol.Range(min=-86400, max=86400)),
        })
        return self.async_show_form(step_id="opt_edit_sun", data_schema=schema)

    async def async_step_opt_edit_template(self, user_input=None):
        cond = self._get_editing_cond()
        if not cond:
            return await self.async_step_opt_conditions_menu()
        if user_input is not None:
            new_cond = dict(cond)
            new_cond["label"] = user_input.get("label", cond.get("label", ""))
            new_cond["value_template"] = user_input["template"]
            self._replace_cond(new_cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default=cond.get("label", "模板条件")): str,
            vol.Required("template", default=cond.get("value_template", "")): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        })
        return self.async_show_form(step_id="opt_edit_template", data_schema=schema)

    async def async_step_opt_edit_group(self, user_input=None):
        cond = self._get_editing_cond()
        if not cond:
            return await self.async_step_opt_conditions_menu()
        conditions = self._opts.get(CONF_CONDITIONS, [])
        cond_options = _condition_options(conditions)
        if user_input is not None:
            new_cond = dict(cond)
            new_cond["label"] = user_input.get("label", cond.get("label", ""))
            new_cond["conditions"] = user_input.get("members", [])
            self._replace_cond(new_cond)
            return await self.async_step_opt_conditions_menu()
        schema = vol.Schema({
            vol.Optional("label", default=cond.get("label", "组合条件")): str,
            vol.Required("members", default=cond.get("conditions", [])): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cond_options, multiple=True, mode="list")
            ),
        })
        return self.async_show_form(step_id="opt_edit_group", data_schema=schema)

    # ================================================================
    # Outputs – incremental editing
    # ================================================================

    async def async_step_opt_outputs_menu(self, user_input=None):
        outputs = self._opts.get(CONF_OUTPUTS, [])
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_opt_add_output()
            if action == "delete":
                return await self.async_step_opt_delete_output()
            if action == "done":
                return self.async_create_entry(title="", data=self._opts)
        out_lines = [f"{i+1}. {o['name']} ({o['type']})" for i, o in enumerate(outputs)]
        schema = vol.Schema({
            vol.Optional("action", default="done"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": "add", "label": "➕ 添加输出实体"},
                        {"value": "delete", "label": "🗑️ 删除输出实体"},
                        {"value": "done", "label": "✅ 保存并返回"},
                    ],
                    mode="list",
                )
            ),
        })
        return self.async_show_form(
            step_id="opt_outputs_menu",
            data_schema=schema,
            description_placeholders={
                "outputs_list": "\n".join(out_lines) if out_lines else "（暂无输出实体）",
            },
        )

    async def async_step_opt_add_output(self, user_input=None):
        conditions = self._opts.get(CONF_CONDITIONS, [])
        cond_options = _condition_options(conditions)
        if user_input is not None:
            out = {
                "name": user_input["name"],
                "type": user_input["output_type"],
                "entity_id": f"ssc_{uuid.uuid4().hex[:6]}",
                "on_conditions": user_input.get("on_conditions", []),
                "off_conditions": user_input.get("off_conditions", []),
                "manual_override": user_input.get("manual_override", False),
            }
            self._opts.setdefault(CONF_OUTPUTS, []).append(out)
            return await self.async_step_opt_outputs_menu()
        schema = vol.Schema({
            vol.Optional("name", default="逻辑开关"): str,
            vol.Optional("output_type", default=OUTPUT_SWITCH): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": OUTPUT_SWITCH, "label": "开关 (Switch)"},
                        {"value": OUTPUT_BINARY_SENSOR, "label": "二进制传感器 (Binary Sensor)"},
                    ],
                    mode="dropdown",
                )
            ),
            vol.Optional("on_conditions", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cond_options, multiple=True, mode="list")
            ),
            vol.Optional("off_conditions", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=cond_options, multiple=True, mode="list")
            ),
            vol.Optional("manual_override", default=False): bool,
        })
        return self.async_show_form(step_id="opt_add_output", data_schema=schema)

    async def async_step_opt_delete_output(self, user_input=None):
        outputs = self._opts.get(CONF_OUTPUTS, [])
        out_options = [
            {"value": o["entity_id"], "label": f"{o['name']} ({o['type']})"}
            for o in outputs
        ]
        if user_input is not None:
            eid = user_input["entity_id"]
            self._opts[CONF_OUTPUTS] = [o for o in outputs if o["entity_id"] != eid]
            return await self.async_step_opt_outputs_menu()
        schema = vol.Schema({
            vol.Required("entity_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=out_options, mode="dropdown")
            ),
        })
        return self.async_show_form(step_id="opt_delete_output", data_schema=schema)
