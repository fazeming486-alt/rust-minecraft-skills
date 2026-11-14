# ADR 0001 · 用平台无关的能力契约层隔离 Horizon 的不确定性

- **状态**：Accepted（v0.1，2026-11-15）
- **决策者**：本仓库（用户明确授权由项目侧决定）
- **相关**：`capabilities/vocabulary.json`、`target/horizon.capabilities.json`、`schemas/capability.schema.json`

## 背景

Horizon 是 Rust 重写的 Minecraft，但其运行时架构目前未知：是否 ECS、插件 ABI 是 Rust trait / WASM / 脚本层、注册表与资源系统如何组织，均无定论。而本仓库要产出的是**大量**上游 skill（分类、契约抽取、映射、美术转换、验证）。若这些 skill 直接假定某种 Horizon API，一旦架构明确或日后调整，几十个 skill 会集体返工，且返工点分散、无法回归。

同时，用户要求这套方法是「成熟可移植」的——可移植性不能建立在猜测之上。

## 决策

**引入平台无关的 portable contract 中间层，把移植拆成互不依赖的两段。**

```
Java mod ──[上游 skills]──> portable contract ──[下游绑定]──> Horizon
   (依赖 Forge)              (不依赖任何平台)         (依赖 Horizon)
```

1. 定义 `capabilities/vocabulary.json`：一组**能力 id**（如 `event_hook`、`raycast`、`asset_handle`、`animation_driver`），每个 id 只描述「需要什么能力」及其输入输出契约，不描述「怎么实现」。
2. 上游 skill 的契约产物只能引用 capability id。**禁止出现 Rust 类型、trait、ECS 术语、WASM 或任何 Horizon 具体 API**，也禁止出现 Java 类名 FQN。
3. `target/horizon.capabilities.json` 是唯一的目标侧绑定表，v0.1 中所有条目为 `unbound`，并附 `binding_status` 与 `notes`。
4. 等 Horizon 明确后，只填这张表 + 实现下游绑定 skill。上游分类规则、manifest schema、契约抽取规则**不需要改动**。
5. `conformance-check`（规划中）通过比对「某 mod 需要的 capability 集合」与「target 表中已绑定的集合」，直接输出可移植性缺口清单。

**明确不假定**：ECS 与否、组件/系统模型、插件 ABI 形态、网络同步机制、tick 调度方式。能力词汇表是「Horizon 需要满足什么」，不是「Horizon 是什么」。

## 后果

**正面**

- Horizon 架构变化的影响面被压缩到一张表 + 下游绑定层，可度量、可回归。
- 未知架构从阻塞项变成可度量的「能力缺口清单」，上游工作可以立即开始。
- 同一套上游方法未来可复用于其他目标运行时（换绑定表即可）。

**负面 / 代价**

- 多一层间接，contract 的粒度需要靠真实样本校准；过细会绑死实现，过粗会丢失语义。
- v0.1 无法给出端到端可运行产物，必须等目标侧绑定。
- `target` 表长期 `unbound` 时容易被人误当成已完成，需由 `validate.py` 与 CI 显式报告缺口数量。

## 复核条件

当以下条件任一成立时复审本 ADR，但**不自动推翻**：

1. Horizon 的 ABI / 运行时架构被确定，需要填写绑定表；
2. 出现某个能力无法用 vocabulary 现有 id 表达，需要新增 capability；
3. 首个端到端样本（TaCZ）暴露出 contract 粒度问题。
