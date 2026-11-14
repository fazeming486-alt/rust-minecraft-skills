---
id: api-mapping-table
version: 0.1.0
stage: 03-map
execution: human
status: specified
reads: ["units[].target.capabilities", "capability_gaps"]
writes: ["capability_gaps[]"]
depends_on: ["extract-behavior-contract"]
acceptance: ["每个引用的 capability id 存在于 vocabulary", "语义等价项必须人工确认", "未绑定能力全部进入 capability_gaps"]
---

# api-mapping-table

## 目的

维护「能力需求 → Horizon 实现」的映射，并把未绑定的能力变成**可度量的缺口清单**。这是 Horizon 架构不确定性唯一被允许落地的地方。

## 唯一入口

`target/horizon.capabilities.json`。v0.1 中所有条目为 `unbound`，因为 Horizon 的运行时架构尚未明确（`docs/adr/0001`）。架构明确后只填这张表 + 实现下游绑定，上游规则与 schema 不需要改动。

`binding_guide` 三态：

| status | 含义 |
|---|---|
| `unbound` | 尚未确定由目标侧哪种机制提供 |
| `declared` | 已确定机制（组件/系统、trait、host function、脚本 API 等），尚未实现 |
| `implemented` | 已有可用实现且通过 conformance 检查 |

## 为什么是 human 级别

「Java 侧某 API 的语义，等价于目标侧某机制」是一个**决策**，不是可以靠字符串相似度推断的事实。机器与模型都无权替人确认；本 skill 只负责生成 review sheet 与缺口清单，由人签署。

## 产物

- `capability_gaps[]`：某 mod 需要的 capability 与 target 表中已绑定集合的差集；
- 可移植性判定：缺口为空才允许进入下游代码生成；
- 每个映射项的证据与人工确认记录。

## 边界

- 不假定 ECS、插件 ABI 形态或任何 Rust 具体类型。
- 不修改上游 skill、规则库或 manifest schema。
- 不把 `unbound` 伪装成 `declared`。
