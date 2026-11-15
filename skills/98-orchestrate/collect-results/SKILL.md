---
id: collect-results
version: 0.1.0
stage: 98-orchestrate
execution: deterministic
status: implemented
reads: []
writes: []
depends_on: ["plan-dispatch"]
acceptance: ["每个 result 校验 task_id 与 input_hash", "结果不得含发布/商用/创造性改编字段且 distribution 为 local-only", "缺失或越界整体判为 BLOCKED 或 PARTIAL"]
---

# collect-results

## 目的

子 agent 之间不通信，只把结果写到约定路径。本 skill 是**唯一汇总入口**，负责契约校验、合规越界检查与全局状态判定。

## 校验项

| 检查 | 失败后果 |
|---|---|
| `task_id` 与任务包一致 | violation |
| `input_hash` 与任务包一致 | violation（任务包已变更，结果作废） |
| `evidence` 非空 | violation |
| 结果不含 `published` / `redistributed` / `creative_adaptation` / `commercial_use` / `raw_bytes`，且 `distribution` 为 `local-only`、`transformation` 不为 `creative`（ADR 0008） | violation，整体中止 |
| result 文件存在 | 缺失计入 `missing`，判 PARTIAL |

`verdict` 三态：`COMPLETE` / `PARTIAL`（有缺失）/ `BLOCKED`（有越界）。规划阶段可用 `--allow-missing` 只生成清单不判失败。

## 为什么 input_hash 必须校验

任务包由 `plan-dispatch` 确定性生成；如果模板、角色、band 或 policy 变了，hash 就会变，子 agent 的旧结果必须作废。否则会出现「换了合规档位却沿用旧结论」这种最难查的错误。

## 边界

- 不替子 agent 补结果、不猜测缺失内容。
- 不修改任何 manifest；只出汇总报告。
- 不在 `violations` 存在时把结论写成「已完成」。

## 运行

```bash
python skills/98-orchestrate/collect-results/run.py \
  --index work/dispatch/index.json \
  --packs-dir work/dispatch --results-dir work/dispatch/results \
  --out reports/m2-collection.json --allow-missing
```
