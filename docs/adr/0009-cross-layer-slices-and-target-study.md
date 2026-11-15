# ADR 0009 · 跨层特性切片、目标侧源码研读与真实格式转换

- **状态**：Accepted（v0.7，2026-11-15）
- **触发**：用户提出「动画这类又有美术资产又有 Java 代码的东西该怎么搬，还得考虑跟 Horizon 对齐，Horizon 的源码也该分 skill 去研读」
- **关联**：ADR 0005（目标绑定）、0006（合规分档）、0007（子 agent 分工）、0008（三维度政策）
- **不影响**：ADR 0001 的三层隔离、0002 的版本无关、0003 的 skill 集群协议

## 1. 问题：按文件分工在动画面前失效

v0.5 的分工矩阵按「工序 × 层」切：资产族给资产角色，Java 单元给代码角色。这对纯数据或纯逻辑没问题，但**换弹**不是一堆文件，它是一个用户可感知的行为特性，横跨四层：

| 层 | 真实内容（TaCZ 1.20.1 实测） |
|---|---|
| 资产 | `reload_*.animation.json`（42 个状态）、骨骼轨道（365 个不同骨骼名）、geometry / display / index / sounds.json |
| 代码 | `ReloadState` / `AnimationStateMachine` / `ObjectAnimationRunner` 等 75 个 Java 单元 |
| 目标侧 | `player_tick` / `input_key` / `mouse_button_pre` / `item_model_property` / `render_hand_pose` |
| 契约 | 服务端权威的弹药状态机 ↔ 客户端分段动画 ↔ 音效触发，共用 `shared_states` |

拆给两拨子 agent 后**没人负责缝合**，典型事故就是「逻辑已换弹、动画还在装填」。而且实测显示复杂度被严重低估：73 个动画文件里藏着 **157 个不同状态、365 个骨骼名**——按文件数估工作量会差一个数量级。

另外，v0.3–v0.6 的目标侧结论全部来自 `docs/` 与 `native-hooks.json`。文档会滞后，源码不会。

## 2. 决策 1：引入 cross-layer feature slice

一个 slice = 一个用户可感知特性，`schemas/feature-slice.schema.json` 强制四层齐全：

```
assets  → animation states / bones / geometry / display / index / sound events
code    → Java unit_id + C1–C6 分布 + 状态机单元
target  → Horizon hooks / helpers / capability gaps / API tier
contract→ shared_states + authority + sync_boundary + presentation
```

- **`shared_states` 是唯一状态来源**。代码侧与目标侧只能引用它，不得各自定义状态机——这是防「逻辑/动画不同步」的结构性约束，不是文档建议。
- 锚点规则外置在 `orchestration/slice-anchors.json`（10 个锚点 + 参数化规则 + workaround 目录），换 mod 只改规则。
- **确定性**：`tools/build_feature_slices.py` 零模型参与。未命中状态必须计入 `unmatched_states`，目标侧 hook/helper 名未在 `native-hooks.json` 出现即退出码 2，状态参数化必须 roundtrip 闭合。
- **verdict 三态**：`portable` / `needs_workaround` / `blocked`。含 `skeletal_animation` 的切片一律 `needs_workaround`，且必须挂具体 workaround；**硬缺口不伪装成已解决**。

实测：157 → 110 个参数化状态（压缩 29.94%），10 个切片，`unmatched = 0`，`closed = true`，2 个 `portable`（`fire_mode` / `static_pose`）、8 个 `needs_workaround`。

**状态参数化本身是个有分量的发现**：`reload_empty_xmag_1..23`、`reload_intro/loop/end` 这类变体不该逐个搬，应压成 `reload{mode, magazine_level, stage_index}`。157 → 110 不是丢信息，映射关系完整保留且可逆。

## 3. 决策 2：Horizon 源码研读 = 三路确定性探针 skill

「读源码」不做成模型一次性摘要，而做成**可回归的取证**：`tools/lib_horizon_source.py` + 三份 `orchestration/horizon-probes/*.json` + 三个 `06-target-study` skill。每份探针声明必查文件、要看的声明、以及**不该出现的关键词**，输出行号与 ≤160 字符短签名，不复制源码正文。

三路分工：渲染管线 / 资产数据结构 / mod API 与加载链。首波并行派发，结果作为切片与转换的目标侧事实来源。

**这一轮真实纠正了五处推断**（分工复核的价值）：

| # | 先前结论 | 源码事实 |
|---|---|---|
| 1 | 可用 `ConditionProperty::Custom` 表达自定义状态 | `item_model.rs:660` 的 `Custom` **仅布尔**；枚举需 `minecraft:select`，数值走 `range_dispatch` |
| 2 | 自定义 property 可直接用 | `item_model/foreign.rs:12-79` 会**静默降级**：condition→on_false、select→fallback、range_dispatch→按 0、special→base，mod 逻辑根本不执行 |
| 3 | 只能拿 `draw_quad` 硬拼姿态 | `horizon-client-render/src/models.rs:21` 有 `register_standalone`；`native_hooks.rs` 的 `ModelPart` 支持逐部件静态姿态 + 变换栈。phase B 比预想强，但仍无骨骼/蒙皮/关键帧插值 |
| 4 | `native-hooks.json` 的 `mod_api` 有 tier 字段 | 434 条 hook 的 `mod_api.tier` **全为 None**；tier 是 `docs/modpacks.md` 的分层，由 `horizon-port-pack/src/classify.rs` 消费 |
| 5 | M3 需要自建 harness | `oracle.rs`(1027 行) / `report.rs`(816 行，含 coverage.json) / `tools/mod_port_harness.py` **已有实现**；M3 应对接而非重造 |

另有一处是 v0.5 已纠正、本轮再次确认的：`roadmap.json:712` 的 *set aside* 只针对 whole-modpacks 总目标，**0.5 动画是 Planned 未实现，不是被搁置**（`docs/modpacks.md:183`；`manifest.rs:20-22` 的 `APIS` 止于 0.3）。

**缺席证明**：精确正则全仓扫描对 `gltf|GLTFLoader`、`BedrockGeometry|bedrock[_ ]geometry`、`.bbmodel|BlockbenchModel`、`bone_hierarchy|joint_matrices|skin_weights` 全部 **0 命中**。裸词 `skeleton` 会命中 `chat.rs` / `commands/` 等 vanilla 骷髅生物代码，因此探针改用精确正则并在报告里记录 caveat——这是取证精度的必要修正。

## 4. 决策 3：真实格式等价转换 + 三态 schema_status

ADR 0008 承诺的「本地语义不变的技术性转换」首次落地。`technical-convert-assets` 有 5 个转换器，每个都必须用 roundtrip 证明可逆：

| 转换器 | roundtrip | `schema_status` |
|---|---|---|
| `shared_states`（状态参数化） | 展开集合 == 原集合 | `partial`（Custom 仅布尔 + foreign 降级） |
| `bone_tracks`（按状态重组骨骼轨道） | 重建 73 个 JSON 归一化相等 | `unbound`（无消费者） |
| `geometry_ir`（剥离 Bedrock 包装） | 重建 327 个 JSON 归一化相等 | `unbound`（无读取器） |
| `namespace_rewrite`（路径重写） | 417 个 JSON 键集合守恒 | `bound` |
| `binary_carry`（PNG/OGG 原样搬运） | 2793 个 sha256 前后相同 | `bound` |

`unbound` **不等于失败**——roundtrip 照样要闭合，但绝不允许写成「资产已转换完成」。实测 3683 源文件 → 3215 输出，210 MB 产物全部只留 `work/converted/`，仓库内只有 `reports/m2-conversion.json` 的计数。

第一轮 `bone_tracks` roundtrip 为 false（重建时漏了 `format_version` 顶层键）。修好后才全绿——这正是把可逆性做成硬断言的价值。

## 5. 决策 4：修掉政策断点并加回归测试

发现一个真实的机制断裂：ADR 0008 把资产政策放宽到 `full-inspection / technical-only / local-only`，但 `orchestration/roles.json` 里资产角色的 `allowed_actions` 仍只有 `list_resource_entries` / `read_public_docs`。`plan_dispatch` 取「角色 ∩ 策略白名单」交集，导致**政策放开了，任务包却仍不允许转换**。

修复：在策略白名单补 `read_horizon_source` / `build_cross_layer_slice`，角色与任务包显式下发 `technical_format_conversion`；`validate.py` 新增三条回归检查（角色权限、白名单、任务包实际权限），防止再次出现「文档说可以、执行层拒绝」。

## 6. 后果

- 集群 17 → **22 个 skill**，新增 stage `06-target-study`；M2 任务 12 → **17 个 / 4 wave**，首波是三路目标侧研读。
- 目标侧能力结论从「读文档」升级为「读源码 + 可回归探针」，快照升级后重跑即可比对。
- `animation_driver` 仍 **unbound**，但描述更精确：不是「完全没有动画能力」，而是「有逐部件静态姿态与变换栈，没有骨骼/蒙皮/关键帧插值与动画驱动」。
- `target/horizon.capabilities.json` 与 `mappings/disposition-to-tier.json` 补上源码证据与 tier 口径说明；**上游规则、schema、分类法一行未改**，ADR 0001 的隔离设计再次被验证。

## 7. 未决

1. `unbound` 的 `geometry_ir` / `bone_tracks` 只是中间表示。等 0.5 落地或换自有资产样本前，不能验证「内容级转换是否真能在 Horizon 跑起来」。
2. `foreign.rs` 的静默降级尚未实测（需要构造一个最小 `.hmod` 并跑通加载链）；目前是源码判读结论。
3. `ModelPart` 逐部件姿态的预算上限（每帧部件数、draw call）未测，phase B 能否达到可接受帧率未知。
4. 复杂度模型九信号权重仍是 v0.1 初值；M3/M4 跑完用实际耗时校准。
5. ~~17 个 result 由主 agent 按真实报告归档，尚未全部由独立子 agent 产出~~ **v0.8 已解除**（ADR 0010 §6）：M3/M4 的 6 个任务由 3 个独立子 agent 真跑真写，7/7 COMPLETE / 0 越界。
