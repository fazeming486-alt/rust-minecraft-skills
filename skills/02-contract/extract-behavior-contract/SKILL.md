---
id: extract-behavior-contract
version: 0.1.0
stage: 02-contract
execution: assisted
status: specified
reads: ["units[].semantic", "units[].disposition", "units[].behavior_delta", "units[].graph"]
writes: ["units[].target.capabilities", "cross_layer_contracts[]"]
depends_on: ["classify-java-decompiled"]
acceptance: ["每个 C1/C2 单元有状态机或纯函数契约", "每个 behavior_delta 成对记录 delta_target 与 delta_semantics", "contract 中不得出现 Java 类名 FQN 或 Horizon 具体 API", "逻辑状态机与动画状态机共用同一 shared_states"]
---

# extract-behavior-contract

## 目的

把分类结果收敛成**平台无关的行为契约**，这是三层结构的中间层（`docs/adr/0001`）。契约只描述「需要什么能力」，不描述「怎么实现」。

## 契约允许出现的内容

- 状态机（状态枚举、迁移条件、输入事件、输出副作用）；
- 纯函数签名与输入/输出约束；
- 事件时序与网络同步需求；
- 资源引用（逻辑 ID，不是文件路径）；
- `capability id`（必须存在于 `capabilities/vocabulary.json`）。

## 契约禁止出现的内容

Java 类名 FQN、Forge/MC 具体 API、MC 版本号、Rust 类型与 trait、ECS 术语、WASM/host function 等任何目标侧实现细节。

## 受控的模型参与

本 skill 是 `assisted`：`run.py` 先按规则产出候选契约与证据，模型**只裁决被显式标出的低置信项**，且每条裁决必须写回 `evidence[]` 并引用具体 unit_id。模型不得参与 S1 机械分诊，也不得替人决定语义等价。

## 两处重点

1. **Mixin / 事件回调**：必须成对记录 `(delta_target, delta_semantics)`，并映射到 `event_hook`。当成普通类处理会得到没有宿主的逻辑碎片。
2. **跨层契约**：逻辑状态机（如 idle/shoot/reload）与动画状态机必须共用同一 `shared_states` 枚举，并写入 `cross_layer_contracts[]`。这类不一致不报编译错误，只会产生「逻辑已换弹、动画还在装填」的隐形缺陷。

## 边界

- 不做目标侧绑定（属于 `api-mapping-table`）。
- 不生成 Rust 代码。
- 不覆写 manifest，只输出 delta。
