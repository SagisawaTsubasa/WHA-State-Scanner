# HA 全屋状态扫描 / HA Whole-House State Scanner

> **零 YAML 全屋状态扫描器：可视化流程图编辑中间层决策，条件规则 + 多路输出 + 独立决策日志。**
>
> A zero-YAML whole-house state scanner: edit your sensor→decision middle layer as a visual flow graph — condition rules, multiple outputs, and an independent decision log.

> **Programmer:** [Kimi](https://kimi.moonshot.cn) (Moonshot AI) · **Author:** [@SagisawaTsubasa](https://github.com/SagisawaTsubasa)

---

## 功能 / Features

- **侧边栏 Web 管理页** — 无需 YAML：总览 / 流程图编辑器 / 决策日志三个视图，全部内置、零 CDN、离线可用
- **可视化流程图编辑器** — 条件→组→输出拖线连线（Drawflow），节点点击即改参数，刷新状态只读染色（绿=满足/红=不满足，不动作不写日志），「立即评估」确认后才真实动作（输出徽章显示决策）
- **触发器可连线路由（0.7.0，0.10.0 起强制显式）** — 触发器是画布上的信号源：信号线连到条件或逻辑组的「信号」口开始评估；信号覆盖了哪些门，就沿链唤醒哪些输出；未连线=不评估，到期唤醒同样定向（逻辑组：连信号=触发合并贯通，连成员=条件判定）。0.10.0 起遗留全量评估（routes 缺省）与「留空监听整个传感器池」均废弃：routes 与触发实体（可逗号分隔多实体）必须显式声明
- **条件规则库** — `numeric_state`、`state`、`time`、`sun`、`template`、`cooldown`、`calendar`、`duration`（持续满 N 秒，TON）、`debounce`（静默 N 秒）、`snapshot`（快照记忆）、`literal`（常量）、`compare`（双端求值）、`countdown`（倒计时锁存）、`quota`（次数余量）、`tally`（累计计数）十五类叶子，支持 `AND`/`OR`/`NOT` 嵌套组合
- **多路输出** — 一个控制器可生成多个开关或二进制传感器；`off_conditions` 优先于 `on_conditions`（防抖动）
- **决策日志** — 每周期逐输出写入独立 JSONL（触发源实体与状态变化、逐条件求值明细、applied/override 标记；0.11.0 及以前的旧记录另含全池读数快照），面板内可直接查询
- **手动覆盖** — 开关类型支持可选的手动强制控制
- **零构建前端** — 集成自带全部静态资源（vendored Drawflow），无 Node 工具链、无外网依赖

---

- **Sidebar web panel** — overview / visual flow editor / decision-log viewer, fully built-in, zero CDN
- **Visual flow editor** — wire condition→group→output on a Drawflow canvas; click a node to edit it; the read-only status refresh colors nodes (green=met / red=unmet, no actuation); "evaluate now" actuates behind a confirm (decision badges on outputs)
- **Condition library** — `numeric_state`, `state`, `time`, `sun`, `template`, `cooldown`, `calendar`, `duration` (hold N seconds, TON), `debounce` (quiet N seconds), `snapshot` (memory of one moment), `literal` (constant), `compare` (two-input verdict), `countdown` (timed latch), `quota` (budget gate), `tally` (pass-through counter) — fifteen leaf types, plus `AND`/`OR`/`NOT` nesting
- **Multiple outputs** — switches and binary sensors per controller; `off_conditions` win over `on_conditions` (anti-flapping)
- **Decision log** — per-cycle JSONL with firing entity + state change, per-condition verdicts, applied/override flags (records up to 0.11.0 also carry a full-pool readings snapshot); queryable in the panel
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

安装文羽面板壳（FumihaHub）后，本面板自动并入壳的页签栏（不再重复出现在侧边栏）；未装壳或壳被移除时（条目重载后）回落独立侧边栏面板，两种形态自动切换。壳内编辑器/日志视图为页内内存态导航，独立模式下才支持 `#/editor/<id>` 深链接与刷新保持。

| 视图 / View | 内容 / Content |
|-------------|----------------|
| **总览 / Overview** | 控制器卡片（输出实时状态、立即评估、启停、删除） / Controller cards with live output states, evaluate-now, enable/disable, delete |
| **编辑器 / Editor** | Drawflow 流程画布：条件/组/输出节点拖线连线，右侧 inspector 编辑参数，顶部保存、刷新状态（只读）与立即评估（确认后动作） / Flow canvas with condition/group/output nodes, inspector forms, save & refresh status (read-only) & evaluate-now (actuates behind a confirm) |
| **决策日志 / Logs** | 按控制器+日期查询 JSONL 决策记录，可按 decision 过滤，旧记录的读数快照可展开 / Query JSONL records by controller+date, filter by decision, expandable readings in pre-0.12.0 records |

**编辑器节点语义 / Node semantics:**

- 条件节点（十二类叶子 + 逻辑组 AND/OR/NOT）→ 信号线连到普通条件或逻辑组的「信号」口（input_3；持续、旗标与数据节点无信号口）
- 组或顶层条件连线到**输出节点**的两个输入端口：`input_1` = 满足则开（on_conditions），`input_2` = 满足则关（off_conditions，**优先**）
- **快照节点**：`input_1` = 拍下（capture，多线=任一门的上升沿拍一次）、`input_2` = 清空（clear，多线=任一，清空优先）+ 表单选源实体（纯读）
- **常量节点**：恒真，无输入口，表单填值类型（数字/状态）与值，供求值 A/B 端复用
- **求值节点**：`input_1`/`input_2` = A/B 端（各只接一根线，**只收快照/常量节点**；未连线端按表单实体状态或属性求值），算子在表单选
- **刷新状态**是只读观察（不写输出实体、不写决策日志），把每个条件的当前满足结果染色到节点上；真实评估走「立即评估」按钮（经确认框，会实际写输出实体、写决策日志）
- 保存后控制器整条重载，FOR 计时器清零

**REST API**（面板使用，亦可脚本调用，均需鉴权）：

```
GET    /api/sensor_switch_controller/config
POST   /api/sensor_switch_controller/controllers          # 创建（body 为控制器 JSON）
GET    /api/sensor_switch_controller/controllers/{id}/observe # 只读实时条件状态（观察）
PUT    /api/sensor_switch_controller/controllers/{id}     # 更新
DELETE /api/sensor_switch_controller/controllers/{id}
POST   /api/sensor_switch_controller/controllers/{id}/evaluate   # 立即评估（带逐条件结果）
GET    /api/sensor_switch_controller/logs?controller_id=&date=YYYY-MM-DD&decision=on|off|hold|capture|clear&limit=500
```

---

## 独立日志系统 / Independent Logging

开启日志后，每次评估在专用 JSONL 文件中追加记录（按控制器分目录、按日轮转、保留 30 天）：

```
<HA_CONFIG>/sensor_switch_controller_logs/<controller_id>/log_YYYY-MM-DD.jsonl
```

**示例记录 / Example record：**

```json
{"timestamp":"2026-10-05T14:30:00+08:00","controller":"浴室湿度控制","output":"湿度控制使能","decision":"off","on_met":false,"off_met":true,"applied":true,"override":false,"triggered_by":"湿度达标 [switch.shi_du: off→on]","conditions":{"cond_1a2b…":false}}
```

- `decision` 为条件判定结果（on/off/hold；0.13.0 起快照拍下/清空另记 capture/clear 事件行——hold 也记录，"为什么没动作"同样有据可查）
- `applied` 表示判定是否实际写入实体；`override` 表示该写入被手动覆盖拦截
- `triggered_by` 记录触发来源（触发器标签 + 触发实体及其状态变化）；`conditions` 是本周期输出链逐条件求值明细（条件 id → 布尔结果）
- 0.11.0 及以前的旧记录另有 `readings` 键（当时的全池读数快照）；0.12.0 起新记录不再携带，面板仅对旧记录展开显示

---

## 架构 / Architecture

```
Config Entry（单一条目 / single entry）
├── Store                → 全部控制器配置（hub.ScannerHub, storage.Store）
├── ControllerManager    → 每控制器一个：触发调度 + 评估 + 实体注册（controller.py）
├── Condition Engine     → 十二类叶子（duration/debounce 计时门 + snapshot/literal/compare 数据节点）+ AND/OR/NOT 嵌套 + 逐条件追踪（condition_engine.py）
├── Output Platforms     → switch / binary_sensor（每控制器一个设备）
├── Web Layer            → 侧边栏面板 + REST API + 静态资源（web.py + static/）
└── Decision Logger      → 独立 JSONL（decision_log.py）
```

**核心组件 / Key Components：**

| 文件 / File | 职责 / Purpose |
|-------------|----------------|
| `hub.py` | 域级单例：Store 读写、控制器 CRUD、运行时快照 / Domain singleton: store, controller CRUD, snapshots |
| `controller.py` | 触发调度、定向路由评估（含 applied/override 记录）、评估/观察 API / Trigger scheduling, directed evaluation, evaluate/observe API |
| `condition_engine.py` | 递归条件评估（十二类叶子 + AND/OR/NOT 嵌套 + 计时账本 + 定向唤醒）/ Recursive evaluator |
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

- **⚡ 触发器 = 开始评估**（HA 同构）：触发器节点带一个信号输出口（琥珀色框）。触发器 fire = 发出一个信号，信号沿**琥珀色信号线**流入条件门；信号覆盖了哪些门，评估就沿这些门向下走到输出——**未连线 = 不评估**。0.10.0 起 routes 必填、state 触发器触发实体必填（遗留全量与池监听废弃，见「升级兼容」）。
- **👁 条件 = 判定门**：条件节点（灰蓝色框）是拦在链上的门，条件为真门开、为假门关。`AND`/`OR`/`NOT` 组是**双模式**：连成员线=条件逻辑（AND/OR/NOT 判定）；连触发器信号线=触发逻辑（合并器，任一触发贯通放行）。两种模式对称互斥，连了一侧另一侧隐藏。
- **⏳ 持续（duration）= 掐表门**：两个口——开始口（input_1）进线的条件为真时开始掐表，持续满 N 秒放行；开始掉线或中止口（input_2，红）进线的条件为真即复位。持续不是信号起点（无信号口）。
- **⊕⊗¬ 逻辑组 = 汇聚判定**：**双模式**——成员口（input_1，灰蓝）收条件线组成 AND/OR/NOT（条件逻辑）；信号口（input_3，琥珀）收触发器线做触发合并（任一触发贯通放行，可多条；空组合法）。两侧对称互斥：连了一侧另一侧隐藏，删线恢复。
- **🕯 防抖（debounce）= 静默门**：实体最后一次变化后安静满 N 秒才放行（每次变化重置）。
- **⏱ 翻转冷却（cooldown）= 闭锁门**：输出翻转一次后 N 秒内拒绝再次翻转。翻转史持久化（0.11.0 起）；**只挂 on 链**——挂 off 链会在无翻转史时恒为 True 并以 off 优先永久压制 on 链（保存时会告警）。
- **⏲🎫🧮 状态节点（0.14.0）= 数值状态步进门**：一套机制三种参数化，全部边沿触发（电平持续只算一次）、同拍复位优先、内部状态进第五张持久化表（跨重启/重载存活）——**⏲ 倒计时（countdown）**：开始门升沿启动/重走（时限=当下+秒数），复位门升沿停止并回满；出口=归零后 true 并锁存，再次开始瞬间翻 false，复位翻 false；归零由定向唤醒自调度，重启按 wall-clock 差值继续走到零（停机时长计入倒计时）。**🎫 次数余量（quota）**：消耗门升沿剩余>0→扣 1→出口 true，剩余=0→出口 false（拦截）；复位门升沿恢复满 X；出口=最近一次消耗的结果。**🧮 累计计数（tally）**：计数门升沿 +1；出口随计数门电平透传（门假→出口假）；复位门升沿归零；不判阈值不锁存，计数供面板/日志/未来判断面观测。三者均非信号起点（无信号口），出口由步进/锁存决定、不支持 `for`。
- **输出 = 执行器**：只有「是 / 否」两个口——on 门（input_1，绿）/ off 门（input_2，红，优先），由条件链决定；触发器不直连输出（0.7.0 起 routes.outputs 被拒绝，存量经 v4 迁移自动折算为其条件链覆盖）。

**到期也定向**：掐表门到点、静默门放行、冷却结束、时间范围进/出点、日出日落时刻——引擎只在那个精确瞬间唤醒这些时刻**能影响到的输出**，其余输出保持沉默。手动评估与刷新状态始终全量。

**升级兼容**：存量配置自动迁移（0.5.x 走 v2→v3→v4→v6,0.6.x 走 v3→v4→v6,0.7.0/0.7.2 走 v4/v5→v6：剥离持续覆盖、把有成员的组覆盖展开为叶子集——成员+信号共存的组会被拒绝,画布上二选一）——带 `for` 的条件拆出独立「持续」节点并改写连线、条件型 `at` 降级为时间范围（每日时刻请改用触发器）；触发器路由改为「信号覆盖的条件」（v3→v4：原直连输出自动折算为其条件链覆盖，`routes.outputs` 键删除，此后画布/接口都拒绝直连）。

0.7.1（v5）已展开为纯叶子覆盖的存量保持不变；0.7.0/0.7.2 存量升级时剥离持续覆盖并把有成员的组覆盖展开为叶子集（v5→v6）。两点 0.7.0 时代的可观测差异需要知晓：① 0.6.x 中把触发器**只直连到部分输出**的存量，若这些输出与其它输出共享条件，折算后信号覆盖会沿共享链扩展到同链输出（v4 的条件载体无法无损表达「只唤其中一半」）；如需收窄，在画布上把信号线改连到更靠近该输出的条件门。② **没有任何条件**的空输出（开/关链皆空）不再进入触发器驱动的定向评估与日志（实体状态本就不受影响；初始评估/立即评估等全量扫描仍会记一条 hold——试运行已改为只读观察不写日志，0.12.0 起记录也不再携带全池 readings 快照），如需恢复请给它接条件。

**0.10.0（v7 迁移，因果显式化）**：遗留全量触发器（routes 缺省）物化 `routes.conditions` 为其输出链可达的全部合法信号起点——叶子条件（持续门/旗标/逻辑组不是信号起点，叶子经组的成员边、持续的 start/abort、旗标的 set/reset 边天然可达）；物化后的定向唤醒集覆盖原全量扫描中每个可能改变状态的输出。池监听 state 触发器（entity_id 缺省）物化 `entity_id` 为传感器池全部实体列表（等价原监听面）。此后 schema **拒绝** routes 缺省与触发实体留空：新建触发器必须显式连线、显式声明实体（面板支持逗号分隔多实体，单实体保持字符串形态）。传感器池为空的池监听触发器迁移后实体列表为空：启用的触发器落 invalid 可见修复（该触发器原本就永不触发），停用的触发器保持合法惰性（运行时本就不注册）；pre-0.5.0 无触发器列表的远古存量映射出的扫描触发器自动物化 routes（与 v7 同一套信号叶子集，行为等价原全量评估面）、触发器 id 由配置确定性派生（跨重载稳定），无需重建。

**0.11.0（保存时静态告警 + 冷却翻转史持久化）**：四类配置隐患改为**保存时告警（不拒存，升级兼容）**——① off 条件链挂冷却（翻转史缺失恒 True + off 优先 + off 不记账的组合会让输出永久压在 off，见「翻转冷却」）；② 输出仅靠日历门（日历事件边界无 HA 事件，唤醒靠心跳兜底、延迟可达心跳间隔）；③ 触发器信号线连到到不了任何输出的条件（空转）；④ 输出链引用空逻辑组（非信号锚点恒 False）。冷却的**翻转史自 0.11.0 起持久化**（与旗标锁存同载荷）：旧版本重载/重启后冷却门会立即失效（比预期更早放行），升级后自首次翻转起跨重启有效——旧存量没有历史可恢复，首个保护期从升级后第一次翻转开始。编辑器「试运行」按钮改为**只读刷新**（不动作）；真实评估移到「立即评估」按钮，必须经确认框。binary_sensor 输出的 `manual_override` 死键在保存时丢弃。

## 路线图 / Roadmap

- **候选** — 执行路径引擎（信号沿边串行传播、中途赋值、动作序列链）专项调研


## 兼容性 / Compatibility

- Home Assistant **2024.11+**（Web 面板在 2026.1 实测）
- Python **3.12+**

---

## 许可证 / License

MIT

---

*Built with [Kimi](https://kimi.moonshot.cn) by Moonshot AI · Author: [@SagisawaTsubasa](https://github.com/SagisawaTsubasa)*

## 更新日志 / Changelog

### 0.14.0（2026-11-14）— 状态节点批：倒计时、次数余量、累计计数

**新增（补引擎数值状态原语，替代 HA 原生 timer/counter 的判断面职能，防镜像化回潮；存量配置零改动）**
- **⏲ 倒计时（countdown）**——双入口（start/reset）一出口：start 门升沿启动/重启动（回满重走，时限=当下+秒数，1..86400 同 duration 梯）；reset 门升沿=停止并回满（未启动态）；出口=**归零后 true 并锁存**，再次 start 瞬间翻 false，reset 翻 false。归零由 `next_wakeup` 定向自调度唤醒（duration offer 同源）；**重启按 wall-clock 差值继续走到零**（持久化的是绝对 deadline，停机时长计入倒计时；到零即锁存 true，verdict 丢失可由 deadline 自愈）
- **🎫 次数余量（quota，X 次）**——双入口（consume/reset）一出口：consume 门升沿剩余>0→扣 1→出口传 true；剩余=0→**出口传 false（拦截）**；reset 门升沿=恢复满 X。出口=最近一次消耗的结果（消耗掉最后一个名额那次报告 true——当时允许；下一次尝试在 0 处报告 false）
- **🧮 累计计数（tally）**——双入口（count/reset）一出口：count 门升沿=+1→出口传 true（入口 false→出口 false，**透传+副作用**）；reset 门升沿=归零；不判阈值不锁存，计数状态供面板/日志/未来判断面观测
- **通用口径**：触发一律**上升沿**（电平持续成立只算一次，防连环扣/连环加）；同拍 reset 优先于普通入口；一套机制三种参数化（`STATEFUL_GATE_KEYS` 单源：start/consume/count + 共享 reset_conditions），仿旗标步进族在每周期输出求值前统一执行
- **持久化（第五张运行态表）**：三节点内部状态进 `stateful` 表（flags/last_flip/snapshots/snapshot_gates 之后，键=节点 id，值=verdict+deadline（ISO）/余量/计数+prev 门真值）——prev 门随值表持久化，重载/重启后电平持续**不会**重放边沿（防重启多扣/多计）；旧载荷无该键静默容忍，坏值（类型不符）告警丢弃、引擎默认值自愈。控制器删除时第五表成对清理。存储版本 v8→v9（控制器配置零变化，v8 链为空过站，载荷重存至 v9 纪元）
- **校验面**：双门引用存在性、参数范围（countdown `seconds` 1-86400 整数、quota `times` 1-86400 整数）、禁自引用（直接引用拒存 F-451 同型；间接引用闭包走查拒绝——**reset 方向走查含 duration abort 边**，主门方向的一次性自复位[abort]合法，R8#1 教训内建）、门死分支拒存（冷却在步进上下文恒假同型）、`for` 拒收（旗标族口径，持续前置用 duration 组合）；状态节点入 NON_SIGNAL_TYPES（非信号起点，路由目标拒存）；触发覆盖展开/路由索引/空组存续/静态告警四处走查列表同步
- **画布**：三新节点入调色板——倒计时/次数余量/累计计数均为双入口（主门 input_1 蓝 + 复位 input_2 红，多线=任一）+单出口；编辑表单含秒数/次数与语义提示；中英文案同步（LANG +16 键/语言）；触发覆盖走查含状态节点门边
- **同周期收敛**：状态节点动作与旗标/快照门互读时单周期内收敛（旗标/快照在读到新出口判定后有界重步进，F-427 同型面镜像）；快照 clear 门闭包走查补 duration abort 边（F-459 清偿：clear=[duration(start=X,abort=自身)] 拒存，capture 方向一次性自复位保持合法）

**内部**
- 引擎 `step_stateful`（快照步进后单次推进，动作事件立即持久化+prev 门移动去抖持久化 if-changed [F-434 纪律]+翻转定向扩面+收敛重步）；`next_wakeup` 倒计时 deadline offer；hub 第五表 load 阶梯（单点规整+坏值自愈）与事件/去抖双保存路径；smoke 新增五段状态节点钉（边沿/电平判别、同拍 reset 优先、余量 0 拦截极性、锁存翻回、无自唤醒、零点翻转驱动输出+快照门同周期收敛、壁钟续走+原值恢复+deadline 自愈、hub 阶梯+成对清理、v8→v9 迁移链+历史链全量 validate、schema 拒存面+F-459 判别对）；test_roundtrip 新增状态节点形态字节等价钉

### 0.13.0（2026-11-10）— 数据节点批：快照记忆、常量、双端求值

**新增（纯增量能力，存量 8 控制器拓扑与行为零改动）**
- **📷 快照（snapshot）叶子条件**——记忆这一刻：`capture` 引用条件的门**由假变真那一拍**拍下源实体当时的值（之后源变化不刷新，再拍需门先掉再升）；`clear` 任一满足即清空（清空优先，复刻旗标复位优先次序）。节点真值=「快照存在」（无快照恒假）；**纯读源实体，绝不写**。拍下时按源实体属性判型：带 `unit_of_measurement` 或 `state_class=measurement` 的读数按数值拍（float；声明数值却读出非有限数字时告警并落状态快照）；无属性提示时以 `float()` 解析兜底（数字样状态串会数值化），NaN/inf 一律不落数值快照；源实体缺失/unavailable 时**不拍**并在日志告警。边沿 prev 门真值随快照同载荷持久化（`snapshot_gates` 表）：重载/重启后门持续真**不会**覆盖已锁存的值；旧载荷无该表时退化为首个真周期幂等重拍一次。拍下/清空事件进决策日志（结构化 `decision=capture/clear`+`value` 行，面板按语言本地化渲染）
- **常量（literal）叶子条件**——恒真节点：`value_type`（number/state）+匹配类型的 `value`，给求值 A/B 端提供比较基准，可被多个求值复用
- **⚖ 求值（compare）叶子条件**——双输入单输出：A/B 各自三态（`{kind: entity, entity_id, attribute?}` 实体当前状态或属性 / `{kind: snapshot, cond}` 快照值 / `{kind: literal, cond}` 常量）。两端同数值型→数值比较；同状态型→字符串比较；above 族遇非数值端或两端混型→**判定为假+日志 WARN**（禁静默回落）；实体 unavailable/属性缺失→假+告警记因。六算子：`equal / not_equal / above / below / above_equal / below_equal`
- **三层分工正交**：and/or/not 组管布尔逻辑、求值管值算术、快照管记忆——数据节点可进组/输出链统一求值，引擎无类型特例分支；`for` 持续前置按通用叶子规则同样可用。同周期收敛：拍/清事件发生时旗标重步进一次（旗标 set/reset 读快照不再慢一拍）并把下游链扩进本周期评估
- **画布**：三新节点入调色板——快照=拍下/清空双入口（多线=任一，旗标同款）+源实体表单；常量=值类型下拉按型联动；求值=A/B 双口（只收快照/常量连线、单线，未连线端按表单实体求值，连线优先）+算子下拉；中英文案同步（LANG +36 键/语言）
- **持久化**：旗标存储载荷 `{flags, last_flip}` 扩为 `{flags, last_flip, snapshots, snapshot_gates}`——旧载荷缺键静默容忍，**显式 null 与坏值告警丢弃**；快照与边沿门真值跨重启/重载存活。唤醒口径不变（0.12.0）：数据节点无计时边，依赖实体变化靠触发器显式声明——其中**求值的实体端由监听该实体的 state 触发器自动覆盖**（触发器 entity 列表命中求值所读实体时，该求值可达的输出自动并入本周期评估面，无需信号线）。该覆盖的边界：① 触发器自身的 `from`/`to`/`attribute` 过滤会收窄实际触发面，「监听命中」不等于「每次变化都唤醒」（被过滤吞掉的事件不唤醒）；② **属性端**：无 attribute 过滤的 state 触发器在状态值不变（仅属性变化）时不再触发事件，求值读属性的链若只靠此类触发器覆盖，属性单独变化不会唤醒——请给该触发器加对应 attribute 过滤；③ 触发器监听 X 而求值读 Y 不覆盖（需把信号线连到链上条件，或为 Y 另配触发器）
- 校验面：快照 capture/clear 引用存在性、**拍/清门死分支拒存**（冷却条件在快照步进时没有输出上下文恒 False，混入恒假成员的组同理；混合 OR 组经活成员仍可用）、求值 A/B 引用必须指向同型节点、常量值型匹配、算子白名单；触发器覆盖展开含快照拍/清边与求值 A/B 引用（与运行时路由索引同构防漂移）
- **保存时静态告警第五面（不拒存，warn-only）**：输出链上没有任何可唤醒源——链上无壁钟门/计时门，触发器信号覆盖与求值实体监听也接不上时，该输出只会在初始评估或手动「立即评估」时更新，保存时告警提示把信号线连到链上条件。边界：**快照的拍/清门不算唤醒源**（引擎只为计时/壁钟/日历类门排定向唤醒，拍/清门只在已有周期内被步进）——快照链的唤醒同样要靠触发器信号线连到链上条件或 state 触发器监听求值读取的实体（0.12.0 唤醒口径不变）

**内部**
- 引擎 `step_snapshots`（旗标步进后单次推进，拍/清事件驱动定向扩面+旗标重步进+持久化+决策日志事件行）；smoke 新增十一段数据节点钉（边沿拍/不刷新/清空优先/冻结/持久/门种子重建不覆盖/旧载荷退化重拍/六算子/字符串等值/判型属性提示与 NaN 门/类型不匹配与不可读端 WARN/schema 守卫与死门/定向扩面+同周期旗标收敛/覆盖展开/无自唤醒）；新增 `tests/test_roundtrip.py` 存量配置 GET→PUT 字节等价钉；新增 `dev/test_ports.py` Playwright 真实 DOM 端口可见性钉（快照/求值输入口在画布可连，准入 JS 与 CSS 同向）

### 0.12.0（2026-11-03）— 传感器池机制下线、实体下拉可读性修复、P3 清偿

**行为变更（存量自动迁移，语义不变）**
- **传感器池机制下线**：`sensors` 配置字段退役——存储迁移 v7→v8 剥离存量 `sensors` 键（首次加载日志可见）；REST 载荷携带 `sensors` 键接受即弃并 warning（存量导出可重放，不静默）；决策记录不再携带全池 `readings` 快照（旧日志文件原样保留，面板仅对旧记录展开读数列）；总览页传感器池总览视图与编辑器池编辑面移除。条件/输出/触发器语义不变（条件实体本就直读 HA 状态，池只是决策日志的快照载体）
- 镜像布尔 input_boolean 配置层本版不动（按既定计划切换后退役）

**修复**
- **实体下拉可读性**：编辑器检查器列 320px→360px——HA 前端 2026.1 的 picker 浮层宽度跟随字段容器（`--body-width` 由 JS 内联锁定，两重 shadow 无法从面板侧覆盖），拉宽宿主列是唯一纯 CSS 通道；各处实体输入下拉浮层随之达标
- P3 清偿（复验 R3）：README 试运行措辞残留 + `trialRun` 孤儿键；无 hass 时 `tr()` 补浏览器语言兜底（en 界面不再透出中文）；冷却翻转史去抖 stub 改判别钉（回退同步写不再全绿）；`check_panel_strings.mjs` 接入 CI（面板 i18n 防线生效）；日历告警面过滤 disabled 条件（恒 True 的 disabled 日历不再误报，disabled 非日历门不再虚增「其他可唤醒」判定）

**内部**
- 存储版本 v7→v8（`_migrate_controller_v8` 挂入全部迁移链）；smoke 新增 v8 剥键、PUT 容忍+warning、observe/决策记录无 readings 断言与 F-346 双判别钉；`_async_evaluate_output` 签名去 readings 参数

### 0.11.0（2026-10-31）— cooldown 关侧陷阱防御、日历门唤醒、翻转史持久化、编辑器预览只读化

**新增**
- **保存时静态告警（不拒存）**：schema 图检查新增四类隐患告警——off 条件链挂冷却（极性陷阱）、输出仅靠日历门、触发器信号线连到到不了任何输出的条件、输出链引用空逻辑组（非信号锚点）
- **日历门到期唤醒**：日历条件求值时缓存最早未来边界（事件进入/离开查询窗口的时刻），`next_wakeup` 定向唤醒；心跳兜底覆盖冷启动与远期事件（默认 15 分钟间隔）
- **冷却翻转史持久化**：applied 翻转与旗标锁存同载荷落盘，重载/重启后冷却门不再失效（旧版本 fail-open）
- 模板/日历求值失败改**限频 warning**（默认 10 分钟一次），不再只有 debug 级静默回落

**修复**
- 编辑器「试运行」按钮改为只读状态刷新（原按钮会真实动作输出且无确认）；真实评估移到「立即评估」按钮，必须经确认框（与总览页一致）
- 存储迁移函数对非 dict 顶层载荷不再崩溃（警告降级，不再阻断整个集成 setup）
- 旗标存储写入改为逐控制器快照（与控制器保存同纪律，杜绝并发改表面）；载荷「flags 键缺失/null」不再静默清空
- PUT 更新控制器后清扫被删输出/类型切换遗留的注册表幽灵条目（与 DELETE 同款 best-effort）
- NOT 组下的空组不再发「不贡献」误导告警（恒 True 语义与文档对齐）
- binary_sensor 输出的 `manual_override` 死键保存时丢弃；面板类型切换时同步清零；触发器「死」徽章扩展覆盖「连了但到不了输出」的路由；日志错误提示文案进双语字典
- P3 清偿（复验 R2）：README 正文三处同步试运行只读化语义；空组保存告警排除已停用组（引擎侧 disabled 恒 True，不再误报）；面板 en 字典去重、`hass 未就绪` 提示进双语字典；冷却翻转史落盘改 1 秒去抖合并写（突发翻转不再逐次全表重写）；面板卸载不再对已触发的 started 监听 unsub（消除 error_log 噪音）；补 config_flow / binary_sensor / 面板 i18n 测试钉与 F-323/F-324 判别钉

**元数据**
- `iot_class` 改为 `local_push`（0.5.0 起纯事件驱动）；`force_evaluate` 服务描述与翻译同步（不再提轮询定时器）

### 0.10.0（2026-10-29）— 因果显式化：废弃遗留全量、触发实体显式化、因果日志

**行为变更（breaking，存量自动迁移保语义）**
- **触发器 routes 必填**：遗留全量评估（routes 键缺省）废弃，schema 直接拒绝；v6 存量经 v7 迁移自动物化 `routes.conditions` 为输出链可达的全部合法信号起点（叶子条件），物化后定向唤醒集覆盖原全量扫描中每个可能改变状态的输出（空链输出原本只产出 hold 记录，冻结等价）
- **state 触发器实体必填**：留空监听整个传感器池废弃；v6 存量池监听触发器物化 `entity_id` 为传感器池全部实体列表（等价原监听面）；`entity_id` 放开字符串列表（多实体触发，单监听器生效）；池为空的迁移存量：启用的触发器落 invalid 可见修复（原本就是永不触发的注册错误），停用的触发器保持合法惰性（运行时本就不注册）
- pre-0.5.0 远古存量（无触发器列表）映射出的扫描触发器自动物化 routes（与 v7 同一套信号叶子集，行为等价），触发器 id 由配置确定性派生，无需重建触发器

**新功能**
- **决策日志因果显式化**：`triggered_by` 记录触发源实体与状态变化（`标签 [switch.c: off→on]`）；每条记录新增 `conditions` 逐条件求值明细（复用试运行同款 evaluate_detailed 路径，评估语义不变）
- **面板多实体触发**：state 触发器实体字段支持逗号分隔多实体（inspector 提示+节点摘要显示 N 实体）；面板新建触发器改为 born directed-empty（routes 必填，未连线走既有死触发确认防线）

**内部**
- 存储版本 v6→v7（迁移含旗标 set/reset 边可达性与组类型过滤：有成员组不进覆盖、空组保持死锚点语义防判定翻转）；smoke 新增迁移等价性钉（评估面=原全量、监听面=原池）、legacy/池空拒绝、多实体触发、triggered_by/conditions 明细断言

### 0.9.0（2026-10-26）— 旗标节点 + 暗病修复 + 面板死触发防线

**新功能**
- **旗标/锁存节点（flag）**：控制器内置虚拟布尔——任一置位条件满足→开、任一复位条件满足→关（同周期复位优先），其余锁存保持；每评估周期开始统一步进，输出与逻辑组可直接引用。锁存状态持久化（条目重载保持、HA 重启后从 `sensor_switch_controller_flags` 存储恢复），补齐 level 引擎缺失的"记忆"表达力（此前"洗完澡"类锁存语义只能留在控制层）
- 画布新增 🚩 旗标节点：置位/复位两口均可多线；inspector 可设初始值；校验拒绝旗标级联（set/reset 引用另一旗标）与触发器信号直连旗标

**修复（集成体检 2026-10-25，报告见仓 temp 记录）**
- **P2 输出实体接入 RestoreEntity**：重启/重载后恢复上次状态，`hold` 不再落到错误的 off 基线
- **P2 删除控制器的实体注册表清扫**：按 unique_id 前缀扫描（含"先停用再删除"与未入 hass 实体），不再残留永久幽灵实体
- **P2 存储保存失败回滚**：save 抛异常时内存状态回滚+补排重载，消除"内存已删/磁盘还在"的分裂（DELETE 路径重启僵尸复活的根因）
- **P2 新建控制器 id 同时查 invalid 空间**：撞号不再被 invalid 轮转静默顶掉
- P3：迁移失败后果注释化（数据不丢进 invalid）；v4→v6 coverage 清空加 warning；PUT 并发竞态回 404；**面板连续保存合并重载（1s 窗口）**——每次重载清零 FOR/duration 计时的问题消除；决策日志目录被删后自愈重建；invalid 条目快照保留原 name；config entry version>2 拒绝加载（防降级改写）；平台转发失败时回收触发器监听；面板 noControllers 重复键清理

**面板（M4 死触发防线）**
- **触发器三态徽章**：节点角标直接显示「全量」（遗留评估，琥珀）/「→N」（定向 N 条件）/「死」（定向但零覆盖，红色描边）——死触发此前在画布上完全不可见
- **保存防线**：已启用的定向触发器零覆盖时保存弹确认（拦截"连线再删线"的静默降级路径）
- **面板新建触发器改为遗留语义**（routes 键缺省）：与 REST 创建对齐，新触发器不再默认"死"

**工程**
- `dev/test_routing.py` 解禁入仓（panel.js 唯一回归防线此前被 gitignore）；CI 新增 `node --check` 语法门
- 修复 0.8.1 后 3 个未入账提交（IMP-01~03/14~16/20~21，全部 panel.js）的 changelog 缺口；修正架构图 `SannerHub` 拼写

### 0.8.1（2026-10-14）— 可操作性迭代

- 删除控制器与试运行 dirty 确认改自绘对话框（原生 confirm 观感/按钮序不可控）；试运行确认文案与行为对齐（原文案说"先保存"而确定却直接试运行）
- 总览「立即评估」加确认+忙碌禁用（真实应用输出）；「启停」切换忙碌禁用防重复点击
- 日志页区分"该日无决策记录"空态与查询失败（失败带样式可重试）；截断提示具体化

### 0.8.0 — 接入文羽面板壳（FumihaHub）
- **壳集成在场时面板自动注册为壳内页签**（`sensorswitch.main`，排序 40），卸载/删除壳后（条目重载后）自动回落为独立侧边栏面板（`wha-scanner`）——无需改任何配置；HA 启动时序竞态由 `homeassistant_started` 事件重判兜底
- 模式切换（壳出现/消失）时对称拆除旧注册；壳内页内导航为内存态（壳独占 `location.hash`，`#/editor/<id>` 深链接/刷新保持仅独立模式支持）；移动端只读由 CSS 视口断点驱动，两种模式一致
- panel.js 自定义元素注册改守卫式，模块重复加载（升级时页签已开）不再抛"已定义"错误
- 「手动覆盖」限定为开关输出专属：二进制传感器输出不再显示该勾选与 ✋ 标记（实体侧本无控制面可锁）；试运行徽章现可正确显示 ✓（已写入）/ ✋（手动覆盖拦截）
- 工程面：tests/ 解禁入仓（smoke.py 零依赖冒烟 + web 层 pytest 用例），新增 `.github/workflows/validate.yml`（hassfest + HACS + pytest/真机 import 三 job），`pyproject.toml`/`requirements-dev.txt` 入仓

### 0.7.3 — 逻辑组双模式 + 条件节点实时状态

#### 逻辑组双模式（触发合并 / 条件组合）
- AND/OR/NOT 组恢复触发器信号口（0.7.0 能力回归），接哪个口定模式：
  - **触发逻辑模式**：多个触发器信号线连进组（可多条），任一触发即评估下游——组是触发合并器。注意：**停用触发器仍保留其信号覆盖**（锚点保持贯通，只是它自己不再触发），如需彻底停效请同时删除信号线或删除组。电平模型下贯通门**求值恒真**：挂在它下游的输出在启动初始化/立即评估/试运行等全量扫描中即判满足并动作（「常开锁存」，靠 off 链或手动覆盖关断）；「任一触发」决定的是**何时评估**，不是脉冲
  - **条件逻辑模式**：条件线组成 AND/OR/NOT 判定（原有）
- 对称互斥：连了一侧另一侧隐藏；删线恢复双口重新选模式
- schema：被信号引用的空组合法（触发逻辑锚点）；无引用空组仍拒绝

#### 条件节点实时状态
- 编辑器打开时（约 5 秒）轮询只读观察端点，**输出链可达**的条件节点显示当前判定 ✓/✗ 与实体当前值，节点边框随判定染色
- 观察与真实评估共享计时账本（持续/冷却语义一致），但**不会直接应用任何动作**（会推进计时账本，可能影响后续评估的时序）
- 触发逻辑组显示「触发合并 · 贯通」徽章

### 0.7.2 — 逻辑组独立分组,恢复触发器接口（与成员口互斥）
- 调色板把 AND/OR/NOT 单独列为「逻辑组」小节
- 逻辑组**恢复触发器信号口**：信号直达整组（0.7.0 能力回归,画布更省线）
- **成员先搭,信号冻结**：组的信号口仅在已有成员线时可用;信号连上后成员口冻结（改成员先删信号线）,无成员的组信号口变暗
- schema 重新允许 routes.conditions 携带组 id（持续门仍拒绝）;存储无需迁移（0.7.1 已展开的纯叶子覆盖保持,行为不变）
- 持续 duration 维持无信号口（0.7.1 裁决）;信号直达的组删光成员会自动断开信号并提示

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
