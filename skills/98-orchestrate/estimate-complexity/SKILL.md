---
id: estimate-complexity
version: 0.1.0
stage: 98-orchestrate
execution: deterministic
status: implemented
reads: []
writes: []
depends_on: ["policy-gate", "classify-java-decompiled"]
acceptance: ["复杂度由真实输入计算而非模型自评", "只读 jar 条目名不读资产内容", "硬门槛触发时强制 human_gate"]
---

# estimate-complexity

## 目的

在派活之前**确定性地**算出任务复杂度，决定拆分粒度、并行度与是否设人工关卡。

**关键决策（ADR 0007）**：不让子 agent 自己说「这个任务简单还是难」。模型自评不可复现、不可回归，会直接破坏「确定性归机器」的地基。复杂度由 `tools/estimate_complexity.py` 从九个真实信号计算，人工可以覆盖但必须记录理由。

## 九个信号

`unit_count` / `asset_count` / `format_diversity` / `content_pack_ratio` / `unsupported_format_ratio` / `capability_gap_count` / `policy_strictness` / `c6_ratio` / `cross_layer_contracts`，权重与分档在 `orchestration/complexity-model.json`。

`unsupported_format_ratio` 权重最高（0.20）：目标侧不接受的资产格式越多，转换工作量越大。`capability_gap_count` 次之（0.15）：硬缺口意味着必须设计 workaround。

## 硬门槛

`capability_gap_count > 0`、`policy_mode == oracle-only`、`unsupported_format_ratio > 0.30` 任一成立即强制 `human_gate`，不受 band 覆盖。

## 边界

- 只读 jar 的**条目名**，因此可在 `oracle-only` 下运行；绝不读取资产内容。
- 不生成任务包（属于 `plan-dispatch`），不调度子 agent。
- 不根据模型对任务描述的主观感受调整分数。

## 运行

```bash
python skills/98-orchestrate/estimate-complexity/run.py \
  --jar work/tacz-forge-1.20.1-1.2.0.jar \
  --index work/index.source.json \
  --policy-decision work/policy-decision.json \
  --bindings target/horizon.capabilities.json \
  --delta work/delta.source.json \
  --out reports/m2-complexity.json --label M2
```
