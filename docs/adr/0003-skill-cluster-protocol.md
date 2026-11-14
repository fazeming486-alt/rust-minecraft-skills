# ADR 0003 · Skill 集群采用「双形态 + 仅经 delta 交互」

- **状态**：Accepted（v0.1，2026-11-15）
- **决策者**：本仓库（用户明确：这是由很多 skill 构成的集群，形态由项目侧决定）
- **相关**：`docs/02-skill-cluster-protocol.md`、`skills/registry.json`、`schemas/delta.schema.json`

## 背景

目标不是写几个提示词，而是长期维护**大量** skill。集群有两种典型失败方式：

1. **只有 `SKILL.md`**：每个 skill 都是一段自然语言策略，模型每次执行结果不同，无法 CI 回归，无法定位是哪次改动破坏了哪个 mod。
2. **skill 之间随意直调**：很快形成隐式调用网，新增一个 skill 要理解全部上游，改一个字段全链路崩，且没有拓扑序、没有冲突检测。

## 决策

**每个 skill 强制双形态，且 skill 之间只能通过 manifest 的 delta 间接交互。**

1. **双形态**：`SKILL.md`（语义边界、验收断言）+ `run.py`（确定性 CLI，标准库优先）+ `tests/`（golden）。两者缺一不可；需要模型时也只能由脚本先产出候选集与证据，再受控裁决。
2. **manifest 是唯一共享状态**。禁止私有账本，禁止 skill A 直接读/写 skill B 的输出文件。
3. **输出 delta，不覆写 manifest**；orchestrator 按 `reads`/`writes` 建 DAG、做写冲突检测、按序应用并重算 `content_hash`。
4. **幂等键** = `skill_id + skill_version + unit_id + input_hash`；禁止把时间、随机数、环境写进产物内容。
5. **`skills/registry.json` 是唯一来源**：id、版本、stage、执行级别、读写声明、依赖、状态。`SKILL.md` frontmatter 由 `validate.py` 校验与其一致。
6. **三级执行**：`deterministic` / `assisted` / `human`，每个 skill 必须声明；模型只参与 `assisted`，且只处理被标出的单元。
7. **验收断言是硬门槛**：`acceptance` 必须是可执行检查，没有断言的 skill 不算完成。

## 为什么不用「一个大 skill」

大 skill 无法并行、无法单独回归、无法度量单个环节的成熟度，也无法让不同 mod 复用其中一段。按「工序 × 层」切成小 skill，才能把 C6 占比、命中率、golden 漂移这些指标落到具体环节上。

## 后果

**正面**

- 新增 skill 的成本与已有数量无关（只需声明读写字段 + 通过冲突检测）。
- 任何一次失败可定位到具体 skill 版本与 `input_hash`。
- 确定性部分可 CI 化，模型参与面被压缩到 `assisted` 级别。

**负面 / 代价**

-  upfront 成本更高：schema、delta 协议、registry、validate 都要先写好（本 v0.1 的主要工作量）。
- skill 粒度需要校准，过细会导致 delta 数量爆炸；由真实样本上的 `unit` 数量决定。
- 强制「不直调」会让某些一次性便利操作变繁琐，这是有意为之的约束。

## 复核条件

1. 首个端到端样本跑通后评估 delta 体积与调度开销；
2. 出现两个 skill 必须共享中间大对象、且经 manifest 传递明显不经济时（可考虑引入带 schema 的 artifact 引用，但仍不得直调）；
3. skill 数量超过 30 个时评估 registry 是否需要分组。
