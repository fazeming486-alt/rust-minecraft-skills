---
id: build-feature-slices
version: 0.1.0
stage: 02-contract
execution: deterministic
status: implemented
reads: ["work/index.source.json", "work/delta.source.json", "jar:*.animation.json", "orchestration/slice-anchors.json", "target/horizon.capabilities.json", "third_party/horizon/native-hooks.json"]
writes: ["work/feature-slices.json", "reports/m2-feature-slices.json"]
depends_on: ["parse-java-source", "classify-java-decompiled", "policy-gate", "study-horizon-render-pipeline", "study-horizon-asset-schema", "study-horizon-mod-api"]
acceptance: ["每个切片四层齐全且 shared_states 是唯一状态来源", "目标侧 hook/helper 名称全部可解析，未知符号即报错", "状态参数化 roundtrip 闭合且未匹配状态为 0", "verdict 三态判定可复核，硬缺口不得伪装成 portable"]
---

# build-feature-slices

## 解决的问题

按文件分工会把「换弹」拆成两半：资产子 agent 拿 `reload_*.animation.json`，代码子 agent 拿 `ReloadState.java`，**没人负责缝合**。结果就是最典型的移植事故：逻辑已换弹、动画还在装填。

一个 **cross-layer feature slice** 把用户可感知的一个行为特性绑成单一可判定迁移单元，四层缺一不可：

| 层 | 事实来源 | 例（reload） |
|---|---|---|
| `assets` | jar 内 `*.animation.json` / geometry / display / index / sounds | 42 个状态、365 个骨骼名、70 个动画文件 |
| `code` | `work/index.source.json` + `work/delta.source.json` 按类名 token 关联 | 75 个 Java 单元、状态机类、C1–C6 分布 |
| `target` | `native-hooks.json` + 能力绑定表 + 三路源码探针 | `player_tick` / `input_key` / `mouse_button_pre`、gap = `animation_driver` |
| `contract` | 锚点规则 | `shared_states`、服务端权威、同步边界 |

`shared_states` 是**唯一状态来源**：代码侧与目标侧只能引用它，不得各自定义状态机。这是防「逻辑/动画不同步」的结构性约束。

## 确定性，不让模型参与

```bash
python skills/02-contract/build-feature-slices/run.py \
  --jar work/tacz-forge-1.20.1-1.2.0.jar \
  --index work/index.source.json --delta work/delta.source.json \
  --horizon-hooks D:/RUST重写mc项目/third_party/horizon/native-hooks.json \
  --policy-decision work/policy-decision.json \
  --out work/feature-slices.json
```

锚点规则外置在 `orchestration/slice-anchors.json`，换 mod 只改规则不改代码。脚本会：
- 按 `state_prefixes` 分配状态（首个命中优先），**未命中必须计入 `unmatched_states`，不得静默丢弃**；
- 校验所有 `target_hooks` / `target_helpers` 真实存在于 `native-hooks.json`，未知符号直接退出码 2；
- 参数化折叠（`reload_empty_xmag_1..23` → `reload_empty{magazine_level}`），并做 round-trip 闭合校验。

## 实测（TaCZ 1.20.1，v0.7）

73 个动画文件里有 **157 个不同状态、365 个不同骨骼名**——状态机复杂度远高于文件数，这正是按文件分工会失效的实证。

`157 → 110` 个参数化状态（压缩 **29.94%**），10 个切片，`unmatched = 0`，`unknown_hooks/helpers = 0`，`closed = true`：

- **`portable` 2 个**：`fire_mode`、`static_pose`。纯离散状态 + 静态模型，走 `minecraft:condition` / `select` / `range_dispatch` + `standalone_models`，不需要骨骼动画。
- **`needs_workaround` 8 个**：`reload` / `shoot` / `aim` / `bolt` / `inspect` / `equip` / `locomotion` / `melee`。全部挂 `workaround_catalog`，明确两阶段路径与限制。

`verdict` 三态：`portable` / `needs_workaround` / `blocked`。**硬缺口不伪装成已解决**——`animation_driver` 仍 unbound，`workaround` 里写明「无骨骼/蒙皮/关键帧插值，不能宣称已支持动画」。

## 政策

只读取 mod 自己的数据文件与二进制资产（ADR 0008：`full-inspection / technical-only / local-only`）。报告只含状态名、符号名、计数与 `unit_id`，**不含任何变换数值、像素或音频内容**；产物留 `work/`。

## 验收

- `validation.closed == true`、`unmatched_states` 为空、所有 `roundtrip_closed == true`。
- `target_symbols_resolved == true`；Horizon 快照升级后若有 hook 改名，必须失败而不是静默失配。
- 需要骨骼动画的切片一律 `needs_workaround`，且 `workaround.limitations` 非空。
