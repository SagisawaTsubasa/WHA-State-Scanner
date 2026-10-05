# HA 全屋状态扫描 / HA Whole-House State Scanner

> **零 YAML 全屋状态扫描器：可视化流程图编辑中间层决策，传感器池 + 条件规则 + 多路输出 + 独立决策日志。**
>
> A zero-YAML whole-house state scanner: edit your sensor→decision middle layer as a visual flow graph — sensor pools, condition rules, multiple outputs, and an independent decision log.

> **Programmer:** [Kimi](https://kimi.moonshot.cn) (Moonshot AI) · **Author:** [@SagisawaTsubasa](https://github.com/SagisawaTsubasa)

---

## 功能 / Features

- **侧边栏 Web 管理页** — 无需 YAML：总览 / 流程图编辑器 / 决策日志三个视图，全部内置、零 CDN、离线可用
- **可视化流程图编辑器** — 条件→组→输出拖线连线（Drawflow），节点点击即改参数，试运行实时染色（绿=满足/红=不满足/输出徽章显示决策）
- **传感器池** — 一个控制器可引用任意数量的实体；总览页有全局传感器池视图，共享传感器高亮
- **条件规则库** — `numeric_state`、`state`、`time`、`sun`、`template`，支持 `AND`/`OR` 嵌套组合与 `FOR` 持续计时
- **多路输出** — 一个控制器可生成多个开关或二进制传感器；`off_conditions` 优先于 `on_conditions`（防抖动）
- **决策日志** — 每周期逐输出写入独立 JSONL（含传感器读数快照、applied/override 标记），面板内可直接查询
- **手动覆盖** — 开关类型支持可选的手动强制控制
- **零构建前端** — 集成自带全部静态资源（vendored Drawflow），无 Node 工具链、无外网依赖

---

- **Sidebar web panel** — overview / visual flow editor / decision-log viewer, fully built-in, zero CDN
- **Visual flow editor** — wire condition→group→output on a Drawflow canvas; click a node to edit it; trial runs color nodes live (green=met / red=unmet, decision badges on outputs)
- **Sensor pool** — any number of entities per controller; a global pool view highlights sensors shared across controllers
- **Condition library** — `numeric_state`, `state`, `time`, `sun`, `template`, plus `AND`/`OR` nesting and `FOR` durations
- **Multiple outputs** — switches and binary sensors per controller; `off_conditions` win over `on_conditions` (anti-flapping)
- **Decision log** — per-cycle JSONL with sensor readings, applied/override flags; queryable in the panel
- **Manual override** — optional per-switch manual control lock
- **Zero-build frontend** — all static assets vendored (Drawflow); no Node toolchain, no external requests

---

## 安装 / Installation

### HACS（推荐）

1. 在 HACS 中添加此仓库为自定义仓库。
2. 安装 **HA 全屋状态扫描**。
3. 重启 Home Assistant。
4. **设置 → 设备与服务 → 添加集成**，搜索 **HA 全屋状态扫描**，一键创建全局条目。
5. 侧边栏出现 **全屋状态扫描** 面板——所有控制器都在这里创建和编辑。

### 手动安装

1. 将 `custom_components/sensor_switch_controller` 复制到 Home Assistant 的 `custom_components` 目录。
2. 重启 Home Assistant，按上述步骤添加集成并使用侧边栏面板。

---

### HACS (Recommended)

1. Add this repository as a custom repository in HACS.
2. Install **HA Whole-House State Scanner**.
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration** → search **HA Whole-House State Scanner** and create the single entry.
5. A **Whole-House State Scanner** panel appears in the sidebar — create and edit all controllers there.

### Manual

1. Copy `custom_components/sensor_switch_controller` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant and add the integration as above.

---

## Web 管理页 / Web Panel

| 视图 / View | 内容 / Content |
|-------------|----------------|
| **总览 / Overview** | 控制器卡片（输出实时状态、立即评估、启停、删除）+ 全局传感器池视图 / Controller cards with live output states + global sensor pool view |
| **编辑器 / Editor** | Drawflow 流程画布：条件/组/输出节点拖线连线，右侧 inspector 编辑参数，顶部保存与试运行 / Flow canvas with condition/group/output nodes, inspector forms, save & trial run |
| **决策日志 / Logs** | 按控制器+日期查询 JSONL 决策记录，可按 decision 过滤，读数快照可展开 / Query JSONL records by controller+date, filter by decision, expandable readings |

**编辑器节点语义 / Node semantics:**

- 条件节点（六类叶子）→ 用连线加入 **AND/OR 组**（成员可进多组）
- 组或顶层条件连线到**输出节点**的两个输入端口：`input_1` = 满足则开（on_conditions），`input_2` = 满足则关（off_conditions，**优先**）
- **试运行**与正式评估语义完全相同（会实际写输出实体、写决策日志），并把每个条件的满足结果染色到节点上
- 保存后控制器整条重载，FOR 计时器清零

**REST API**（面板使用，亦可脚本调用，均需鉴权）：

```
GET    /api/sensor_switch_controller/config
POST   /api/sensor_switch_controller/controllers          # 创建（body 为控制器 JSON）
PUT    /api/sensor_switch_controller/controllers/{id}     # 更新
DELETE /api/sensor_switch_controller/controllers/{id}
POST   /api/sensor_switch_controller/controllers/{id}/evaluate   # 立即评估（带逐条件结果）
GET    /api/sensor_switch_controller/logs?controller_id=&date=YYYY-MM-DD&decision=on|off|hold&limit=500
```

---

## 独立日志系统 / Independent Logging

开启日志后，每次评估在专用 JSONL 文件中追加记录（按控制器分目录、按日轮转、保留 30 天）：

```
<HA_CONFIG>/sensor_switch_controller_logs/<controller_id>/log_YYYY-MM-DD.jsonl
```

**示例记录 / Example record：**

```json
{"timestamp":"2026-10-05T14:30:00+08:00","controller":"浴室湿度控制","output":"湿度控制使能","decision":"off","on_met":false,"off_met":true,"applied":true,"override":false,"readings":{"sensor.shi_du_chai_zhi":"8.2"}}
```

- `decision` 为条件判定结果（on/off/hold，hold 也记录——"为什么没动作"同样有据可查）
- `applied` 表示判定是否实际写入实体；`override` 表示该写入被手动覆盖拦截
- `readings` 是本周期传感器池的完整读数快照

---

## 架构 / Architecture

```
Config Entry（单一条目 / single entry）
├── Store                → 全部控制器配置（hub.SannerHub, storage.Store）
├── ControllerManager    → 每控制器一个：轮询调度 + 评估 + 实体注册（controller.py）
├── Condition Engine     → 六类叶子 + AND/OR 嵌套 + FOR 计时 + 逐条件追踪（condition_engine.py）
├── Output Platforms     → switch / binary_sensor（每控制器一个设备）
├── Web Layer            → 侧边栏面板 + REST API + 静态资源（web.py + static/）
└── Decision Logger      → 独立 JSONL（decision_log.py）
```

**核心组件 / Key Components：**

| 文件 / File | 职责 / Purpose |
|-------------|----------------|
| `hub.py` | 域级单例：Store 读写、控制器 CRUD、运行时快照 / Domain singleton: store, controller CRUD, snapshots |
| `controller.py` | 轮询、评估（含 applied/override 记录）、试运行 API / Polling, evaluation, trial-run API |
| `condition_engine.py` | 递归条件评估（六类叶子 + 嵌套 + FOR 计时器 + detail 追踪）/ Recursive evaluator |
| `schema.py` | 共享校验（Web API 与 config flow 同源）/ Shared validation |
| `web.py` | REST views、面板注册、静态资源 / REST views, panel & static registration |
| `static/panel.js` | 面板前端（零构建自定义元素 + Drawflow）/ Zero-build panel frontend |
| `decision_log.py` | 按日轮转 JSONL 日志 / File-based JSONL logger |
| `config_flow.py` | 单步创建全局条目 / Single-step entry creation |

---

## 服务 / Service

### `sensor_switch_controller.force_evaluate`

立即触发指定输出实体的条件评估（不影响轮询定时器）。

```yaml
service: sensor_switch_controller.force_evaluate
target:
  entity_id: switch.humidity_control_enable
```

---

## 兼容性 / Compatibility

- Home Assistant **2024.11+**（Web 面板在 2026.1 实测）
- Python **3.12+**

---

## 许可证 / License

MIT

---

*Built with [Kimi](https://kimi.moonshot.cn) by Moonshot AI · Author: [@SagisawaTsubasa](https://github.com/SagisawaTsubasa)*

## 更新日志 / Changelog

### 0.4.2
- **手机/窄屏支持（只读）**：总览单列、表格长 ID 自动换行（无横向溢出）；编辑器在窄屏切"查看模式"——隐藏全部编辑控件，画布占满并带 ＋/－/⌂ 缩放浮钮（Drawflow 原生触摸平移/拖线），提示"编辑请用电脑"；桌面布局不变
  Mobile/narrow-screen support (read-only): single-column overview, wrapping tables (no horizontal overflow); the editor switches to a read-only canvas view with zoom buttons — editing stays on desktop

### 0.4.1
- 修复：带路径参数的 REST 接口（PUT/DELETE 控制器、试运行）必 500——aiohttp 把 URL 变量以关键字参数传入 handler，而方法签名未接收（mock 环境抓不到，实机冒烟暴露）
  Fixed: path-param REST endpoints (controller PUT/DELETE, trial-run) always 500 — aiohttp passes URL vars as kwargs which the handler signatures did not accept

### 0.4.0
- **侧边栏 Web 管理页**：总览 / 可视化流程图编辑器 / 决策日志三视图；条件→组→输出拖线连线（vendored Drawflow，零 CDN 零构建），节点点击编辑参数，试运行实时染色（绿=满足/红=不满足/输出决策徽章）
- **存储重构**：由"每控制器一个 config entry"改为单一条目 + `storage.Store`；config flow 瘦身为单步确认，旧 5 步向导与 Options Flow 退役，Web 页成为唯一编辑器
- **REST API**：`/api/sensor_switch_controller/*` 全套（config/controllers CRUD/evaluate/logs），共享 voluptuous 校验（组引用、防环、输出引用完整性）
- **决策日志增强**：record 新增 `applied`（判定是否实际写入）与 `override`（被手动覆盖拦截）字段；日志目录由 entry_id 改为 controller_id 键控；新增面板内日志查询
- **全局传感器池总览**：跨控制器共享传感器高亮
- 传感器 `alias` 字段启用（此前无 UI 可写入）；控制器新增 `enabled` 停用开关
- services.yaml 去硬编码文案，接入翻译体系（name/description 进 translations）
- ⚠ 存储版本升级（1→2）：旧版按 entry 创建的控制器配置不会自动迁移（0.4.0 前该集成无已配置条目，无实际迁移需求）

### 0.3.2
- 修复：config flow 创建条目时配置丢失——HA 2026 起创建期 options 不再落地。向导结果现在写入 data，首次启动镜像到 options
  Fixed: config entries were created empty — the wizard result now goes into data and is mirrored to options on first setup

### 0.3.1
- 修复：自研决策日志模块与 HA logbook 平台自动发现撞名（AttributeError 连累输出实体创建），模块更名 `decision_log.py`
  Fixed: the in-house decision-logger collided with HA's logbook platform discovery; renamed to `decision_log.py`

### 0.3.0
- Config/Options Flow 全量接入 HA 翻译体系（93 处硬编码中文清除）；确认页摘要重构；`translations/en.json` 补齐；manifest `loggers` 规范化；ruff 告警清零
  Full i18n of the flows via translation keys; reworked confirmation summary; loggers array; ruff clean

### 0.2.0 / 0.1.0（2026-09-05 审计修复批次）
- 实体注册/查找键、组条件求值、options 重载等 11 项高级别问题与全部中低项修复
  September audit fixes: entity registration, group condition evaluation, options reload, and all medium/low items
