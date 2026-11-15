---
id: plan-dispatch
version: 0.1.0
stage: 98-orchestrate
execution: deterministic
status: implemented
reads: []
writes: []
depends_on: ["estimate-complexity"]
acceptance: ["每个任务包自包含且带 policy_mode 与 forbidden_actions", "任务按 depends_on 拓扑分批", "并行任务按 band 的 workers 数分配"]
---

# plan-dispatch

## 目的

把里程碑任务模板切成**自包含的子 agent 任务包**，让「大量子 agent 分工」变成开箱即用的一步，而不是每次靠主 agent 临时口述。

## 分工由主 agent 规划，不由子 agent 自定

角色（`orchestration/roles.json`）与任务模板（`orchestration/task-templates/*.json`）由主 agent 维护；子 agent 只收到自己的任务包，看不到全局规划，也不能互相通信。这样集群扩展时新增一个角色不需要改动任何已有 skill。

## 任务包里必须有什么

`task_id` / `role` / `goal` / `inputs` / **`policy_mode` + `allowed_actions` + `forbidden_actions`** / `output_contract` / `output_path` / `acceptance` / `depends_on` / `complexity{band,score}` / `input_hash` / `invariants` / `assigned_worker`。

**三维合规传导是硬约束**（ADR 0008）：任务包携带 `policy_mode` / `transformation` / `distribution` / `distribution_conditions`。M2 资产任务为 `full-inspection` + `technical-only` + `local-only`，`forbidden_actions` 明确禁止 `creative_adaptation`（重绘/改造型）、`publish_adapted_material`、`commercial_use`，以及与其他子 agent 通信、自评复杂度。越界由 `collect-results` 拦截。

## 拓扑分批

按 `depends_on` 分 wave：同一 wave 内可并行，wave 之间必须等上一批完成。`assigned_worker` 按 band 的 `workers` 数轮询分配；`can_parallel: false` 的角色（合规监督、契约对齐、汇总验收）固定交给 `main-agent`。

## 边界

- 不执行子 agent，只生成任务包与 `index.json`。
- 不做语义判断、不调整任务目标。
- 不改变复杂度分数（那是 `estimate-complexity` 的产物）。

## 运行

```bash
python skills/98-orchestrate/plan-dispatch/run.py \
  --complexity reports/m2-complexity.json \
  --roles orchestration/roles.json \
  --template orchestration/task-templates/m2.json \
  --policy-profiles policy/license-profiles.json \
  --out-dir work/dispatch
```
