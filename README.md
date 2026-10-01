# HA 全屋状态扫描 / HA Whole-House State Scanner

> **零 YAML 可视化全屋状态扫描器，自由组合任意传感器条件，实时驱动多路输出。**
> 
> A zero-YAML visual whole-house state scanner — freely compose any sensor conditions and drive multiple outputs in real time.

> **Programmer:** [Kimi](https://kimi.moonshot.cn) (Moonshot AI) · **Author:** [@SagisawaTsubasa](https://github.com/SagisawaTsubasa)

---

## 功能 / Features

- **纯 UI 配置** — 5 步向导，零 YAML
- **传感器池** — 一个控制器可引用任意数量的实体
- **条件规则库** — `numeric_state`、`state`、`time`、`sun`、`template`，支持 `AND`/`OR` 嵌套组合
- **增量编辑** — 创建后仍可随时添加、编辑、删除条件规则和输出实体
- **多路输出** — 一个控制器可生成多个开关或二进制传感器
- **FOR 持续时间** — 内置状态持续计时器
- **独立日志** — 决策日志写入专用 JSONL 文件（按日轮转），不混入 HA 系统日志
- **手动覆盖** — 开关类型支持可选的手动强制控制
- **热重载** — 选项修改后立即生效，无需重启

---

- **Pure UI Configuration** — 5-step wizard, zero YAML
- **Sensor Pool** — Reference any number of entities in a single controller
- **Condition Library** — `numeric_state`, `state`, `time`, `sun`, `template`, plus `AND`/`OR` nesting
- **Incremental Editing** — Add, edit, or delete conditions and outputs after creation
- **Multiple Outputs** — One controller can drive multiple switches or binary sensors
- **FOR Duration** — Built-in state-persistence timer support
- **Independent Logging** — Decision logs written to dedicated JSONL files (daily rotation), never mixed into `home-assistant.log`
- **Manual Override** — Optional per-switch manual control lock
- **Hot Reload** — Options changes take effect immediately without restart

---

## 安装 / Installation

### HACS（推荐）

1. 在 HACS 中添加此仓库为自定义仓库。
2. 安装 **HA 全屋状态扫描**。
3. 重启 Home Assistant。

### 手动安装

1. 将 `custom_components/sensor_switch_controller` 复制到 Home Assistant 的 `custom_components` 目录。
2. 重启 Home Assistant。
3. 进入 **设置 → 设备与服务 → 添加集成**，搜索 **HA 全屋状态扫描**。

---

### HACS (Recommended)

1. Add this repository as a custom repository in HACS.
2. Install **HA Whole-House State Scanner**.
3. Restart Home Assistant.

### Manual

1. Copy `custom_components/sensor_switch_controller` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **HA Whole-House State Scanner**.

---

## 配置向导 / Configuration Wizard

### 第一步：基础设置 / Step 1: Basic Settings

- **名称 / Name**：如 `浴室湿度控制` / `Bathroom Humidity Control`
- **轮询间隔 / Scan Interval**：评估频率（秒），默认 180
- **启用日志 / Enable Logging**：是否记录每次决策到独立文件

### 第二步：传感器池 / Step 2: Sensor Pool

- 多选所有参与逻辑判断的实体。
- Multi-select any entities that will participate in logic evaluation.

### 第三步：条件规则 / Step 3: Condition Rules

点击"添加条件"，选择类型：

| 类型 / Type | 说明 / Description |
|-------------|--------------------|
| **数值比较 / Numeric State** | 传感器数值与 `above` / `below` 阈值比较 |
| **状态匹配 / State** | 匹配精确状态字符串（逗号分隔多状态），可选 `FOR` 持续时间 |
| **时间范围 / Time** | 限制在 `after` / `before` 时间范围内 |
| **日出日落 / Sun** | 基于日出日落判断，偏移量单位为秒（负数表示提前） |
| **模板表达式 / Template** | 完整 Jinja2 模板表达式 |
| **AND / OR 组合 / Group** | 将已有条件组合为嵌套逻辑 |

顶层条件之间默认 **OR** 关系（任一满足即触发）。

Top-level conditions are evaluated with **OR** logic (any one satisfied triggers).

### 第四步：输出实体 / Step 4: Output Entities

每个控制器可生成多个输出：
- **开关 / Switch**：可切换实体，可选手动覆盖
- **二进制传感器 / Binary Sensor**：只读状态指示器
- 绑定 `on_conditions` 和 `off_conditions`（`off_conditions` 优先级高于 `on_conditions`，防止抖动）

### 第五步：确认 / Step 5: Confirm

预览所有配置后创建。

---

## 修改配置（增量编辑）/ Editing After Creation

进入 **设置 → 设备与服务 → HA 全屋状态扫描 → 配置 → 选项**。

Go to **Settings → Devices & Services → HA Whole-House State Scanner → Configure → Options**.

| 项目 / Item | 支持操作 / Operations |
|-------------|------------------------|
| 轮询间隔 / Scan Interval | 直接修改 / Direct edit |
| 日志开关 / Logging | 直接修改 / Toggle on/off |
| 传感器池 / Sensor Pool | 直接修改（注意：可能使现有条件失效）/ Direct edit |
| **条件规则 / Condition Rules** | **添加 / 编辑 / 删除（预填充表单）/ Add / Edit / Delete** |
| **输出实体 / Output Entities** | **添加 / 删除 / Add / Delete** |

所有修改热重载，无需重启。

All changes are hot-reloaded. No restart required.

---

## 独立日志系统 / Independent Logging

开启日志后，每次评估在专用 JSONL 文件中追加记录：

When enabled, every evaluation cycle is appended to a dedicated JSONL file:

```
<HA_CONFIG>/sensor_switch_controller_logs/<entry_id>/<控制器名>_<YYYY-MM-DD>.jsonl
```

**示例记录 / Example record：**

```json
{"timestamp":"2026-07-16T14:30:00+08:00","controller":"Bathroom Humidity Control","output":"Dehumidifier Enable","decision":"on","on_met":true,"off_met":false,"readings":{"sensor.humidity_diff":"25.3","switch.ventilation":"off"}}
```

**日志特点 / Properties：**
- 按日期自动轮转 / Daily file rotation
- JSON Lines 格式，可用 `jq`、Python 或任何文本工具解析 / JSON Lines format — parseable with `jq`, Python, or any text tool
- 完全不写入 HA 系统日志，不污染 `home-assistant.log` / Completely isolated from Home Assistant system logs

---

## 架构 / Architecture

```
Config Entry（一个控制器 / One Controller）
├── Sensor Pool          → 任意实体引用 / Any entity references
├── Condition Engine     → 模块化评估 + FOR 计时器 / Modular evaluation + FOR timer
├── Output Entities      → switch / binary_sensor（任意数量 / any quantity）
└── Decision Logger      → 独立文件日志（按日轮转 / daily rotation）
```

**核心组件 / Key Components：**

| 文件 / File | 职责 / Purpose |
|-------------|----------------|
| `controller.py` | 调度轮询、评估、实体注册、热重载 / Orchestrates polling, evaluation, registration, hot reload |
| `condition_engine.py` | 递归条件评估器（6 种叶子类型 + AND/OR 嵌套 + FOR 计时器）/ Recursive evaluator (6 leaf types + nesting + FOR timers) |
| `logbook.py` | 基于文件的 JSONL 日志（按日轮转）/ File-based JSONL logger with daily rotation |
| `config_flow.py` | 5 步向导 + 完整增量 Options Flow / 5-step wizard + incremental Options Flow |
| `switch.py` / `binary_sensor.py` | 输出平台（控制器驱动状态更新）/ Output platforms with controller-driven updates |

---

## 服务 / Service

### `sensor_switch_controller.force_evaluate`

立即触发指定控制器的条件评估（不影响轮询定时器）。

Manually trigger an evaluation cycle for a specific controller.

```yaml
service: sensor_switch_controller.force_evaluate
target:
  entity_id: switch.bathroom_humidity_control_dehumidifier_enable
```

---

## 可扩展性 / Extensibility

框架设计便于扩展：

- **新条件类型**：在 `condition_engine.py::_evaluate_leaf()` 中添加分支
- **新输出类型**：在 `const.py` 中注册，在对应平台文件中实现
- **动作输出**（未来）：直接调用服务（如 `fan.set_percentage`），无需中间实体

The framework is designed for easy extension:

- **New Condition Types**: Add a branch in `condition_engine.py::_evaluate_leaf()`
- **New Output Types**: Register in `const.py` and implement the corresponding platform file
- **Action Outputs** (future): Direct service calls without intermediate entities

---

## 兼容性 / Compatibility

- Home Assistant **2024.1+**
- Python **3.12+**

---

## 许可证 / License

MIT

---

*Built with [Kimi](https://kimi.moonshot.cn) by Moonshot AI · Author: [@SagisawaTsubasa](https://github.com/SagisawaTsubasa)*

## 更新日志 / Changelog

### 0.3.0
- 国际化：Config/Options Flow 全量接入 HA 翻译体系——全部菜单/条件类型/输出类型/字段标签改为 translation_key + selector 翻译段，中英双语界面完整（此前 93 处硬编码中文）  
  i18n: the full config/options flow now uses the HA translation system — menus, condition/output types and field labels moved to translation keys with selector sections (93 hardcoded Chinese strings removed)
- 确认页摘要重构：段落文案进翻译模板，值列表保持语言中性  
  Reworked the confirmation summary: section text moved into translation templates, value lists stay language-neutral
- 默认标签改为语言中性的条件类型 ID；日出日落「不限制」哨兵值由空串改为 `none`（存储兼容：空串从未被持久化）  
  Default labels now use neutral condition-type IDs; the sun boundary "no limit" sentinel changed from empty string to `none` (storage-compatible)
- 新增 `translations/en.json`（HA 运行时只读 translations 目录）；修正 manifest `loggers` 为规范的字符串数组  
  Added `translations/en.json` (HA runtime only reads the translations dir); fixed manifest `loggers` to the spec string array
- 清理：ruff 告警清零（import、否定条件直返、模板渲染异常豁免注释）  
  Chores: ruff warnings cleared
- 评估记录：审计遗留 L1（errors 死变量）、L10（FLOW_DATA/_config 死代码）、L13（register/unregister 配对）均已在 9 月 V0.1.0 重构中解决，本批复核确认  
  Note: audit leftovers L1/L10/L13 were already resolved in the September V0.1.0 rewrite — re-verified this batch

### 0.2.0 / 0.1.0（2026-09-05 审计修复批次）
- 实体注册/查找键、组条件求值、options 重载等 11 项高级别问题与全部中低项修复  
  September audit fixes: entity registration, group condition evaluation, options reload, and all medium/low items

### 0.3.1
- 修复：自研决策日志模块 `logbook.py` 与 HA logbook 平台的自动发现机制撞名——HA 每次启动调用 `async_describe_events` 报 AttributeError，且连累输出实体创建。模块更名为 `decision_log.py`（纯内部改名，无存储/配置影响）  
  Fixed: the in-house decision-logger module `logbook.py` collided with HA's logbook platform auto-discovery — every boot raised AttributeError for `async_describe_events` and broke output entity creation. Renamed to `decision_log.py` (internal rename only)

### 0.3.2
- 修复：config flow 创建条目时配置丢失——HA 2026 起创建期 options 不再落地，条目表面 loaded 实则为空壳（输出实体永不创建，这也是本集成历史上"配置总是失败"的深层原因之一）。现配置写入 data，首次启动镜像到 options，运行时零改动  
  Fixed: config entries were created empty — HA 2026 no longer persists creation-time options. The wizard result now goes into data and is mirrored to options on first setup
