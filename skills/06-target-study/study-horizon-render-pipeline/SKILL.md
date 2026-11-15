---
id: study-horizon-render-pipeline
version: 0.1.0
stage: 06-target-study
execution: deterministic
status: implemented
reads: ["third_party/horizon/crates/**/*.rs", "orchestration/horizon-probes/render-pipeline.json"]
writes: ["reports/horizon-render-pipeline.json"]
depends_on: []
acceptance: ["三路探针 missing_files 为空", "tree_keywords 命中数如实记录且与文档结论一致", "只记录行号与 <=160 字符短签名，不复制源码正文", "换 Horizon 快照后重跑可对比"]
---

# study-horizon-render-pipeline

## 目的

把「读 Horizon 渲染源码」变成**可回归的取证**，而不是一次性的模型摘要。目标侧能力是跨层切片的 `layers.target` 唯一事实来源；文档会滞后，源码不会。

探针配置 `orchestration/horizon-probes/render-pipeline.json` 只声明「查哪些文件、哪些符号、哪些词不该出现」；扫描逻辑在 `tools/lib_horizon_source.py`。换 Horizon 快照后重跑即可产出可比对的报告。

```bash
python skills/06-target-study/study-horizon-render-pipeline/run.py \
  --horizon-root D:/RUST重写mc项目/third_party/horizon \
  --out reports/horizon-render-pipeline.json
```

## 实测结论（v0.7，本机快照）

**可复用能力比只读文档时判断的更强**：

- `horizon-client-render/src/models.rs:21` 有 `register_standalone` / `standalone()` —— 这是 `standalone_models` hook 的真实落点，可注册静态模型。
- `native_hooks.rs` 里的 `ModelPart` 支持**逐部件姿态**（`x/y/z`、`x_rot/y_rot/z_rot`、`scale`、`children`），配合变换栈 `push/pop/translate/rotate_about/scale`。所以 phase B 不是「只能拿 draw_quad 硬拼」，可以走结构化的逐部件姿态。
- `render_hand` 是唯一可 `cancel` 的手部 hook；**cancel 后引擎不提供替身**，必须自绘整枪。`render_hand_pose` 给的是整手 7 个 `&mut f32`，不是逐骨骼。
- `hand_drawn` / `world_drawn` 暴露 wgpu device / encoder / 纹理 / 顶点，可自绘。

**仍然不存在的**（`tree_scan` 精确正则 0 命中）：`gltf|GLTFLoader`、`BedrockGeometry|bedrock[_ ]geometry`、`bone_hierarchy|joint_matrices|skin_weights`。`skeleton` 一类裸词会命中 `chat.rs` / `commands/` 等 vanilla 骷髅生物代码，**不能据此认定有骨骼动画**——这是把关键词改成精确正则的原因。

`skinning|keyframe_interpolat` 命中 8 个文件，经子 agent 判读只存在于 cosmetics emote 与 vanilla CEM，物品/枪械模型不在其列。

## 与跨层切片的关系

`orchestration/slice-anchors.json` 的 `workaround_catalog.skeletal_animation.phase_b` 直接引用本探针结论：先 `minecraft:condition` / `select` / `range_dispatch` 表达离散状态保证逻辑闭环，再 `render_hand(cancel)` → `render_hand_pose` → `ModelPart` 逐部件姿态逼近时序。**这仍是 workaround，不得写成「已支持动画」**。

## 政策

Horizon 本体是 MIT，源码可自由研读。报告只含路径、行号、短签名，不含源码正文；`reports/` 内文件可入库，第三方 mod 资产产物只留 `work/`。

## 验收

- `missing_files` 为空（快照升级导致的差异必须显式列出，不能静默）。
- `tree_scan.keywords` 命中数与本文档结论一致；若某关键词从 0 变非 0，必须重开能力评估。
- 报告中任何 `signature` 长度 ≤ 160 字符。
