---
id: port-native-module
version: 0.1.0
stage: 05-port
execution: deterministic
status: implemented
reads: ["orchestration/m5-slice.json", "work/m5/state-ir/ak47.json", "schemas/state-machine-ir.schema.json", "third_party/horizon/native-hooks.json", "third_party/horizon/docs/native-mods.md"]
writes: ["work/m5/native/tacz_ak47_pilot/**", "reports/m5-native-module.json"]
depends_on: ["translate-lua-statemachine"]
acceptance: ["engine 仅依赖 std，cargo test --offline 全绿", "engine 的 STATES 与 IR 的 states[].id 集合相等，不等则非零退出", "horizon-mixin.toml 的 hook 名与 hook_version 在 native-hooks.json 中存在", "重复运行输出字节一致", "bindings 为空的接线缺口在报告中标注为 unverified，不声称游戏内可开火"]
---

# port-native-module

## 目的

把 `translate-lua-statemachine` 产出的平台无关 IR，落成一个 Horizon **原生 mod bundle**：`horizon-mixin.toml` + 注入 helper + 一个可独立测试的**纯 Rust engine crate**。它只搬运数值参数与状态名，不复制 TaCZ 的 Lua 文本或资产。

```bash
python skills/05-port/port-native-module/run.py \
  --slice orchestration/m5-slice.json \
  --ir work/m5/state-ir/ak47.json \
  --out work/m5/native/tacz_ak47_pilot \
  --report reports/m5-native-module.json
```

可选参数：`--catalog`（默认 `third_party/horizon/native-hooks.json`）、`--horizon-root`（默认 `third_party/horizon`，相对仓库/工作区根均可解析）、`--cargo`、`--skip-cargo-test`（仅供无工具链环境，交付前禁用）。

## 产物结构

```
tacz_ak47_pilot/
  horizon-mixin.toml      # [mod] / [compatibility] / 2×[[injection]] / 1×[[crate]]
  on_use.rs               # helper：占位，调用 engine 的接缝（bindings=[]，无上下文）
  on_tick.rs              # helper：占位，每 tick 推进冷却/换弹的接缝
  data/ak47.json          # params 原样副本 + derived tick 数（bundle 数据）
  engine/
    Cargo.toml            # 仅 std，无依赖；[lib] ak47_engine + [[bin]] trace
    data/ak47.json        # 与根 data 字节一致，供 include_str!("../data/ak47.json")
    src/lib.rs            # GunState / Input / Event / 状态机
    src/consts.rs         # 手写常量（数字出自 slice，逐条给出来源）
    src/states.rs         # 由 IR 生成：STATES + 角色常量 + fallback 列表
    src/bin/trace.rs      # 文本剧本 → JSONL
    tests/ak47.rs         # 5 条集成测试（另有 8 条 lib 单测）
    tests/fixtures/burst.trace
```

`data/ak47.json` 在 bundle 根与 crate 内各放一份是刻意的：crate 被 `[[crate]]` 暂存时只复制自己的目录（`docs/native-mods.md`「The mod's crate」），根目录那份给内容包/排查用；生成时两份字节相同。

## 注入点从哪来

- 唯一来源是 `third_party/horizon/native-hooks.json`（434 个 hook，全部 `version = 1`，截至本快照）。本 bundle 只用两个：
  - `use_item`（`native_use_item`，server，`cancellable = true`）；
  - `player_tick`（`native_player_tick`，server，`listen`）。
- `native_component` / `native_set_component` 是 `crates/horizon-client/src/game/native_components.rs` 的 **host 方法**，不是 hook，不能写成 `[[injection]]`。
- 生成期会拿 `hook` + `hook_version` 去 catalog 预检；缺失即 `E_HOOK_UNKNOWN`，版本不符即 `E_HOOK_VERSION`，生成器非零退出。

## `[[crate]]` 规则

`engine` 被 `cargo-horizon-mod` 暂存为 `native-crates/<mod>/<crate>/` 并加进 `horizon-client` 的依赖，因此：

- 不能依赖 `horizon-client`（会成环）；
- 不能有 `path` / `git` 依赖；
- 只能依赖 Horizon `Cargo.lock` 里已有的 registry crate；
- 不能自带 `Cargo.lock`、`[workspace]` 或独立构建。

本 engine **零依赖**，所以这三条自动满足。`cargo test --offline` 直接在这个目录跑；生成器测试后会删掉本地 `Cargo.lock` 与 `target/`，避免污染可打包的 bundle。

## 为什么 `bindings = []`

`bindings` 决定 horizon-mixins 往 helper 里注入哪些参数（`game`、玩家、物品栈……）。本机没有 `horizon-mixins` 的生成代码/源码可核对签名，写一个猜的绑定会在真实构建时编译失败，甚至静默改语义。因此：

- `bindings = []`，helper 只留空函数作为接缝；
- 报告写 `honesty.wiring = "placeholder"`、`bindings = "unverified"`、`helper_signature = "unverified"`；
- **不声称**当前 bundle 能在游戏里开火；engine 的测试只证明纯逻辑。

## engine 与 IR 的对应关系

- `src/states.rs` 的 `pub const STATES: &[&str]` 原样复制 IR 的 `states[].id`（保持 IR 顺序）。`run.py` 写完后会**重新解析 Rust 源码**并断言集合相等 + 数量相等；不等则 `E_STATE_SET_MISMATCH` 非零退出。
- `pub const IR_INPUTS: &[&str]` 同样原样复制 IR 的 `inputs`，并由 `E_INPUT_SET_MISMATCH` 断言集合相等；它只用于追溯，**不代表**每个输入都有运行时 handler。真正实现的 6 个动作在 `MODELED_INPUTS`。
- 引擎只认识一组角色（`IDLE / INSPECT / DRAW / PUT_AWAY / FIRE_AUTO / FIRE_SEMI / RELOAD_EMPTY / RELOAD_TACTICAL`）。IR 若没有换弹状态，角色回退到 `idle`，并写进 `ROLE_FALLBACKS` 与报告的 `state_alignment.role_fallbacks`——不偷偷改名、不伪造状态。
- 输入侧区分两件事：`IR_INPUTS` 与 IR 集合相等（可断言），但引擎只建模 6 个运行时输入（`Shoot / ReleaseTrigger / Reload / Inspect / PutAway / FireSelect`）；其余 IR 动画输入记在 `input_alignment.unmodeled_ir_inputs`，不声称运行时等价。`ReleaseTrigger` 没有对应的 IR 常量：TaCZ 半自动靠内部 latch 重置。
- 数值：`consts.rs` 手写常量，逐条 `source` 指向 `orchestration/m5-slice.json#/params/...`；tick 数统一 `ceil(seconds × 20)`：
  - 600 rpm @ 20 tps → 2 tick/发；
  - 空仓换弹 2.6 s → 52 tick 补满（feed 2.25 s = 45 tick 仅记录）；
  - 战术换弹 2.0 s → 40 tick；draw 0.35 s → 7 tick；put_away 0.57 s → 12 tick。
- `data/ak47.json` 被 `include_str!` 进 engine，并有测试断言其中含 `"ammo_amount": 30` / `"rpm": 600`，证明数据确实随 crate 走。

## trace

`engine/src/bin/trace.rs` 读纯文本剧本（一行一条）：

```
tick <n>
shoot | release | reload | inspect | putaway | fireselect
expect <EventKind>
```

动作先入队，由下一次 `tick` 推进时应用；`expect` 检查下一次步进的事件，不匹配退出 2。每行输出：

```json
{"tick":0,"ammo":29,"events":[{"kind":"Shot","ammo_after":29}]}
```

```bash
cd work/m5/native/tacz_ak47_pilot/engine
cargo run --offline --bin trace -- --script tests/fixtures/burst.trace
```

## 幂等与验证

- 生成器不写时间戳/绝对时间；JSON 统一 `sort_keys` + 2 空格缩进；重复运行 bundle 与报告字节一致。
- 报告 `engine.cargo_test` 只记录稳定字段（`passed` / `failed` / 套件计数），不写入耗时或原始日志，除非失败。
- 生成期预检与运行期预检是两层：本 skill 只做 `hook`/`hook_version`；`verify-hook-catalog` 还会查 helper 文件、crate 依赖与 `horizon_revision`。

## 没有验证的部分

| 项 | 状态 | 原因 |
|---|---|---|
| bindings / helper 签名 | `unverified` | 没有 horizon-mixins 生成 API 的离线副本 |
| 游戏内开火、换弹、第一人称表现 | `not_observed` | 无头服务端没有玩家，触发不了右键 |

> **M5b 更新**：`native-build` 那一行已经不再是 `not_run`。bundle 经 `horizon-mixins 0.6.0` 的 `plan` / `apply` 真跑后编进了 `horizon-client`，无头服务端首 tick 打出了 `load probe … engine states=18`——证明「编进去 + 钩子被调用 + engine 链接」。仍然**没有开火**：`bindings = []` 拿不到物品栈。

### horizon-mixins 0.6.0 的四条硬约束（M5b 实测，已写进生成器）

| 错误码 | 规则 | 本 skill 的处理 |
|---|---|---|
| `E_CRATE` | bundle 的 crate 不能带 `Cargo.lock` | `cargo test` 后清理 `engine/target` 与 `engine/Cargo.lock` |
| `E_REVISION` | 快照无 `.git` 时，任何 `snapshot:` 值都被拒 | 无 git 时**省略** `[compatibility]`，不钉版本；指纹只写报告 |
| `E_INVALID_HELPER` | helper 恰好一个**私有**函数，不能有文件级属性 | 生成 `fn on_use()` 而不是 `pub fn`；`//!` 一律改 `//`（`//!` 会变成 `file.attrs`） |
| `E0425` | `STATES` 在 `states` 模块，不在 crate 根 | load probe 用 `ak47_engine::states::STATES` |

### 运行时探针

bundle 里除了 `use_item` / `player_tick`，还注入一个 `server_tick` 的 `on_load.rs`：只在第一次 tick 打印一行，然后什么都不做。

```
[tacz_ak47_pilot] load probe: first server tick, engine states=18
```

它**不是玩法**，只用来在无头服务端上证明三件事：bundle 编进去了、钩子点活着、engine 链接成功。别拿它当「mod 能用了」。
