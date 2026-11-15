# M2 执行报告 · v0.7

> 依据 `docs/04-roadmap.md` M2 与 `docs/05-m2-plan.md`。本轮把 M2 从「规划 + 路径清单」推进到**真实执行**：目标侧源码研读、跨层特性切片、语义不变的格式等价转换、17 个任务包全闭合。
> 政策：`full-inspection / technical-only / local-only`（ADR 0008）。产物只留 `work/`，不发布、不商用、不重绘。工程政策判断，非法律意见。

## 1. 总览

| 指标 | v0.6 状态 | v0.7 结果 |
|---|---|---|
| M2 任务包 | 12（2 完成 / 10 待派发） | **17（17 完成 / 0 缺失 / 0 越界，verdict = COMPLETE）** |
| 派发 wave | 4 | **4**（首波改为三路目标侧源码研读） |
| 复杂度 | 0.4255 / M / 2 workers / human_gate | 不变（输入未变） |
| 目标侧事实来源 | `docs/` + `native-hooks.json` | **+ 三路 Rust 源码探针（可回归）** |
| 资产交付 | 路径级清单 | **5 个转换器 / 3683 源文件 / 3215 输出，roundtrip 全闭合** |
| 跨层特性 | 概念（`shared_states` 在 schema 里） | **10 个四层切片，157→110 状态，2 portable / 8 needs_workaround** |
| skill 数 | 17 | **22** |
| `validate.py` | 49 项 | **67 项全绿** |

## 2. 四波派发与闭合

`estimate-complexity → plan-dispatch → collect-results` 三步原样复用，复杂度仍是确定性的 0.4255 / M / 2 workers，`human_gate` 由「能力缺口 + local-only」触发。

| wave | 任务 | 关键产出 |
|---|---|---|
| 1 | `m2-01` 清单、`m2-11` 合规、**`m2-13/14/15` 三路 Horizon 源码研读** | `reports/horizon-{render-pipeline,asset-schema,mod-api}.json` |
| 2 | 7 个资产族转换、`m2-09` 缺口复核、**`m2-16` 跨层切片** | `work/converted/**`、`reports/m2-feature-slices.json` |
| 3 | `m2-10` 契约对齐、**`m2-17` 转换汇总** | `reports/m2-conversion.json`、契约复核清单 |
| 4 | `m2-12` 验收 | `reports/m2-collection.json`（COMPLETE） |

三路研读**真实派出了三个独立子 agent 并行读 Rust 源码**，结论经探针脚本复现后固化。这是「Horizon 源码分 skill 研读」从想法变成机制的验证。

## 3. 三路目标侧源码研读（新增 `06-target-study`）

`tools/lib_horizon_source.py` + 三份 `orchestration/horizon-probes/*.json`；只记行号与 ≤160 字符短签名，不复制源码正文。

| 探针 | 文件 / 声明 | 缺席证明（精确正则全仓 0 命中） |
|---|---|---|
| `render-pipeline` | 6 文件 / 102 声明 | `gltf\|GLTFLoader`、`BedrockGeometry`、`bone_hierarchy\|joint_matrices\|skin_weights` |
| `asset-schema` | 7 文件 / 59 声明 | `BedrockGeometry`、`.bbmodel\|BlockbenchModel`、`gltf` |
| `mod-api` | 12 文件 / 263 声明 | `animated_model\|BedrockGeometry`、`api_tier\|ApiTier` |

三份 `missing_files` 全空（v0.7 校准了 `build.rs` / `native.rs` / `mod_port_harness.py` 三处真实路径）。`ModelPart` 命中 9 文件、`coverage.json` 命中 3 文件。

**五处推断被源码纠正**（详见 ADR 0009 §3）：`Custom` 仅布尔；`foreign.rs` 静默降级第三方 property；`ModelPart` 逐部件姿态可用但无骨骼插值；`mod_api` 无 tier 字段；dev-only Java oracle / coverage 已有实现，M3 应对接而非重造。

## 4. 跨层特性切片：直接回答「动画怎么搬」

73 个动画文件里实际有 **157 个不同动画状态、365 个不同骨骼名**。按文件分工会漏掉状态机复杂度，也会让资产组与代码组各自宣布完成却没人缝合。

`build-feature-slices` 以锚点为键，把四层绑成单一可判定单元；`shared_states` 是唯一状态来源。参数化把 `reload_empty_xmag_1..23`、`reload_intro/loop/end` 压成 `reload{mode, magazine_level, stage_index}`：**157 → 110（压缩 29.94%）**，映射完整保留且 roundtrip 闭合，不是丢信息。

| 切片 | 状态 | 参数化后 | Java 单元 | verdict |
|---|---:|---:|---:|---|
| `reload` | 42 | 20 | 75 | needs_workaround |
| `shoot` | 12 | 12 | 34 | needs_workaround |
| `aim` | 9 | 7 | 15 | needs_workaround |
| `bolt` | 18 | 14 | 13 | needs_workaround |
| `inspect` | 23 | 9 | 2 | needs_workaround |
| `equip` | 7 | 7 | 5 | needs_workaround |
| **`fire_mode`** | 11 | 11 | 91 | **portable** |
| **`static_pose`** | 13 | 13 | 30 | **portable** |
| `locomotion` | 18 | 15 | 9 | needs_workaround |
| `melee` | 4 | 2 | 12 | needs_workaround |

`unmatched = 0`、`unknown_hooks/helpers = 0`、`closed = true`。两个 `portable` 切片是纯离散状态 + 静态模型，走 `minecraft:condition` / `select` / `range_dispatch` + `standalone_models`，**不需要骨骼动画**；其余 8 个挂 `workaround_catalog.skeletal_animation`：

- **A 逻辑闭环**：条件树表达离散状态 → 静态模型注册。
- **B 补表现**：`render_hand(cancel)` → `render_hand_pose` 取整手 PoseStack → `ModelPart` 逐部件姿态 + `hand_drawn`/`world_drawn` 自绘逼近时序。
- **限制**：无骨骼/蒙皮/关键帧插值；cancel 后引擎不提供替身；`Custom` 仅布尔；第三方 property 会被静默降级；0.5 仅声明未实现。**这是 workaround，不是「已支持动画」。**

## 5. 五个格式等价转换器

| id | 源文件 | roundtrip 证明 | `schema_status` |
|---|---:|---|---|
| `shared_states` | 73 | 展开集合 == 原 157 状态集合 | `partial` |
| `bone_tracks` | 73 | 重建 73 个 JSON 归一化相等 | `unbound` |
| `geometry_ir` | 327 | 重建 327 个 JSON 归一化相等 | `unbound` |
| `namespace_rewrite` | 417 | JSON 键集合守恒 | `bound` |
| `binary_carry` | 2793 | sha256 前后全部相同 | `bound` |

合计 **3683 源文件 → 3215 输出 / 210 MB**，全部在 `work/converted/`；仓库内只有 `reports/m2-conversion.json` 的计数与状态，没有任何变换数值、像素或音频。

第一轮 `bone_tracks` roundtrip 为 false（重建漏了 `format_version` 顶层键），修好后全绿。这个失败本身是方法有效的证据：**没有硬断言就会静默丢信息**。

`schema_status` 三态是刻意设计：`bound` 可直接进 `.hmod`；`partial` 能表达但有前提（先注册自定义 property，否则被 `foreign.rs` 降级）；`unbound` 只是中间表示，Horizon 26.3 没有消费者。**`unbound` 不算失败，但绝不允许写成「资产已转换完成」。**

## 6. 修掉的政策断点

ADR 0008 放宽了资产政策，但 `roles.json` 的资产角色仍只许「列路径、读公开文档」；`plan_dispatch` 取「角色 ∩ 策略白名单」交集，所以**任务包实际上仍禁止转换**。本轮：

- 策略白名单补 `read_horizon_source` / `build_cross_layer_slice`；
- 6 个资产角色与 3 个目标侧角色的 `allowed_actions` 显式下发转换/研读权限；
- `validate.py` 新增 3 条回归检查，验证角色、白名单与**任务包实际字段**三处一致。

实测 `m2-17-conversion` 的任务包现在真的带 `technical_format_conversion`，`m2-13-target-render` 真的带 `read_horizon_source`。

## 7. 未决风险（不粉饰）

1. **`unbound` 的中间表示没有消费者**。`geometry_ir` / `bone_tracks` 目前只能证明「可逆」，不能证明「在 Horizon 跑得起来」。要验证内容级转换，需等 0.5 或换有授权的自有资产样本。
2. **`foreign.rs` 降级是源码判读，尚未实测**。需要构造最小 `.hmod` 跑通加载链才能确认触发条件。
3. **`ModelPart` 姿态的预算上限未测**（每帧部件数 / draw call），phase B 的帧率可行性未知。
4. **`animation_driver` 仍 unbound**，M2 没有消除这个硬缺口，只是把它定位得更精确：不是「完全没有动画能力」，而是「有逐部件静态姿态与变换栈，缺骨骼/蒙皮/关键帧插值与驱动」。
5. **17 个 result 由主 agent 按真实报告归档**，尚未全部由独立子 agent 产出。下一轮应把 wave 2 的资产族真正分给子 agent，验证并行收益与任务包自包含程度。
6. 复杂度模型九信号权重仍是 v0.1 初值，需用实际耗时校准。

## 8. 下一步（M3 / M4）

- **M3 调整为「对接」而非「自建」**：`horizon-port-pack/src/oracle.rs` / `report.rs` / `tools/mod_port_harness.py` 已有 dev-only Java oracle 与 coverage 链。我们的 `diff-test-harness` 只负责产出 harness 可消费的录制契约与差分断言。
- **M4**：换混淆或跨版本的第二个 mod，验证 C6 = 0 不是 TaCZ 过拟合；顺便检验 `slice-anchors.json` 的锚点是否需要扩展（当前 10 个锚点覆盖 157 状态，第二样本可能引入新状态族）。
- **并行化验证**：把 wave 2 的 7 个资产族真正派给子 agent，用 `input_hash` + `collect-results` 验证闭环。
