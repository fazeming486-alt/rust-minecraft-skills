---
id: art-asset-classify
version: 0.1.0
stage: 04-art
execution: deterministic
status: specified
reads: ["units[].carrier", "units[].semantic", "units[].disposition", "units[].graph"]
writes: ["units[].semantic_subtype", "cross_layer_contracts[]"]
depends_on: ["classify-java-decompiled"]
acceptance: ["每个 C4 资源有资产类别与完整性清单", "模型/贴图/动画/音效分类互斥且全覆盖", "动画资源与逻辑状态机建立 contract 边"]
---

# art-asset-classify

## 目的

美术层不是「翻译」，是**格式转换 + 视觉等价校验**。本 skill 负责资产分类与清单，为后续转换器提供确定性输入。

## 分类维度（互斥且全覆盖）

| 类别 | 关注点 |
|---|---|
| 几何模型 | 坐标系、单位、骨骼命名、层级、材质槽 |
| 贴图 | 通道（diffuse / normal / emissive）、透明、发光、图集、分辨率 |
| 动画 | 时间轴、骨骼轨道、状态枚举、插值方式、循环/一次性 |
| 音效 | 格式、声道、触发时机、衰减 |
| 粒子 / GUI | 发射器定义、布局与覆盖层 |
| 第一人称视图 | 手臂动画与视角绑定 |

## 必须建立的跨层边

- 动画资源 ↔ 逻辑状态机（`cross_layer_contracts[]`，`kind: state_machine_alignment`）；
- 注册 ID ↔ 资产路径（常量池字符串回填，见 `docs/01` §1）；
- 模型 ↔ 材质槽 ↔ 贴图（资产完整性闭包）。

## 转换原则

- 产物是**转换脚本 + 目标侧资产定义 + 完整性清单**，不是手改的贴图或一次性代码。
- 单位/坐标系/骨骼命名映射要可配置、可回归；不要在脚本里硬编某个 mod 的具体骨骼名。
- 视觉等价由 `diff-test-harness` 的快照对比验收，本 skill 只保证清单闭合。

## 边界

- 不提交任何第三方贴图、模型、音效文件到仓库（版权边界，见 `.gitignore`）。
- 不判断逻辑语义、不生成 Rust 代码。
- 不调用模型；分类由路径与内容特征机械判定。
