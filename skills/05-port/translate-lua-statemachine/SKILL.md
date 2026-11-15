---
id: translate-lua-statemachine
version: 0.1.0
stage: 05-port
execution: deterministic
status: implemented
reads: ["orchestration/m5-slice.json", "lua:**/assets/tacz/scripts/*state_machine*.lua", "schemas/state-machine-ir.schema.json"]
writes: ["work/m5/state-ir/<gun>.json", "reports/m5-state-ir.json"]
depends_on: []
acceptance: ["IR 通过 schemas/state-machine-ir.schema.json（required/类型/枚举/附加属性逐条校验）", "state 的 id 集合与 transitions 的 target 集合闭合，不出现未声明的 id", "每条 transition 的 guard 都能在 guards[] 里查到，unconditional 的 guard 为 null", "unresolved 每条都有 file/symbol/reason，且没有任何符号被静默丢弃", "同一输入连续两次运行输出逐字节一致（sha256 相同）", "scripts/ 下全部 *state_machine*.lua 都有语法级解析结论（parsed 或 failed+原因）", "coverage.flattened 之外的文件不得被描述为已展开"]
---

# translate-lua-statemachine

## 目的（判定问题）

TaCZ 的枪械行为有一半活在 Lua 状态机里：**哪个输入、在什么守卫下、把哪条轨道推进到哪个状态、播哪个动画**。移植到 Horizon 的 Rust 引擎时，如果只照着 Java 反编译结果写，会出现「逻辑已换弹、动画还在装填」这类跨层错位。

本 skill 只回答一个判定问题：**给定一份 Lua 状态机（含 require 继承链），能否在不运行 Lua 的前提下，把它化简成一张平台无关的状态/转移/守卫/动画表，并且对化简不到的部分如实记账。**

答案必须可复核：所有字符串都由 AST 渲染而来（不是正则截取），所有猜不出来的东西都进 `unresolved`。

## 输入契约

- `--slice`：`orchestration/m5-slice.json`。只用 `source.mod_root` / `source.lua` / `slice_id` / `version`，其余字段忽略。
- `--scripts-dir`（可选）：覆盖脚本目录；默认 `<mod_root>/assets/tacz/scripts`。
- `--gun`（可选）：枪械 id；默认从 `source.lua` 的文件名推导（`ak47_state_machine.lua` → `ak47`）。
- 只读，不修改 `work/TACZ-1.20.1/` 下任何文件。仓库内不写入任何 TaCZ 源码或资产内容。

## 输出契约

`work/m5/state-ir/<gun>.json` 严格符合 `schemas/state-machine-ir.schema.json`（`schema_version = 0.1.0`，`additionalProperties: false`）：

| 字段 | 语义 |
|---|---|
| `source_files` | 参与提取的 Lua 文件，相对 scripts 目录，字典序 |
| `inheritance` | require 链，被依赖方在前。`["tacz_default_state_machine_v2", "ak47_state_machine"]` |
| `tracks` | 被引用的轨道符号（`MAIN_TRACK` / `SWITCH_MODE_TRACK` …），含 `findIdleTrack` 的轨道行 |
| `inputs` | **转移里实际出现**的输入名（去重排序），与 `counts.inputs` 一致；声明了但没有任何转移引用的常量列在报告 `declared_inputs_not_referenced` |
| `guards[]` | `{id, expr, kind, source}`，`id` 按首次引用顺序编号 `g001..`，`kind ∈ ammo/fire_mode/attachment/state/other` |
| `states[]` | `{id, origin, source, entry[], transitions[]}` |
| `states[].entry[]` | `{animation, track?, loop, fade}`：进入或常驻该状态时**候选**播放的动画 |
| `states[].transitions[]` | `{on, guard, target, animations[], stop_animations[]?}`，**数组顺序 = 求值优先级**（TaCZ 是顺序 if，先命中先返回） |
| `counts` | 与数组长度严格自洽（`validate_ir` 会校验） |
| `unresolved[]` | `{file, symbol, reason}`，不得为空数组时声称 closed |

`reports/m5-state-ir.json` 只含统计、路径、符号名与判定，不含资产内容、不含绝对路径。

### `on` / `target` / 动画的语义约定

- `on` 是输入名（`INPUT_*` 或状态机内部触发名 `INPUT_MODE_SEMI`**原样保留、去掉 `this.`**）。
- `on = "*"` 表示**没有输入比较、靠每 tick 轮询条件触发**（如 `slide.normal` 的 `shouldSlide()`）。这不是「任意输入」，是「无输入」。
- **`on = "*"` 只允许搭配非空 `guard`**（条件驱动）。`on = "*"` 且 `guard = null` 是无条件通配，属于建模失败，`validate_ir()` 直接报错。AK-47 实测只有 2 条（`slide.normal` / `slide.slide`），报告 `condition_driven=2`。
- `target = "self"` 表示留在原状态（`return nil`、或只停止动画不返回状态表）。
- `animations[]` 是该转移里出现的动画名；**经本地 helper 内联后可能包含多个互斥分支的候选**（如 `reload_empty` / `reload_tactical` 并列），因为 `ext`、弹药数都是运行时值，静态无法裁剪。
- `stop_animations[]` 记的是**轨道符号**，不是动画名：TaCZ 的 `stopAnimation` 接收轨道句柄（`context:getTrack(STATIC_TRACK_LINE, MAIN_TRACK)` → `MAIN_TRACK`）。
- 守卫表达式归一化：`context:getXxx()` → `xxx`（去 `context:`、去 `get` 前缀、camel→snake，**零参不保留括号**），`context:getTrack(A, B)` → `track:B`，`this.main_track_states.x` → `main.x`，`and/or/not/~=` → `&&/||/!/!=`，括号只在内层是二元/一元运算时保留。运行时枚举名（`SEMI`/`AUTO`/`LOOP`）**保持大写原样**，便于回溯 `unresolved` 里的同名 R1 条目。
- `entry[]` 同时扫描 `entry()` 与 `update()` 里的 `runAnimation`，因此是「该状态可能播的全部候选」，不是确定的第一帧。
- `loop = true` 当且仅当**第三个实参是字面 `true`** 或**第四个实参是 `LOOP`**。真实签名是 `runAnimation(name, track, ?, playMode, fade)`，`playMode ∈ {LOOP, PLAY_ONCE_STOP, PLAY_ONCE_HOLD}`；任务书里「第四个参数为 true」的说法与实际脚本不符，本实现以脚本为准并在 `limitations` 里写明。
- `fade` 只取字面数值；`put_away_time * 0.75` 这类表达式记 `null`（不求值）。

## 稳定 id 规则

id 由「状态表在导出模块 `M` 里的位置」决定，与局部变量名无关（`local idle_state = setmetatable({}, {__index = ...})` 被装到 `M.main_track_states.idle`，id 就是 `main.idle`）。

命名空间前缀（`NAMESPACE_ALIASES`）：

| Lua 表 | id 前缀 |
|---|---|
| `main_track_states` | `main` |
| `bolt_caught_states` | `bolt` |
| `over_heat_states` | `heat` |
| `fire_mode_state` | `fire_mode` |
| `movement_track_states` | `movement` |
| `ADS_states` | `ads` |
| `slide_states` | `slide` |

顶层单状态对象（`SINGLE_STATE_ALIASES`）：`base_track_state` → `base_track`，`gun_kick_state` → `gun_kick`。

两条额外规则：

1. **终态哨兵**：表里带数值字段 `isfinal` 的状态（`main_track_states.final`）id 固定为 `final`，不带前缀。
2. **回退**：不在上述表里的表，用其局部路径把 `.` 换成 `_` 作为 id，并记一条 `R6 unresolved-target`——不允许静默丢弃。

因此 AK-47 的 18 个 id 是：`base_track`、`gun_kick`、`final`、`main.{start,idle,inspect}`、`bolt.{normal,bolt_caught}`、`movement.{idle,run,walk}`、`ads.{normal,aiming}`、`slide.{normal,slide}`、`fire_mode.{draw,semi,auto}`。

状态集合 = **`M:states()` 的种子 ∪ 从种子经 transition target 可达闭包**。`states()` 只给每条轨道行的当前状态，不是全集；只把 `states()` 当种子才不会漏 `main.idle` / `ads.aiming` 这类状态。不可达的表（`heat.normal`、`heat.over_heat`、`main.charge`、`movement.sprint`）写进报告的 `excluded_states`，不进 IR。

## 继承与 require 解析

- `require("tacz_default_state_machine_v2")` 按 TaCZ 的 `{namespace}_{path}` 约定反解：先试 `<id>.lua`，再逐个剥掉前缀段后试 `<rest>.lua`（`_` 与 `/` 两种拼法都试）。所以 `tacz_default_state_machine_v2` → `default_state_machine_v2.lua`。
- `setmetatable(child, {__index = parent})` 建立 `Table.meta`，`table_field()` 沿链查字段，与 Lua 的 `__index` 同义；`__index` 是函数时无法静态解析，记 `R7`。
- **覆盖即新表**：子状态机用 `setmetatable({}, {__index = 基类同名状态})` 造新表后，`origin = "gun"`；直接继承基类的状态 `origin = "base"`。AK-47 实测 `base 13 / gun 5`。
- **委托展开**：`return main_track_states.idle.transition(this, context, input)` 视为「把本状态未处理的输入交给基类」，递归展开被委托的函数体（`(表, 函数)` 去重，避免自环）。
- **遮蔽**：子状态机自己处理过的同名输入，基类里同 `on` 的转移不再输出（运行时不可达）。`on = "*"` 的轮询转移不做遮蔽。

## Lua 子集边界

支持的语法（写成真解析器，不是正则）：

- 注释：`--` 行注释、`--[[ ]]` / `--[=[ ]=]` 块注释
- 字面量：单双引号字符串（含转义）、长字符串 `[[ ]]`、十进制/十六进制数、`nil/true/false`
- 语句：`local a, b = ...`、`local function`、`function a.b.c(...)`、`function M:method(...)`、`if/elseif/else/end`、`while/do`、`repeat/until`、数值与泛型 `for`、`do`、`return`、`break`、赋值、表达式语句
- 表达式：优先级爬升（含右结合 `..` 与 `^`）、表构造 `{...}`（位置/`k = v`/`[k] = v`）、方法调用 `obj:method(args)`、字段链、`and/or/not`、字符串拼接
- 顶层只做「建表/建函数/别名/`setmetatable`」的求值；遇到顶层控制流不执行，记 `R3`

不支持的语法（**不会静默跳过**）：

| 情况 | 处理 |
|---|---|
| `goto` / `::label::` | 语法错误 → 该文件计入 `coverage.failed` |
| 转移/entry 内部的 `while` / `repeat` / `for` | 记 `R3`，不展开循环体 |
| 动态动画名（`"bolt_add_" .. flag`、局部变量） | 记 `R2`，该动画不入 `animations` |
| 动态轨道（`context:findIdleTrack(...)` 之外的构造） | 记 `R8` |
| 表构造里的动态键 `[expr]` | 记 `R3` |
| 函数值 `__index`、非表字面量元表 | 记 `R7` |
| 转移里调用本地 helper 且 helper 改写 `this.*` | 记 `R7`（动画已内联，状态改写未建模） |

## 已知 unresolved 类别

`reason` 一律以稳定前缀开头，报告按前缀分组：

| 前缀 | 含义 | AK-47 实测 |
|---|---|---|
| `R1 runtime-global` | TaCZ 运行时注入的自由名字（`INPUT_*`、`PLAY_ONCE_*`、`LOOP`、`SEMI`、`AUTO`）。符号名原样保留，值未知 | 24（ak47 9 条 + 基类 15 条，按「文件+符号」去重） |
| `R2 dynamic-animation` | 动画名不是字符串字面量（`animationName`） | 1 |
| `R3 unsupported-control-flow` | 未展开的控制流 / 动态键 | 0 |
| `R4 unresolved-delegation` | 委托目标解析不出来 | 0 |
| `R5 unresolved-require` | require 找不到或依赖解析失败 | 0 |
| `R6 unresolved-target` | `return` 的表没有稳定 id | 0 |
| `R7 local-helper-side-effect` | 本地 helper 改写状态机字段，效果未建模 | 1（`updateRunOverlay`） |
| `R8 unresolved-track` | 轨道解析不出来 | 0 |
| `R9 parse-error` | 语法级解析失败 | 0 |

`R1` 条目多不代表失败：它记录的是「这些名字不是脚本定义的，是运行时给的」。移植时它们必须由目标侧提供同名输入，不能改名。

## 报告字段

`reports/m5-state-ir.json` 除 `states/transitions/inputs/guards` 外还给：

| 字段 | 含义 |
|---|---|
| `origins` | base / gun 各多少状态 |
| `inheritance` | require 链 |
| `on_distribution` | 每个 `on` 值出现多少条转移（含 `"*"`），可直接核对转移表规模 |
| `condition_driven` | `on="*"` 的条数（应等于 `on_distribution["*"]`） |
| `delegated_fallbacks` | 委托展开后被子状态机同名输入遮蔽而丢弃的基类转移条数 |
| `declared_inputs_not_referenced` | 脚本声明但无转移引用的输入常量 |
| `excluded_states` | 在模块树里但不在 `states()` 可达闭包内、未进 IR 的状态表 |
| `dangling_targets` | 转移 target 不在 states 集合里的 id（应为空） |
| `coverage` | `discovered/parsed/failed/not_flattened/flattened` |
| `acceptance` | 上面几条断言的可机读结论 |

## 确定性保证

- 纯标准库；不读时间、随机数、环境变量；不联网；不调用模型。解析器对表达式嵌套设 200 层上限（超限记 `R9`），不做无界递归；53 个文件全量语法扫描实测 < 1s。
- 输出 `json.dumps(sort_keys=True, ensure_ascii=False, indent=2)` + 结尾 `\n`，UTF-8，`newline="\n"`。
- 所有集合在写盘前排序（`source_files`/`tracks`/`inputs`/`unresolved`/`states`/`guards`），guards 按首次引用重编号，转移动画去重保序。
- `source_files` 用相对 scripts 目录的文件名，报告用相对仓库根的路径；产物内不含绝对路径。
- `--self-test` 校验：schema + 两次独立分析字节比对 + 落盘文件比对。

## 如何复现

```bash
cd rustmc-skills

# 1) 生成产物（幂等）
python skills/05-port/translate-lua-statemachine/run.py \
  --slice orchestration/m5-slice.json \
  --out work/m5/state-ir/ak47.json \
  --report reports/m5-state-ir.json

# 2) 自检：schema + 幂等（不写文件）
python skills/05-port/translate-lua-statemachine/run.py \
  --slice orchestration/m5-slice.json --self-test

# 3) 数字核对
python -c "import json;d=json.load(open('work/m5/state-ir/ak47.json'));print(d['counts'])"
```

## 实测（TaCZ 1.20.1 / AK-47）

- `states=18`、`transitions=44`、`inputs=22`、`guards=8`；`origins: base 13 / gun 5`。
- `condition_driven=2`（两条 `on="*"` 都有非空 guard）；`delegated_fallbacks=7`（委托展开后被 gun 同名输入遮蔽、运行时不可达而丢弃的基类转移）。
- `declared_inputs_not_referenced`：`INPUT_CHARING` / `INPUT_CHARING_EXIT` / `INPUT_COOLING_HEAT` / `INPUT_OVER_HEAT`（基类声明但 AK-47 未启用过热轨道，没有转移引用）。
- 继承链 `["tacz_default_state_machine_v2", "ak47_state_machine"]`，`source_files` 两个。
- `coverage`：`discovered=53`、`parsed=53`、`failed=0`、`not_flattened=51`。**只有 ak47 与其基类两个文件做了完整展开**，其余 51 个文件仅语法级解析。
- `unresolved=26`：`R1` 24 / `R2` 1 / `R7` 1，每条都有 file + symbol + reason。
- 连续两次运行 `sha256` 一致（IR 与报告都逐字节相同）。

## 不得声称已完成的部分

- **没有运行 Lua**，也没有对比过真实运行时的转移序列。IR 是静态近似，不是 oracle。
- **`update()` 的触发条件没有回填到转移**：`bolt.normal.update` 里 `if isNoAmmo then context:trigger(INPUT_BOLT_CAUGHT)` 的条件不会出现在 `on=INPUT_BOLT_CAUGHT` 的 `guard` 里。IR 的 `on` 只表示「收到该输入」。
- **`elseif` 分支只保留自身条件**，不叠加前序分支条件的取反：TaCZ 的 `if/elseif` 分支条件是互斥常量比较（`SEMI` / `AUTO`），叠加只会制造噪声；但若上游写出可同时成立的分支，IR 不会替它补互斥性。
- **`animations` 是候选集**，不是确定结果：`ext` 等级、弹药量、分支顺序都未求值。
- **只展开了 2 个文件**：另外 51 个 `*state_machine*.lua` 只证明「语法能解析」，不证明语义正确、不证明能翻译。
- **`tracks` 不是 Horizon 轨道语义**：只收集符号名，未映射到目标侧的轨道/轨道行模型。
- **没有生成任何 Rust 代码**，也不判断 IR 是否足够驱动目标引擎；那是下游 skill 的事。
- **未覆盖其他枪**（只有 AK-47 一支真实样本），未做跨枪回归。
