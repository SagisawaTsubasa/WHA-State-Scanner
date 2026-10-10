# HA 全屋状态扫描 / HA Whole-House State Scanner

> **零 YAML 全屋状态扫描器：可视化流程图编辑中间层决策，传感器池 + 条件规则 + 多路输出 + 独立决策日志。**
>
> A zero-YAML whole-house state scanner: edit your sensor→decision middle layer as a visual flow graph — sensor pools, condition rules, multiple outputs, and an independent decision log.

> **Programmer:** [Kimi](https://kimi.moonshot.cn) (Moonshot AI) · **Author:** [@SagisawaTsubasa](https://github.com/SagisawaTsubasa)

---

## 功能 / Features

- **侧边栏 Web 管理页** — 无需 YAML：总览 / 流程图编辑器 / 决策日志三个视图，全部内置、零 CDN、离线可用
- **可视化流程图编辑器** — 条件→组→输出拖线连线（Drawflow），节点点击即改参数，试运行实时染色（绿=满足/红=不满足/输出徽章显示决策）
- **触发器可连线路由（0.7.0）** — 触发器是画布上的信号源：信号线连到条件的「信号」口开始评估；信号覆盖了哪些条件门，就沿链唤醒哪些输出；未连线=不评估，到期唤醒同样定向
- **传感器池** — 一个控制器可引用任意数量的实体；总览页有全局传感器池视图，共享传感器高亮
- **条件规则库** — `numeric_state`、`state`、`time`、`sun`、`template`、`cooldown`、`calendar`、`duration`（持续满 N 秒，TON）、`debounce`（静默 N 秒），支持 `AND`/`OR`/`NOT` 嵌套组合
- **多路输出** — 一个控制器可生成多个开关或二进制传感器；`off_conditions` 优先于 `on_conditions`（防抖动）
- **决策日志** — 每周期逐输出写入独立 JSONL（含传感器读数快照、applied/override 标记），面板内可直接查询
- **手动覆盖** — 开关类型支持可选的手动强制控制
- **零构建前端** — 集成自带全部静态资源（vendored Drawflow），无 Node 工具链、无外网依赖

---

- **Sidebar web panel** — overview / visual flow editor / decision-log viewer, fully built-in, zero CDN
- **Visual flow editor** — wire condition→group→output on a Drawflow canvas; click a node to edit it; trial runs color nodes live (green=met / red=unmet, decision badges on outputs)
- **Sensor pool** — any number of entities per controller; a global pool view highlights sensors shared across controllers
- **Condition library** — `numeric_state`, `state`, `time`, `sun`, `template`, `cooldown`, `calendar`, `duration` (hold N seconds, TON), `debounce` (quiet N seconds), plus `AND`/`OR`/`NOT` nesting
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

- 条件节点（九类叶子，含 duration/debounce 计时门）→ 用连线加入 **AND/OR/NOT 组**（成员可进多组）；触发器信号线连到普通条件的「信号」口（input_3；duration 除外——它是门不是起点）
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
├── ControllerManager    → 每控制器一个：触发调度 + 评估 + 实体注册（controller.py）
├── Condition Engine     → 九类叶子（含 duration/debounce 计时门）+ AND/OR/NOT 嵌套 + 逐条件追踪（condition_engine.py）
├── Output Platforms     → switch / binary_sensor（每控制器一个设备）
├── Web Layer            → 侧边栏面板 + REST API + 静态资源（web.py + static/）
└── Decision Logger      → 独立 JSONL（decision_log.py）
```

**核心组件 / Key Components：**

| 文件 / File | 职责 / Purpose |
|-------------|----------------|
| `hub.py` | 域级单例：Store 读写、控制器 CRUD、运行时快照 / Domain singleton: store, controller CRUD, snapshots |
| `controller.py` | 触发调度、定向路由评估（含 applied/override 记录）、试运行 API / Trigger scheduling, directed evaluation, trial-run API |
| `condition_engine.py` | 递归条件评估（九类叶子 + AND/OR/NOT 嵌套 + 计时账本 + 定向唤醒）/ Recursive evaluator |
| `schema.py` | 共享校验（Web API 与 config flow 同源）/ Shared validation |
| `web.py` | REST views、面板注册、静态资源 / REST views, panel & static registration |
| `static/panel.js` | 面板前端（零构建自定义元素 + Drawflow）/ Zero-build panel frontend |
| `decision_log.py` | 按日轮转 JSONL 日志 / File-based JSONL logger |
| `config_flow.py` | 单步创建全局条目 / Single-step entry creation |

---

## 服务 / Service

### `sensor_switch_controller.force_evaluate`

立即触发指定输出实体的条件评估（不影响触发器调度）。

```yaml
service: sensor_switch_controller.force_evaluate
target:
  entity_id: switch.humidity_control_enable
```

---

## 信号与门 / Signals & Gates

0.6.0 起画布连线遵循统一的「信号+门」语义，与米家自动化极客版的事件/状态模型同构：

- **⚡ 触发器 = 开始评估**（HA 同构）：触发器节点带一个信号输出口（琥珀色框）。触发器 fire = 发出一个信号，信号沿**琥珀色信号线**流入条件门；信号覆盖了哪些门，评估就沿这些门向下走到输出——**未连线 = 不评估**。
- **👁 条件 = 判定门**：条件节点（灰蓝色框）是拦在链上的门，条件为真门开、为假门关。`AND`/`OR`/`NOT` 组是多信号汇聚门。
- **⏳ 持续（duration）= 掐表门**：两个口——开始口（input_1）进线的条件为真时开始掐表，持续满 N 秒放行；开始掉线或中止口（input_2，红）进线的条件为真即复位。组与持续都不是信号起点（无信号口）。
- **🕯 防抖（debounce）= 静默门**：实体最后一次变化后安静满 N 秒才放行（每次变化重置）。
- **⏱ 翻转冷却（cooldown）= 闭锁门**：输出翻转一次后 N 秒内拒绝再次翻转。
- **输出 = 执行器**：只有「是 / 否」两个口——on 门（input_1，绿）/ off 门（input_2，红，优先），由条件链决定；触发器不直连输出（0.7.0 起 routes.outputs 被拒绝，存量经 v4 迁移自动折算为其条件链覆盖）。

**到期也定向**：掐表门到点、静默门放行、冷却结束、时间范围进/出点、日出日落时刻——引擎只在那个精确瞬间唤醒这些时刻**能影响到的输出**，其余输出保持沉默。手动评估与试运行始终全量。

**升级兼容**：存量配置自动迁移（0.5.x 走 v2→v3→v4→v5,0.6.x 走 v3→v4→v5,0.7.0 走 v4→v5：路由中的组/持续 id 展开为其叶子集,若信号覆盖因共享链放宽会在日志中提示)——带 `for` 的条件拆出独立「持续」节点并改写连线、条件型 `at` 降级为时间范围（每日时刻请改用触发器）；触发器路由改为「信号覆盖的条件」（v3→v4：原直连输出自动折算为其条件链覆盖，`routes.outputs` 键删除，此后画布/接口都拒绝直连）。

两点可观测差异需要知晓：① 0.6.x 中把触发器**只直连到部分输出**的存量，若这些输出与其它输出共享条件，折算后信号覆盖会沿共享链扩展到同链输出（v4 的条件载体无法无损表达「只唤其中一半」）；如需收窄，在画布上把信号线改连到更靠近该输出的条件门。② **没有任何条件**的空输出（开/关链皆空）不再进入触发器驱动的定向评估与日志（实体状态本就不受影响；初始评估/立即评估/试运行等全量扫描仍会记一条 hold），如需恢复请给它接条件。

## 路线图 / Roadmap

- **0.8 候选** — 旗标节点（控制器内置虚拟布尔，极客版「自定义状态」等价物，赋值语义绑定输出翻转）；执行路径引擎（信号沿边串行传播、中途赋值、动作序列链）专项调研


## 兼容性 / Compatibility

- Home Assistant **2024.11+**（Web 面板在 2026.1 实测）
- Python **3.12+**

---

## 许可证 / License

MIT

---

*Built with [Kimi](https://kimi.moonshot.cn) by Moonshot AI · Author: [@SagisawaTsubasa](https://github.com/SagisawaTsubasa)*

## 更新日志 / Changelog

### 0.7.1 — 信号口只属于普通条件
- AND/OR/NOT 组与「持续」门**移除触发器信号口**：它们是判断门，不是信号起点（NOT 与组/持续一致处理）
- 触发器信号线只能连到具体条件（数值/状态/时间/日出日落/模板/冷却/日历/防抖）的「信号」口；连到组/持续当场弹回
- schema 拒绝 `routes.conditions` 中的组/持续 id（400）
- 存储迁移 v4→v5：存量路由中的组/持续 id 自动展开为其叶子集——对向下封闭的覆盖（含 0.7.0 迁移产物）评估行为不变；非封闭覆盖可能因共享叶子链放宽唤醒集，迁移时会在日志提示（见「升级兼容」）

### 0.7.0 — 触发器回归「开始评估」语义,输出回归纯是/否
- **行为语义变更**:触发器不再直连输出。信号线只能连到条件的「信号」口;触发器信号覆盖了哪些条件门,评估就沿这些链往下走,链上的输出才被唤醒
- 输出节点只剩「满足则开 / 满足则关」两个口(触发器连接点移除)——与 HA「触发器=开始流程」心智一致
- 存储迁移 v3→v4:原直连输出自动折算为其条件链覆盖(存量行为严格不变);v2 存量直升
- routes.outputs 显式拒绝(400 指引连到条件)

### 0.6.2 — 端口语义标注（Blender 式 socket）
- 画布所有端口圆点旁显示名称标签：输出节点「满足则开/满足则关/信号」、持续「开始/中止/信号」、组「成员」、触发器「信号」——端口含义不再靠试
- 端口按语义配色：琥珀=信号、绿=满足则开、红=满足则关/中止、蓝=持续的开始口、灰蓝=门/成员
- 普通叶子条件隐藏无语义的门入口死口（此前连线被校验拒绝的元凶之一）
- 连线被拒提示对齐新标签

### 0.6.1 — 实体选择升级为 HA 原生组件
- 面板全部实体输入位(传感器池、触发器实体、条件实体、debounce/日历)从浏览器 datalist 升级为 HA 原生 `ha-entity-picker`:友好名、全文搜索、头像;日历条件域过滤只列 `calendar.*`
- 组件按需尽力加载(`loadCardHelpers` 拉起懒加载块),拿不到时自动回退 datalist(零硬依赖)
- 选择结果桥接回既有 change 管线,保存语义零变化

### 0.6.0 — 触发器可连线路由 + 持续/防抖门（信号与门模型）

#### 触发器路由（画布连线）
- 触发器节点 0 入 1 出：信号线从触发器拉到门/输出的信号口（input_3），fire 时**只评估可达输出**；未连=不评估；多条触发线合并时取并集
- 触发器配置新增 `routes:{outputs,conditions}`；无 `routes` 字段的遗留配置保持全量评估语义
- 到期唤醒定向化：FOR/持续到期、防抖静默点、冷却结束、时间范围/日出日落的进出门槛——只唤醒该时刻可达的输出（预计算条件→输出反向索引）
- 拖线即时校验：非法连线当场弹回（信号线只能从触发器到信号口，门线只能到门入口），不再等保存时报 400
- 信号/门视觉语言：触发器琥珀框+琥珀信号线，条件灰蓝框+灰蓝门线，输出绿框；信号口（input_3）琥珀色

#### 新条件节点
- **持续 duration**（三口 TON 门）：开始口条件持续为真满 N 秒→真；开始掉或中止口为真→复位。对应极客版「状态维持」
- **防抖 debounce**（静默门）：实体最后一次变化后安静满 N 秒→真，零运行时状态（读 `last_changed`）。对应极客版「延时」的重触发重置语义
- 条件型 `time.at` 移除：每日时刻只用「每日时刻」触发器（与 HA 语义一致）

#### 存储迁移 v2→v3
- 带 `for` 的 `state`/`numeric_state` 条件自动拆出独立「持续」节点并改写组/输出引用（计时语义逐字保留）
- 含 `at` 的时间条件降级为 `after` 范围条件
- 全部触发器物化为「路由到全部输出」——升级后行为严格不变，用户可在画布上收窄
- 触发器 id 稳定化：校验不再无条件重新生成 id（连线跨保存/重载保持）

#### 修复
- `_rerun_targets` 积压合并的首轮语义：被吞掉的定向评估不再错误扩成全量（smoke 抓获）

### 0.5.2
- 修复 0.5.1 触发器画布节点的三轮审查发现（11 条，全部收口）：
  - inspector 触发器表单 `fi()` 参数错位——attribute/from/to 值不回填、every_seconds/offset 渲染字面 "number" 且类型退化文本（P1）
  - 清空数值字段经 `Number("")===0` 误写 0，改为空串即删除该字段（P2）
  - 太阳事件标签翻译键 `triggerSunEvent` 缺失（P2）
  - 输出列 x 地板改按「组列 x + 节点最大宽 + 间距」推导（820），窄画布不再与组节点重叠（P2）
  - 数值输入补 min/max（对齐 schema 10~86400 / ±86400），节点摘要不再展示越界值（P3）
  - 删除表格遗留孤儿方法、noTriggers/date/limit 死键、只写死的 trgToNode 反向 Map、changelog 空 0.4.2 标题（P3）
- 审查：wb-reviewer（DeepSeek V4.1 Flash）三轮循环至全部严重度零新发现

### 0.5.1
- **触发器画布节点化**：触发器不再是配置区的表格条目，改为流程画布最左列的独立节点（0 端口，不参与逻辑连线——它驱动整轮评估）；palette 三段（添加触发器/条件/输出），点击触发器节点在 inspector 按类型编辑参数，禁用时节点置灰；删除配置区表格
- 修复：时间触发的 at/every_seconds 值写不进模型的分支漏赋值

### 0.5.0 — 自包含自动化框架：触发器自选 + 条件库增强

**定位重述**：内嵌于集成的自动化框架（触发器 + 条件 + 中间层输出实体），自研引擎不随 HA 升级波动；刻意不做设备控制——动作由 HA 自动化消费输出实体完成。

#### 求值触发模型重构
- 控制器配置改为**触发器自选**（对标 HA 自动化/米家中枢心智）：状态触发（实体缺省=整个池，支持 attribute/from/to 过滤）、时间触发（每日时刻 HH:MM 或每 N 秒周期）、太阳触发（日出/日落±偏移）、HA 启动触发；每条触发器可单独禁用
- 任一触发 → 200ms 防抖合并 → **全量电平评估**（求值语义不变，电平模型的滞回/FOR/日志带依据等优点全保留）
- **FOR 到期精确唤醒**：存在持续计时条件时，引擎在到期时刻自动唤醒评估（事件驱动无轮询兜底，靠精确唤醒保证 duration 到期判定）
- 全局 `scan_interval` 字段废弃；旧配置自动映射为一条等价时间触发器（可删改）
- 决策日志 record 新增 `triggered_by`（本轮评估由哪些触发器引起）

#### 条件库增强
- **NOT 非门**（组：任一成员为真即不通过，语义对齐 HA `not`）
- **翻转冷却 cooldown**：距本输出上次实际翻转 ≥ N 秒为真（节流/防抖原生支持）
- **time 条件扩展**：`weekdays` 星期几 + `at` 每日时刻（与 after/before 互斥）
- **条件级 enabled**：临时禁用单条件（跳过求值、不影响 AND/OR 结果）
- **calendar 日历条件**：指定日历未来 N 小时有事件

#### 编辑器
- 控制器配置改**三段式**：触发器 / 传感器池 / 流程图
- 条件面板新增翻转冷却、日历、NOT 组三种节点；time 表单加星期几与 at；每个条件节点带"启用"开关
- 手机查看模式同步适配（触发器配置区在窄屏隐藏）

#### 兼容性
- 旧配置（scan_interval）自动迁移映射；`runtime_snapshot`/实体属性中 `scan_interval_seconds` 由 `trigger_count` 取代

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
