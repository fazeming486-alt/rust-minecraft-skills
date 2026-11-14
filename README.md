# rustmc-skills

为 **Horizon**（Rust 重写的 Minecraft）提供 Java mod 的成熟可移植方法：一套由大量 AI skills 组成的工具链，把「靠模型临场翻译」变成「可复现、可回归、可批量执行」的流水线。

> **范围声明**
> 本仓库只含方法论、schema、判定规则、映射表、能力词汇表、测试夹具与工具链。
> **不包含**任何 mod 的源代码、jar、class、贴图、模型或音效（版权原因，见 `.gitignore`）。
> **不包含**任何整合包特定内容；与「亡灵战争整合包」及本工作区其他既有资产没有任何关系。
> 首个验证样本是 Java 版 **TaCZ**（枪械 mod），但其包结构以实际反编译结果为准，本仓库不预先写死。

## 核心主张

1. 移植的交付物不是「一段 Rust 代码文本」，而是**带证据、可版本化的 manifest** 加上可复现的规则、转换器、映射表与测试夹具。前者不可回归，后者可以。
2. 第一个 skill 是**分类 skill**，不是移植 skill。分类质量决定整个工程的上限。
3. **确定性的归机器，语义的归模型，决策的归人。**

## 三项基础决策（v0.1 已冻结）

| # | 待决问题 | 决策 | 依据 |
|---|---|---|---|
| 1 | Horizon 架构暂时未知 | 引入平台无关的**能力契约层**：上游 skill 只依赖 capability id，不依赖任何 Horizon API；Horizon 明确后只填 `target/horizon.capabilities.json` | [ADR 0001](docs/adr/0001-target-agnostic-contract.md) |
| 2 | 只做 Forge，版本随时会变 | 规则库只写**符号模式**，版本字面值（注解 FQN、包名前缀、mappings）全部收进可插拔 `profiles/forge/<version>.json`；规则与 schema 中不出现任何 MC 版本号 | [ADR 0002](docs/adr/0002-forge-version-agnostic.md) |
| 3 | skills 是集群，由很多 skill 构成 | 每个 skill = `SKILL.md`（意图层）+ `run.py`（确定性执行层）+ `tests/`（黄金用例）；**skill 之间禁止直接调用**，只通过 manifest 的 delta 交互，由 orchestrator 按读写声明做拓扑排序 | [ADR 0003](docs/adr/0003-skill-cluster-protocol.md) |

## 流水线

```
S0 规范化  →  S1 机械分诊  →  S2 建图切簇  →  S3 语义裁决  →  S4 人工关卡  →  S5 冻结
 (双轨留存)    (规则, 100%)    (调用图+常量池)   (仅低置信项)     (C6/语义等价)    (hash 锁定)
```

所有阶段读写的都是同一份 `manifest`。分类法见 [docs/01](docs/01-java-decompiled-classification.md)，总纲见 [docs/00](docs/00-methodology.md)。

## 快速开始

仅依赖 Python 标准库，无需安装任何包。

```bash
# 集群一致性自检：schema、规则符号、registry DAG、frontmatter、golden 用例
python tools/validate.py

# 对示例 artifact-index 跑确定性分诊
python tools/classify.py \
  --index   tests/fixtures/artifact-index.sample.json \
  --profile profiles/forge/_template.json \
  --rules   rules/classification.rules.json \
  --out     out/classification.delta.json
```

`out/` 已被忽略。产物是 delta（补丁），不是整份 manifest 的覆写，便于 review、回退与并行执行。

## 目录

| 路径 | 内容 |
|---|---|
| `docs/` | 方法论总纲、五维分类法、skill 集群协议 |
| `docs/adr/` | 三项基础决策的架构决策记录 |
| `schemas/` | `manifest` / `delta` / `artifact-index` / `capability` 四份 JSON Schema |
| `rules/` | 版本无关的分类判定规则（符号模式 DSL） |
| `capabilities/vocabulary.json` | 平台无关能力词汇表 v0.1 |
| `profiles/forge/` | Forge 版本档；`_template.json` 是模板，按 MC 版本复制填写 |
| `target/horizon.capabilities.json` | Horizon 绑定表，当前全部 `unbound`，待架构明确后填写 |
| `skills/` | skill 集群；`registry.json` 是 DAG 与读写声明的唯一来源 |
| `tools/` | 确定性分诊器与集群自检器 |
| `tests/` | 夹具与 golden 输出 |

## 边界：明确不做的事

- 不提交任何第三方 mod 的二进制或美术资产。
- 不在规则、schema、skill 中硬编 MC 版本号或类名 FQN。
- 不绑定 Horizon 的具体运行时（ECS / WASM / trait / 脚本层均未假定）。
- 不实现 Fabric 或其他加载器；但五维分类与 manifest schema 不封死，未来加 `loader_profile` 即可扩展。
- 不把「AI 生成的一段代码」当作 skill 的合格产物。

## 状态与下一步

**v0.1 — 地基已立**：分类法、契约层、版本无关机制、集群协议、可执行分诊器与自检器。

下一步（按顺序，不要跳）：
1. 取一个真实 Forge mod 的反编译产物，用 `intake-jar` 生成 `artifact-index.json`，校准规则命中率与 C6 占比。
2. 用 TaCZ 做首个端到端验证，重点检验「逻辑状态机 ↔ 动画状态机」跨层契约。
3. 之后才批量扩充下游 skill（contract / map / art / verify）。
