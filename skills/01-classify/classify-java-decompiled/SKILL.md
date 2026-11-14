---
id: classify-java-decompiled
version: 0.1.0
stage: 01-classify
execution: deterministic
status: implemented
reads: ["source", "units[].path", "units[].kind", "units[].symbols", "units[].flags"]
writes: ["units[].carrier", "units[].semantic", "units[].semantic_subtype", "units[].disposition", "units[].evidence", "units[].confidence", "units[].review_state", "units[].requires_drilldown", "units[].behavior_delta", "units[].provenance"]
depends_on: ["intake-jar"]
acceptance: ["每个 unit 都有 disposition", "每条标签至少 1 条 evidence", "confidence 在 [0,1] 且低于阈值的标记待裁决", "C6 单元不得静默产生", "相同 input_hash 重跑逐字节一致"]
---

# classify-java-decompiled

## 目的

对 S0 产出的 `artifact-index.json` 做**五维机械分诊**（A 载体 / B 语义 / C 处置 / D 证据 / E 耦合），输出 delta。这是整条流水线的地基：分类质量决定下游所有 skill 的上限。

## 规范性依据

- `docs/01-java-decompiled-classification.md`（五维定义、判定规则、伪影折叠、Mixin 增量）
- `rules/classification.rules.json`（规则库，只含符号模式）
- `profiles/forge/<version>.json`（符号 → 字面值展开表）
- `schemas/delta.schema.json`（输出格式）

## 输入与输出

```
输入: artifact-index.json + forge profile + classification.rules.json
输出: classification.delta.json (unit_patches[], warnings[])
```

`unit_patch.set` 写入 carrier / semantic / semantic_subtype / disposition / evidence / confidence / review_state / behavior_delta / provenance / target。

## 判定原则

1. 规则按 `priority` 升序执行，**首个命中的给出 semantic + disposition**，所有命中规则都进 `evidence[]`。
2. 符号先按 profile 展开成字面值，再与从**字节码读出的原始值**比对。profile 缺符号直接失败，不静默失配。
3. 反编译伪影（R001）一律折叠为 `artifact`，不计入工作量。
4. Mixin / 事件回调是**行为增量**，标记 `behavior_delta`，由下游契约 skill 成对记录目标与语义。
5. 兜底 R010 必须显式产出 `C6`，**禁止静默猜测**。
6. `mixed_signals ≥ 2` 标记 `requires_drilldown`，交 S2 下钻到方法级。

## 边界：不做什么

- 不读 jar、不做反编译（那是 `intake-jar`）。
- 不调用模型；确定性阶段零模型参与。
- 不做语义等价判断、不生成任何 Rust 代码。
- 不写 `cross_layer_contracts[]` 与 `units[].target.capabilities`（属于下游）。
- 不覆写整份 manifest，只输出 delta。
- 不引用具体 MC 版本或类名 FQN。

## 运行

```bash
python tools/classify.py \
  --index   tests/fixtures/artifact-index.sample.json \
  --profile profiles/forge/_template.json \
  --rules   rules/classification.rules.json \
  --out     out/classification.delta.json
```

自检由 `python tools/validate.py` 完成：会重跑夹具并与 `tests/golden/classification.delta.json` 比对（忽略 `created_at` 与 `delta_id` 中的时间戳部分）。

## 验收

见 frontmatter `acceptance`。任何一条不满足即视为本 skill 版本不可用，必须修复后重新冻结版本。
