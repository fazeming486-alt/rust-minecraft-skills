# ADR 0011 · 单枪竖切优先，内容包与原生模块分离

- 状态：已采纳（v0.9）
- 日期：2026-11-15
- 关联：ADR 0005（Horizon 绑定）、ADR 0008（三维度合规）、ADR 0009（跨层切片）、ADR 0010（M3/M4）

## 1. 背景

M0–M4 把「判定 → 映射 → 资产转换 → 差分契约 → 泛化」这条方法链跑通了，但仓库里 **0 个 `.rs`、0 个 `.hmod`**：所有结论都停在「分类正确」「映射存在」「转换可逆」，没有一次「目标侧真的吃下了这个产物」。

M5 要回答的问题不是「还能不能再加规则」，而是：**一把枪从 TaCZ 到 Horizon，最短的可验证闭环是什么？**

三个未知数挡在中间：

1. 内容 API 到底能声明什么（物品、模型、组件）；
2. 原生 mod 到底怎么编译、怎么接线（`.hnmod` 是 horizon-mixins bundle，不是动态库）；
3. 动画（骨骼 / 关键帧 / Lua 状态机）在目标侧有没有落点。

## 2. 决策

### D1 · 竖切优先于整包

不做「TaCZ 全量移植」，做 **AK-47 一把枪** 的端到端竖切。理由：整包移植的 82%（C3 388 + C5 267 / 799）是重写，任何工期估算在竖切跑通前都是猜；竖切能在最小代价下把三个未知数一次性变成已知。

竖切必须包含：状态机 IR、内容包、原生模块、注入点预检、逻辑差分。只做资产搬运不算竖切。

### D2 · 内容与逻辑分离，`.hmod` 里不放代码

- `.hmod` 只装 `horizon-mod.toml` + `data/` + `assets/`，走 content API 0.2 的 `registries`；官方 `cargo-horizon-mod` 会**拒绝**带 `Cargo.toml` 的目录。
- 任何行为（开火、换弹、弹药状态、后坐）必须落在 `.hnmod`（horizon-mixins bundle）：`horizon-mixin.toml` + helper `.rs` + 可选 `[[crate]]`。
- 因此「物品注册」与「物品行为」是两次交付，不能用「内容包能加载」冒充「枪能用」。

备选方案「把 WASM 组件塞进 `.hmod`」被否：本机没有 `wasm32-unknown-unknown` 目标与 `wasm-tools`，且当前文档把代码路径明确指向 native bundle。

### D3 · 状态机 IR 是唯一跨层契约，Lua 不进运行期

TaCZ 的动画行为在 `*_state_machine.lua`（53 个 `state_machine` 脚本，AK-47 依赖 `tacz_default_state_machine_v2` 基类）。Horizon 不读 Lua，也没有骨骼插值。

所以链路固定为：**Lua → 平台无关 IR（`schemas/state-machine-ir.schema.json`）→ Rust engine**。IR 是唯一被两侧引用的东西：内容侧只认状态名，逻辑侧只认输入与守卫；任何一方改名都要在 IR 层先改，避免「逻辑已换弹、动画还在装填」。

IR 必须显式带 `unresolved`，解析不了的符号不许静默丢弃。

### D4 · 编译前做注入点预检

`horizon-mixins` 在构建期才报 `E_HOOK_UNKNOWN` / `E_HOOK_VERSION`，而一次构建要重建 `horizon-client`（约 12 分钟、数 GB）。把这一步前移成确定性检查：解析 `horizon-mixin.toml`，逐条对照 `native-hooks.json` 的 name/version，校验 helper 与 `[[crate]]`，并核对 `horizon_revision` 与快照 HEAD。

预检不是编译器的替代品：它只保证「名字与版本存在」，不保证绑定签名正确。绑定（`bindings`）在 M5 阶段留空并显式标注 `unverified`。

### D5 · 纯 std 的 engine crate 是唯一可离线验证的行为层

Horizon 的 crate 规则不允许 mod 的 crate 依赖 `horizon-client`（Cargo 循环），这反而给了我们一个可测试单元：engine 只依赖 std，`cargo test` 与 `cargo run --bin trace` 都不需要游戏。

于是行为验证分两层：

| 层 | 能证明 | 不能证明 |
|---|---|---|
| engine trace 差分 | 数值与状态转移（射速、弹匣、换弹时长、模式切换） | 游戏内是否被调用 |
| 官方 `.hmod` 校验 | 内容能被加载器接受 | 物品行为是否正确 |

### D6 · 诚实分级，不用「能编译」冒充「能用」

M5 的产物按四级标注，任何报告不得跨级：

1. `verified_by_official_tool`：`.hmod` 过了 `cargo-horizon-mod check`；
2. `verified_by_test`：engine `cargo test` 全绿、trace 差分 PASS；
3. `source_only`：bundle 的注入点通过目录预检，但没 `native-build`；
4. `unbound`：动画驱动、第一人称表现、命中与同步仍未验证。

## 3. 后果

- 新增 5 个 skill（`translate-lua-statemachine`、`build-content-mod`、`port-native-module`、`verify-hook-catalog`、`playable-diff-harness`），新增 stage `05-port`。
- 所有 TaCZ 派生内容（贴图、由 Lua 转出的 Rust）只留 `work/`，仓库只提交工具、schema、模板与统计报告。
- 已知欠账：`bindings = []`、`native-build` 未跑、动画仍 `unbound`、真机录制（M3b）未做。
- 下一个里程碑（M5b）只做一件事：`native-build` 把 bundle 编进游戏，并在可运行实例里观测第一人称开火；在此之前，不得对外说「AK-47 已经能打」。
