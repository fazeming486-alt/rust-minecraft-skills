---
id: study-horizon-asset-schema
version: 0.1.0
stage: 06-target-study
execution: deterministic
status: implemented
reads: ["third_party/horizon/crates/horizon-assets/**/*.rs", "orchestration/horizon-probes/asset-schema.json"]
writes: ["reports/horizon-asset-schema.json"]
depends_on: []
acceptance: ["判定 AnimationClip 为贴图精灵帧动画而非骨骼动画并附声明行号", "Custom 布尔限制与 foreign.rs 静默降级有行号证据", "Bedrock geometry / glTF / .bbmodel 读取器缺席由 tree_scan 0 命中证明", "报告不含源码正文"]
---

# study-horizon-asset-schema

## 目的

确定 **Horizon 26.3 到底接受哪些资产/模型/动画数据**，以及「语义不变的技术性转换」能走多远。这是 M2 格式等价转换的目标侧规格来源。

```bash
python skills/06-target-study/study-horizon-asset-schema/run.py \
  --horizon-root D:/RUST重写mc项目/third_party/horizon \
  --out reports/horizon-asset-schema.json
```

## 实测结论（v0.7）

1. **动画 ≠ 骨骼动画**。`crates/horizon-assets/src/animation.rs` 的 `AnimationMetadata` / `AnimationClip` / `AnimationSample` 是 `.png.mcmeta` **贴图精灵帧选择**：`frame_time`、`interpolate`、`ClipMode::{DayTime,ScreenTime,Weather,Expression}`、`sample(tick)` / `sample_fraction()`。没有骨骼、蒙皮或关节轨道。别被文件名骗了。
2. **离散状态可以表达，但有严格限制**。`item_model.rs` 的 `ItemModelNode` 有 `Condition` / `Select` / `RangeDispatch` 等变体：
   - `ConditionProperty::Custom` **仅布尔**（`item_model.rs:660`），由 `item_model_property` hook 注入；
   - 枚举态要用 `minecraft:select`（`SelectProperty`，`item_model.rs:707`）；
   - 数值态走 `range_dispatch`（`NumericProperty`，`item_model.rs:409`）。
   因此「idle / shoot / reload / aim」这类状态机可以用条件树表达，但不能直接塞一个字符串枚举。
3. **最大的暗坑**：`item_model/foreign.rs:12-79` 会把第三方自定义 `property` / item model `type` **静默降级**——`condition → on_false`、`select → fallback`、`range_dispatch → 按 0 求值`、`special → base`，mod 自身逻辑根本不执行。跨层切片必须把这条记为缺口，否则会以为自定义属性开箱可用。
4. **格式缺席由源码证明**：`tree_scan` 精确正则对 `BedrockGeometry|bedrock geometry`、`gltf|GLTFLoader`、`.bbmodel|BlockbenchModel`、`bone_hierarchy|joint_matrices|skin_weights` 全部 **0 命中**。Horizon 只吃 Java JSON cuboid model 与 OBJ/MTL。`.hmod` 只收 `assets/` 与 `data/`，路径段需匹配 `[a-z0-9_.-]`，item model 注册在 `assets/<ns>/items/*.json`。
5. 因此 TaCZ 的 `geo_models/*.json`（bones / parent / pivot / rotation）**无法无损表达**为 Java cuboid model，只能按部件近似并显式标有损；`*.animation.json` 的骨骼轨道没有落点；PNG/OGG/lang 可以原样或技术性重编码搬运。

## 与跨层切片的关系

本探针的结论写进了 `orchestration/slice-anchors.json`：
- `fire_mode` / `static_pose` 两个切片判 `portable`（离散状态 + 静态模型，走条件树与 `standalone_models`）；
- 其余 8 个含 `skeletal_animation` 的切片判 `needs_workaround`，并挂上 `workaround_catalog`。

## 验收

- `missing_files` 为空；`tree_scan` 的四个缺席关键词保持 0 命中。
- 若 `item_model.rs` 的 `Custom` 变成非布尔、或 `foreign.rs` 降级规则变化，必须重跑切片并更新 verdict。
