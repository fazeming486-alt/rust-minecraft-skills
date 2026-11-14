# 02 · Skill 集群协议（v0.1 冻结）

集群的可扩展性不取决于 skill 数量，而取决于**它们之间是否允许随意耦合**。本文件规定所有 skill 必须遵守的统一契约。

## 1. 双形态

每个 skill 是一个目录，同时具备两层：

```
skills/<stage>/<skill-id>/
├── SKILL.md    意图层：给 AI agent 读的边界、判定原则、验收标准
├── run.py      执行层：确定性 CLI，--manifest/--index --out，仅标准库优先
└── tests/      黄金用例（输入 fixture + 期望 delta）
```

| 层 | 消费者 | 要求 |
|---|---|---|
| `SKILL.md` | AI agent | frontmatter 必须与 `registry.json` 一致；写清「不做什么」 |
| `run.py` | CI / orchestrator | 不依赖模型即可产出确定性结果；相同输入逐字节相同输出 |
| `tests/` | `validate.py` | 至少一组 golden，漂移即失败 |

`SKILL.md` 不是 `run.py` 的说明书，反过来也不是。前者处理**语义边界**，后者处理**可复现执行**；两者都不可省略。若某 skill 确实需要模型裁决，也必须由 `run.py` 先产出候选集与证据，再由模型在受控范围内裁决（见 §4）。

## 2. Frontmatter 规范

```yaml
---
id: classify-java-decompiled
version: 0.1.0
stage: 01-classify
execution: deterministic            # deterministic | assisted | human
reads:  ["source", "units[].symbols", "units[].flags"]
writes: ["units[].semantic", "units[].disposition", "units[].evidence"]
depends_on: ["intake-jar"]
acceptance: ["每一个 unit 都有 disposition", "每条标签都有 evidence"]
---
```

- `reads` / `writes` 用 manifest 字段路径声明，**是集群调度的唯一依据**。
- `depends_on` 只列直接依赖，orchestrator 据此建 DAG。
- `acceptance` 是可执行断言，不是描述性文字。没有断言的 skill 不算完成，只是提示词。
- `validate.py` 会校验 frontmatter 的 `id` / `version` / `stage` / `execution` 与 registry 一致，不一致即失败。

## 3. Manifest / Delta 协议

- **manifest 是唯一共享状态**。skill 不得持有自己的私有账本，不得直接读取或修改别的 skill 的输出文件。
- skill **输出 delta（补丁），不覆写整份 manifest**。delta 含 `unit_patches[]`（`set` / `append`）、`contracts_add[]`、`gaps_add[]`。
- **skill 之间禁止直接调用**。A 需要 B 的结果时，声明 `depends_on` 并从 manifest 读；orchestrator 负责排序。
- orchestrator 按 `reads`/`writes` 做冲突检测：两个 skill 写同一字段路径而彼此无拓扑序，判为冲突并拒绝执行。
- 应用 delta 后重算 `content_hash`；`frozen: true` 的 manifest 只接受带 review 记录的 delta。

## 4. 三级执行

| 级别 | 含义 | 模型参与 | 例子 |
|---|---|---|---|
| `deterministic` | 纯规则/脚本，可 CI 回归 | 无 | `intake-jar`、`classify-java-decompiled` |
| `assisted` | 脚本先产出候选集 + 证据，模型只裁决被标出的单元 | 受控 | `extract-behavior-contract` |
| `human` | 生成 review sheet，机器与模型都无权决定 | 无 | 语义等价确认、C6 关卡 |

## 5. 幂等

幂等键 = `skill_id + skill_version + unit_id + input_hash`。

同一幂等键重复执行必须产出逐字节相同的 delta。skill 不允许读取当前时间、随机数、环境变量或任何未声明的输入写进产物（时间戳只放在 delta 顶层元数据，且 `validate.py` 比对时忽略）。

## 6. 新增一个 skill 的步骤

1. 在 `docs/` 或新 ADR 中写清它解决的**判定问题**，而不是它「能生成什么」。
2. 确定 `reads` / `writes`，检查与现有 skill 的字段冲突。
3. 写 `SKILL.md`（含可执行的 `acceptance`）与 `registry.json` 条目，`status: specified`。
4. 写 `run.py` + 至少一组 golden；`validate.py` 通过。
5. 把 `status` 改为 `implemented`，并冻结版本。
6. 只有在真实样本上校准过命中率之后，才允许提升规则版本。

## 7. 禁止事项

- 禁止把 mod jar、class、贴图、音效提交进仓库（版权边界，见 `.gitignore`）。
- 禁止在 skill 里引用具体 MC 版本、类名 FQN 或 Horizon 具体 API。
- 禁止让模型参与 S1 机械分诊（会破坏可复现性）。
- 禁止把「生成一段代码文本」当作 skill 产物。
- 禁止静默兜底：任何无法判定的单元必须显式标 `C6` 并进入人工关卡。
