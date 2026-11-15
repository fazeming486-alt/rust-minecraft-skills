# 08 · M5 执行报告：AK-47 单枪竖切

> 状态：v0.9（2026-11-15）。M5 第一次产出**能被目标侧工具接受**的东西：一个官方校验通过的 `.hmod`、一个 `cargo test` 全绿的纯 Rust engine、一份逐 tick 对得上的行为差分。没有 `native-build`，所以还不能说「游戏里能打」——这条边界写在每一份报告里。

## 1. 这一步到底证明了什么

| 层 | 产物 | 证据 | 等级 |
|---|---|---|---|
| 内容 | `work/m5/tacz_ak47_pilot.hmod`（6227 B） | `cargo-horizon-mod check --kind mod --json` → `ok: true` | `verified_by_official_tool` |
| 状态机 | `work/m5/state-ir/ak47.json` | 18 状态 / 44 转移 / 8 守卫 / 22 输入，schema 通过、幂等 | `verified_by_schema` |
| 逻辑 | `work/m5/native/tacz_ak47_pilot/engine` | `cargo test --offline` 13/13，纯 std、零依赖 | `verified_by_test` |
| 接线 | `horizon-mixin.toml`（2 个注入点） | 与 `native-hooks.json` 目录逐条对上，负例报 `E_HOOK_UNKNOWN` | `source_only` |
| 行为 | `reports/m5-diff.json` | 200 tick 剧本 23/23 事件匹配、drift 0；负例失败 | `verified_by_test` |

**没证明**：物品在游戏里出现、开火被真正调用、第一人称表现、动画、网络同步、伤害结算。`bindings = []`，`native-build` 未跑。

## 2. 五步链路

### 2.1 Lua 状态机 → IR（`translate-lua-statemachine`）

输入是 TaCZ 的 `ak47_state_machine.lua` 与它 `require` 的 `tacz_default_state_machine_v2.lua`。解析器是自己写的 Lua 子集解析器（不是正则、不跑 Lua），展开 `setmetatable` 继承后得到：

- 18 个状态：`main.{start,idle,inspect}`、`bolt.{normal,bolt_caught}`、`ads.{normal,aiming}`、`movement.{idle,walk,run}`、`slide.{normal,slide}`、`fire_mode.{draw,semi,auto}`、`gun_kick`、`base_track`、`final`；其中 `origin=base` 13 个、`origin=gun` 5 个。
- 44 条转移、22 个被实际引用的输入、8 个守卫。
- 26 条 `unresolved`：`INPUT_*` / `SEMI` / `AUTO` 这类运行时注入常量只保留符号名，静态拿不到数值——**显式记录，不猜**。
- 覆盖率：53 个 `*state_machine*.lua` 全部做过语法级解析（failed = 0），只有 AK-47 与基类做了完整展开，其余 51 个如实标 `not_flattened`。

三轮才收敛的问题（都写进了报告）：

1. `transitions[].on` 一开始全是 `"*"`，输入藏在 guard 的 `(input == INPUT_RELOAD)` 里 → 改为 `on` 直接取输入名，guard 只留剩余条件。
2. 基类与子类叠加导致重复转移（51 → 44）→ 按 `(on, guard, target, animations)` 去重，保留 `origin=gun`。
3. 剩下 2 条 `on="*"` 是 `slide` 的**每 tick 条件驱动**转移（守卫 `should_slide() && ...`），不是委托 → 保留，并在 schema 里把 `*` 定义为「guard 非空的条件驱动」。

`schema` 也补了一条：`*` 只允许出现在 guard 非空时，无条件通配是非法的。

### 2.2 内容包（`build-content-mod`）

产物结构（6 个文件）：

```
horizon-mod.toml                      api="0.2" side="both" capabilities=["registries"]
data/tacz_ak47_pilot/horizon/item/ak47.json      template=minecraft:crossbow, max_stack_size=1
assets/tacz_ak47_pilot/items/ak47.json           26.3 的 items 定义
assets/tacz_ak47_pilot/models/item/ak47.json     parent=item/generated, layer0
assets/tacz_ak47_pilot/textures/item/ak47.png    从 TaCZ slot 贴图逐字节拷入 work/
assets/tacz_ak47_pilot/lang/en_us.json
```

两次 `build` 的 SHA-256 完全一致（`1f5b4b50…`），说明官方打包器在这个输入上是确定性的。

**实测纠正**：任务原稿把 `minecraft:max_stack_size` 放进 `components`，官方 `check` 直接拒绝并提示 `set max_stack_size instead`。改成顶层字段后通过。这不是我们放宽了校验，是按目标侧的真实约束改的。

负例：删掉 item 的 `template` 后，官方 `build` 报 `missing field template` 并退出 1。校验器是有效的。

### 2.3 原生模块（`port-native-module`）

```
work/m5/native/tacz_ak47_pilot/
  horizon-mixin.toml        [[injection]] use_item(v1) / player_tick(v1)，bindings=[]
  on_use.rs / on_tick.rs    helper 占位，调用 engine
  data/ak47.json            数值快照
  engine/                   纯 std crate：状态机 + consts + states + trace bin + 13 个测试
```

engine 的 18 个状态 id 与 IR **集合相等**（不是数量相等），改名即非零退出。`cargo test --offline` 13/13，覆盖连发 30 发空仓、半自动需松扳机、战术换弹 40 tick、换弹中不能开火、切模式。

### 2.4 注入点预检（`verify-hook-catalog`）

解析 `horizon-mixin.toml`（自带 TOML 子集解析器），逐条对照 `native-hooks.json`：2 个注入点、2 个 helper、1 个 crate，434 个 hook 的目录里全部命中，`errors = []`。

负例把 `use_item` 改成 `use_itme`：立即返回 `E_HOOK_UNKNOWN`，并给出最接近的 3 个候选（`use_item` / `use_item_on` / `use_animation`）。这把原本要等 12 分钟游戏构建才会暴露的错误提前到了秒级。

一个环境事实：本机的 `third_party/horizon` **不是 git checkout（没有 `.git`）**，所以 `horizon_revision` 无法用 commit；预检改用 `native-hooks.json` 的内容指纹 `snapshot:d709ee26dc82`，并在报告里明确「这只证明同一份快照，不等于上游 HEAD」。

### 2.5 行为差分（`playable-diff-harness`）

200 tick 剧本：连发 10 发（600 rpm → 每 2 tick 一发）→ 战术换弹（2.0 s → 40 tick）→ 5 发 → 切 semi → 单发 3 次 → 再换弹。

结果：**23/23 事件匹配，max drift = 0**，`ammo_after` 逐发相等；状态集合相等；把期望弹匣改成 29 的负例在第一个 `Shot` 上就被抓住。产出同时写了官方形状的 `harness/result.json`，`report.rs` 可以消费。

## 3. 五个 skill 与派发

| 任务 | skill | 角色 | 结果 |
|---|---|---|---|
| m5-01 | `translate-lua-statemachine` | state-machine-translator | COMPLETE（3 轮修正） |
| m5-02 | `build-content-mod` | content-mod-packager | COMPLETE |
| m5-03 | `port-native-module` | native-port-engineer | COMPLETE |
| m5-04 | `verify-hook-catalog` | hook-catalog-verifier | COMPLETE |
| m5-05 | `playable-diff-harness` | slice-harness-runner | COMPLETE |

复杂度评估：`score 0.4456 / band M / 2 workers`，硬门槛 2（`animation_driver` 缺口、`local-only`）。5 个任务包 / 3 个 wave（`work/dispatch/m5/index.json`）。

分工方式沿用 ADR 0007：3 个子 agent 各领 1–2 个任务、自己跑命令、自己写 result；主 agent 只做契约、语义复核与汇总。**语义复核确实抓到了东西**：`on="*"`、重复转移、`inputs` 集合不匹配三处都是主 agent 读 IR 时发现的，`collect-results` 的哈希与越界扫描查不出来。

## 4. 复现

```bash
# 1. 状态机 IR
python skills/05-port/translate-lua-statemachine/run.py --slice orchestration/m5-slice.json \
  --out work/m5/state-ir/ak47.json --report reports/m5-state-ir.json

# 2. 内容包（官方工具需先 cargo build -p cargo-horizon-mod --offline）
python skills/05-port/build-content-mod/run.py --slice orchestration/m5-slice.json \
  --official-tool third_party/horizon/target/debug/cargo-horizon-mod.exe \
  --report reports/m5-content-mod.json

# 3. 原生 bundle（含 cargo test）
python skills/05-port/port-native-module/run.py --slice orchestration/m5-slice.json \
  --ir work/m5/state-ir/ak47.json --out work/m5/native/tacz_ak47_pilot \
  --report reports/m5-native-module.json --cargo D:/RUST重写mc项目/dev/cargo/bin/cargo.exe

# 4. 注入点预检
python skills/05-port/verify-hook-catalog/run.py --bundle work/m5/native/tacz_ak47_pilot \
  --catalog third_party/horizon/native-hooks.json --horizon-root third_party/horizon \
  --report reports/m5-hook-catalog.json

# 5. 差分
python skills/09-verify/playable-diff-harness/run.py --slice orchestration/m5-slice.json \
  --ir work/m5/state-ir/ak47.json --engine work/m5/native/tacz_ak47_pilot/engine \
  --cargo D:/RUST重写mc项目/dev/cargo/bin/cargo.exe --report reports/m5-diff.json
```

## 5. 边界与下一步

- **接线未验证**：`bindings = []`，helper 的函数签名没有和 horizon-mixins 生成的 Host API 对过；`native-build` 未跑。
- **行为只覆盖 C1**：开火/换弹/切模式/弹药；后坐、散布、命中、伤害、同步都没有。
- **动画仍 `unbound`**：IR 里的 44 条转移只是状态层，73 个 animation.json 与骨骼插值在 Horizon 侧仍无消费者。
- **期望值不是 oracle**：来自 TaCZ 的 `ak47_data.json`，不是真机录制；M3b 仍未做。

M5b 只做一件事：`horizon-launcher native-build` 把 bundle 编进游戏，在可运行实例里用 `use_item` 真正打出第一发。在那之前，任何「AK-47 已经搬过来」的说法都不成立。
