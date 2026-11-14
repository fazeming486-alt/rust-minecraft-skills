# ADR 0005 · Horizon 目标侧已明确：绑定表、tier 路由与政策边界

- **状态**：Accepted（v0.3，2026-11-15）；§4 已由用户拍板 **方案 C**，正式决策见 ADR 0006，执行见 `docs/04-roadmap.md`
- **决策者**：本仓库（用户授权「下一步你自己制定」，并开放工作区除 `亡灵战争_整合包` 外的全部资产）
- **相关**：`target/horizon.capabilities.json`、`docs/adr/0001-target-agnostic-contract.md`、`docs/03-empirical-calibration.md`

## 背景

ADR 0001 把 Horizon 架构当作未知量，用「能力契约层」把不确定性隔离在 `target/horizon.capabilities.json` 一张表里。现在这个不确定性**已经消除**：本机 `third_party/horizon` 是 Horizon 源码快照，含结构化钩子清单 `native-hooks.json` 与完整设计文档。

关键事实（均来自快照，非推测）：

| 项 | 值 |
|---|---|
| 底座 | Rust + wgpu/Vulkan，MIT，目标 Minecraft 26.3 |
| mod 形态 | **content mod `.hmod`**（纯数据/资产，API 0.2）/ **native mod `.hnmod`**（Rust via horizon-mixins） |
| Java mod | **不能原样运行**；Fabric/NeoForge jar 只有 data 与 assets 能 carry-over。Java bridge 是可选下载、默认关闭 |
| 原生钩子 | `native-hooks.json`：**434 hooks / 177 helpers**，318 个 hook 带 `neoforge` 事件映射；contract 分 listen / collect / cancel / replace |
| API tier | `data`(0.2) → `logic`(0.3) → `machines`(0.4) → `deep`(0.5) → `client`，另有 `none` |
| 官方流水线 | import → inventory → classify → tier → dependency order → carry-over / agent port → **harness（Java oracle vs port）** → coverage report |
| 现状 | roadmap 明示 modpacks 目标「set aside in favour of compatibility through the browser」；ATM10 仅 **42/496** mod 部分搬运 |

## 决策 1：把「全 unbound」占位表换成真实绑定

`target/horizon.capabilities.json` 26 个 capability 现在按快照逐项绑定，每项附 `status`、`mechanism`、`tier`、`evidence`（指向 Horizon 仓库内路径）。分布：

- **implemented 17 项**：`event_hook`（434 hooks）、`input_event`、`tick`、`raycast`、`damage_apply`、`asset_handle`、`resource_reload`、`localization`、`content_pack`、`render_handle`、`audio_play`、`gui_surface`、`registry_entry`、`tag_lookup`、`config_read` 等。
- **declared 8 项**：由通用 hook 组合或 0.4/0.5 roadmap 提供，无专用稳定 API（`network_sync`、`persistent_data`、`entity_state`、`random_source`、`scheduled_task`、`cooldown`、`entity_query`、`block_query`、`collision_query`、`particle_emit` 中的保守项）。
- **unbound 1 项**：**`animation_driver`**。当前快照没有任何骨骼动画 hook/helper；0.5 规划「Bedrock geometry + animations」数据模型，但尚未落地且 modpacks 目标已搁置。

**这一项就是 TaCZ 类 mod 的命门**：枪械的第一人称动作、换弹/拉栓/瞄准动画全部依赖它。ADR 0001 的假设在此得到验证——上游 skill 一行未改，只填了这张表，就得到了可度量的缺口清单。

## 决策 2：C 处置标签增加一层 Horizon tier 路由

在 `C1–C6` 之后增加目标侧路由（不改动五维分类本身）：

| 处置 | Horizon tier | 落地形态 |
|---|---|---|
| C4 数据转换 | `data` (0.2) | `.hmod` content mod：assets/ + data/、registries JSON |
| C1 纯逻辑 | `logic` / `deep` | native mod + `server_tick` / `input_key` / `projectile_*` hooks |
| C2 契约重写 | `deep` | native mod；缺钩子时按 `docs/native-hooks-neoforge.md` 申请命名 hook |
| C3 平台适配 | `logic` / `machines` | hook + 0.4 `net` / `storage` |
| C5 舍弃/替身 | `none` 或 hook 替代 | Horizon 内置替代（GeckoLib → animated models、JEI → recipe viewer、性能 mod → 引擎） |
| C6 人工裁决 | — | Java oracle 行为观测 + 人工签署 |

`@SubscribeEvent` / Mixin 不是翻译对象，而是映射到 `native-hooks.json` 的 `neoforge` 字段对应的命名 hook。`horizon-port-pack events` 已能列出 mod 的监听器与对应 hook；我们的 `api-mapping-table` 应直接消费这份清单，不要另造一套。

## 决策 3：验收链路与官方 harness 对齐

Horizon 官方的「每个 mod 一个 harness：dev-only Java oracle vs port」与我们 `diff-test-harness` 的「Java 侧录制状态序列 → Rust 侧重放比对」是同一件事。下一步把 `horizon-ctl`（控制套接字、截图/状态/操控）接入验收 skill，用官方 oracle 做录制端。

## 决策 4（**已拍板：方案 C**）：与 Horizon cleanroom 政策的边界

**发现一个真实冲突。** `docs/modpacks.md` §Licences 第 4 条是 Horizon 的工程政策：

> *Mod code never enters this repository, and nobody reads it. … A mod's code is never decompiled, read, quoted or paraphrased, by people or agents. Ports are written only from the mod's observed behaviour (the oracle and the harness), its own data files and its public documentation.*

而 rustmc-skills v0.2 的方法核心正是**反编译 TaCZ jar + 解析 class 常量池 + 解析源码注解/字符串**来做分类。我们虽未复制或复述任何实现、报告只含统计与 unit_id，但「读代码结构」这一层与官方政策不一致。若目标是让成果被 Horizon 生态采用、或日后进入其仓库/发布链，这会是硬障碍。

三条路，**用户已选 C**：

| 方案 | 做法 | 代价 |
|---|---|---|
| A 独立研究仓库 | 明确 rustmc-skills 不进入 Horizon 上游/发布链，仅本地方法论研究，文档标注政策边界 | 成果无法贡献给上游；发布链仍需另做 |
| B 完全对齐 cleanroom | 事实提取降级为 `metadata-only`（只读 jar 元数据、资源清单、注解签名，不读方法体/常量池字符串），用行为 oracle 替代 | v0.2 的双轨实验与 665 个常量池证据失效，规则需重做 |
| **C 混合（推荐）** | 按许可证分档：自有代码 / MIT 等明确授权 → 完整双轨；ARR / NC / ND / 未授权 → 强制 `metadata-only` + 行为 oracle。新增 `policy profile` 作为 intake 的必填输入 | 需给 `parse-bytecode` 加模式开关、给 manifest 加 `policy_mode` 字段 |

注意 TaCZ 本身：代码 GPL-3.0、**资产 CC BY-NC-ND 4.0（禁止演绎）**，本地研究可行，发布需授权。当前仓库只存统计，未越界；但需要把这个判断写进流程，而不是靠人记着。

**落地状态**：C 已由 ADR 0006 正式化，`policy-gate`、三档降级提取、`default_deny` 与 `review_required` 在 v0.4 实现；执行顺序见 `docs/04-roadmap.md` M0。v0.2 的代码侧双轨实验在授权范围内保留，资产侧按 ND 降级为 `oracle-only`。

## 后果

**正面**：ADR 0001 的隔离设计被证明有效——目标侧从「完全未知」到「26 项绑定 + 1 项明确缺口」，上游规则、schema、12 个 skill 一行未改。Horizon 官方的 hook 目录与 NeoForge 映射可直接成为 `api-mapping-table` 的数据源，省掉自建映射表。

**负面 / 风险**：绑定表基于**本机快照**，`native-hooks.json` 明确会随 API 版本演进（409 → 更高）；需要版本化与定期复核，不能当成永久事实。`animation_driver` 缺失意味着 TaCZ 美术层现在无法端到端落地。§4 的政策冲突未解决前，不宜把本仓库成果宣传为「Horizon 官方兼容方法」。

## 复核条件

1. ~~用户就 §4 拍板~~ 已完成：C，见 ADR 0006；
2. Horizon `native-hooks.json` 的 `NATIVE_HOOKS_API` 或 0.5 animated models 状态变化；
3. 决定把成果贡献给 Horizon 上游时（届时 cleanroom 合规是前置条件）。
