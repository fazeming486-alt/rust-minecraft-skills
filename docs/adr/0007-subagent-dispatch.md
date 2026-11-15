# ADR 0007 · 子 agent 分工：确定性复杂度 + 自包含任务包

- **状态**：Accepted（v0.5，2026-11-15）
- **背景**：用户要求把可复现 skill 与待办任务按分工分给大量子 agent、希望 agent 能自己分析任务复杂度、分工由主 agent 规划，并把这做成 skills 集群「开箱即用」的能力。首个应用场景为 M2。
- **相关**：`docs/05-m2-plan.md`、`orchestration/`、`skills/98-orchestrate/`

## 决策 1：复杂度由确定性评估器给出，**禁止模型自评**

用户提的「agent 自己分析任务复杂程度」若实现为「让 LLM 读完任务描述自评难易」，会与本项目地基冲突：不可复现、不可回归、不同模型给出不同拆分，且无法在 CI 里断言。

改为 `tools/estimate_complexity.py` 从**九个真实信号**计算：

`unit_count` / `asset_count` / `format_diversity` / `content_pack_ratio` / `unsupported_format_ratio` / `capability_gap_count` / `policy_strictness` / `c6_ratio` / `cross_layer_contracts`，权重与 S/M/L/XL 分档在 `orchestration/complexity-model.json`。

权重最高的是 `unsupported_format_ratio`(0.20) 与 `capability_gap_count`(0.15)：目标侧不接受的格式与硬缺口才是真正的工作量来源，不是文件总数。`capability_gap_count > 0`、`distribution == local-only`、`unsupported_format_ratio > 0.30` 任一成立即强制 `human_gate`（第二项在 v0.6 按 ADR 0008 由 `policy_mode == oracle-only` 改来）。

人工可覆盖 band，但必须记录理由并写入 `dispatch/index.json`。**模型只做语义裁决，不做资源规划。**

## 决策 2：分工由主 agent 规划，子 agent 不自定

角色（`orchestration/roles.json`）与任务模板（`orchestration/task-templates/*.json`）由主 agent 维护。子 agent 只收到自己的任务包，看不到全局规划。这样新增一个角色或资产族时，不需要改动任何已有 skill——集群扩展成本与现有 agent 数量无关，与 ADR 0003 的「禁止直调、只经 delta」一脉相承。

角色只声明「能做什么、不能做什么、交什么」：`allowed_skills` / `allowed_actions` / `input_globs` / `output_kind` / `can_parallel` / `acceptance`。不规定实现。

## 决策 3：任务包自包含，policy 是硬传导

每个 dispatch pack 必须含 `task_id` / `role` / `goal` / `inputs` / **`policy_mode` + `allowed_actions` + `forbidden_actions`** / `output_contract` / `output_path` / `acceptance` / `depends_on` / `complexity{band,score}` / `input_hash` / `invariants` / `assigned_worker`。

M2 任务包按 ADR 0008 传导三个维度：`policy_mode: full-inspection`、`transformation: technical-only`、`distribution: local-only`，并显式禁止 `creative_adaptation` / `publish_adapted_material` / `commercial_use`、禁止与其他子 agent 通信、禁止自评复杂度。**合规不是主 agent 记在心里，而是随任务包下发到每个执行者。**

`input_hash = sha256(task_id + role + mode + band + template)`：模板、角色、band 或 policy 一变，所有旧 result 立即作废。否则会出现「换了合规档位却沿用旧结论」这种最难查的错误。

## 决策 4：拓扑分批 + worker 轮询 + 人工关卡

按 `depends_on` 分 wave：同 wave 并行，跨 wave 等待。`assigned_worker` 按 band 的 `workers` 数轮询；`can_parallel: false` 的角色（合规监督、契约对齐、汇总验收）固定交 `main-agent`。human_gate 为真时，wave 结果必须经主 agent 签署才进入下一阶段。

## 决策 5：`collect-results` 是唯一汇总入口

子 agent 不互相通信，只把 result 写约定路径。汇总器校验 `task_id` / `input_hash` / `evidence`，并扫描发布/商用/创造性改编越界字段（`published` / `redistributed` / `creative_adaptation` / `commercial_use` / `raw_bytes`），要求 `distribution` 为 `local-only`、`transformation` 不为 `creative`；`oracle-only` 任务另禁内容字段。`verdict` 三态：`COMPLETE` / `PARTIAL`（有缺失）/ `BLOCKED`（有越界，整体中止）。

## 落地与实测（M2）

- 3 个新 skill：`estimate-complexity` / `plan-dispatch` / `collect-results`（stage `98-orchestrate`），共 **17 个 skill**。
- 4 个编排数据文件：`roles.json`（12 角色）、`complexity-model.json`、`task-templates/m2.json`（12 任务）、`dispatch-pack.schema.json`。
- 真实输入实测：**score 0.4255 → band M → 2 workers → human_gate true**，硬门槛 2 条；生成 **12 个任务包 / 4 wave**。（v0.5 时为 0.5255/L/4；ADR 0008 解除过严的合规收紧后 `policy_strictness` 归零，复杂度下降 0.1。这是一次真实校准，不是数字修饰。）
- 实际派出 2 个调研子 agent 并行复核（资产清单 / 动画缺口）。其中一个**纠正了主 agent 对 `roadmap.json:712` 的过度推断**："set aside" 只针对 whole-modpacks 总目标，不能据此判定 0.5 动画搁置；0.5 仍是 `docs/modpacks.md:183` 的 Planned / 未实现。这条纠错已同步修正 ADR 0005、README、roadmap 与能力绑定表。**这是分工复核带来的直接价值。**

## 后果

**正面**

- 「大量子 agent 分工」从口号变成一条命令：`estimate → plan → 派发 → collect`，可复现、可回归。
- 复杂度、并行度、合规档位都是数据，可在 CI 里断言；换 mod / 换里程碑只换模板与输入。
- 独立复核能发现主 agent 的推断偏差，已实证。

**负面 / 代价**

- 多一层编排数据要维护；角色与模板写错会批量产出错任务包，需 `validate.py` 兜底。
- wave 之间严格等待，并行度受最慢任务限制；后续可考虑同 wave 内细粒度重排。
- 复杂度模型权重是 v0.1 初值，需在多个里程碑后校准，不能当成普适常数。

## 复核条件

1. 第二个里程碑（M3/M4）跑完后，用实际耗时校准九个信号的权重；
2. 出现需要子 agent 之间交换中间结果的场景（当前一律禁止，需评估是否放宽为「经主 agent 转发」）；
3. 任务数超过 30 时评估 wave 调度与 worker 复用。
