---
id: technical-convert-assets
version: 0.1.0
stage: 04-art
execution: deterministic
status: implemented
reads: ["jar:*.animation.json", "jar:**/geo_models/**", "jar:**/display/**", "jar:**/index/**", "jar:**/*.png", "jar:**/*.ogg", "work/policy-decision.json", "orchestration/slice-anchors.json"]
writes: ["work/converted/**", "reports/m2-conversion.json"]
depends_on: ["policy-gate", "build-feature-slices", "study-horizon-asset-schema"]
acceptance: ["政策三维必须为 full-inspection / technical-only / local-only，否则拒绝运行", "产物目录必须在 work/ 下", "每个转换器 roundtrip_closed 为 true，整体 closed 为 true", "目标侧无消费者的转换必须标 unbound，不得声称已转换完成", "仓库内只放脱敏统计报告"]
---

# technical-convert-assets

## 这是 ADR 0008 承诺的首次真实落地

v0.4–v0.5 的 M2 只做路径级清单；v0.6 解除合规边界后，本 skill **真正读取 mod 自己的数据文件与二进制资产，做语义不变的格式等价转换**。每个转换器都必须用 roundtrip 证明「没丢东西、没改写含义」。

```bash
python skills/04-art/technical-convert-assets/run.py \
  --jar work/tacz-forge-1.20.1-1.2.0.jar \
  --policy-decision work/policy-decision.json \
  --out-dir work/converted \
  --report reports/m2-conversion.json
```

两道硬门禁：`scope_decisions.assets` 必须是 `full-inspection / technical-only / local-only` 且 `redistribution == false`；`--out-dir` 必须位于 `work/` 下。任一不满足直接退出，不产出任何东西。

## 五个转换器与诚实的 schema 状态

| id | 做什么 | roundtrip 证明 | 目标侧状态 |
|---|---|---|---|
| `shared_states` | 157 个动画状态 → 110 个参数化 canonical，保留 `canonical → raw` 映射 | 展开后集合与原集合完全相等 | **partial**：`Custom` 仅布尔；第三方 property 会被 `foreign.rs:12-79` 静默降级 |
| `bone_tracks` | 按文件组织的骨骼轨道 → 按状态索引 | 重建回原 73 个 JSON，归一化比较相等 | **unbound**：Horizon 无骨骼/关键帧消费者 |
| `geometry_ir` | Bedrock `minecraft:geometry` 包装剥离为 bone IR | 重建回原 327 个 JSON | **unbound**：Horizon 只吃 Java cuboid / OBJ |
| `namespace_rewrite` | `display` / `index` / `lang` 输出路径重写为 `.hmod` 的 `assets/` 布局，内容不动 | 417 个 JSON 逐键等值 | **bound** |
| `binary_carry` | PNG / OGG 原样搬运，不重编码 | 2793 个文件 sha256 前后相同 | **bound** |

`schema_status` 是三态：`bound`（可直接进 `.hmod`）/`partial`（能表达但有条件）/`unbound`（只是中间表示）。**`unbound` 不等于失败**——roundtrip 依然要闭合，但绝不允许在报告里写成「资产已转换完成」。

## 实测（TaCZ 1.20.1，v0.7）

`5 个转换器 / 3683 源文件 / 3215 输出 / all_roundtrip_closed = true`，产物 210 MB 全部在 `work/converted/`（`.gitignore` 排除）。仓库内只有 `reports/m2-conversion.json` 的计数与状态，没有任何变换数值、像素或音频。

第一轮 `bone_tracks` 的 roundtrip 是 **false**：重建时漏了 `format_version` 等顶层键。修好后才全绿——这正是把可逆性做成硬断言的价值，否则会静默丢信息。

## 直接回答「动画这类怎么搬」

- **能直接搬**：PNG / OGG / lang / display / index（二进制原样或路径重写）。
- **能有条件搬**：状态枚举。参数化压成 110 个 canonical 后，用 `condition`(布尔) / `select`(枚举) / `range_dispatch`(数值) 表达；但必须先注册自定义 property，否则被静默降级。
- **只能做中间表示**：Bedrock geometry 与骨骼关键帧。Horizon 26.3 不消费，`animation_driver` 仍 unbound。这部分由 `build-feature-slices` 的 `workaround_catalog` 接管两阶段近似，不赌 0.5 排期。

## 政策

ADR 0008 三维模型：ND 限制的是分享/商用改编版，本地语义不变的技术性转换可行。产物不发布、不商用、不重绘；「是否属 technical-only」拿不准就 `review_required`。这是工程政策判断，非法律意见。
