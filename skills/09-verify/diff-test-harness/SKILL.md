---
id: diff-test-harness
version: 0.1.0
stage: 09-verify
execution: deterministic
status: specified
reads: ["units[].disposition", "units[].target.capabilities", "cross_layer_contracts[]"]
writes: []
depends_on: ["extract-behavior-contract", "art-asset-classify"]
acceptance: ["C1 单元有录制的输入序列与状态序列", "重放差异逐条可定位到 unit_id", "跨层契约状态枚举不一致即判失败"]
---

# diff-test-harness

## 目的

兑现「成熟」二字：**比对行为，不比对源码**。本 skill 只读 manifest，不写 manifest，是纯验收组件。

## 三类验收

1. **行为差分**：Java 侧录制输入序列（玩家输入、tick、随机种子）与状态序列 → 目标侧重放，逐帧比对。差异必须能定位到 `unit_id` 与 tick。
2. **资产完整性**：清单闭合、常量池跨层引用无悬空、贴图通道与模型材质槽一一对应。
3. **视觉快照**：关键状态（idle/shoot/reload 等）下的渲染快照对比，用于 C4/C5 美术链。

## 随机性

纯逻辑单元只能通过 `random_source` capability 取随机数，且必须可注入种子。否则状态序列不可复现，差分测试失去意义（见 `target/horizon.capabilities.json` 中 `random_source` 的备注）。

## 跨层契约检查

`cross_layer_contracts[]` 中 `kind: state_machine_alignment` 的条目，两侧 `shared_states` 枚举不一致即判失败。这类缺陷不会导致编译错误，是端到端验证的首要目标。

## 边界

- 不修改任何 unit 标签；发现问题只输出报告，由人工或上游 skill 修正。
- 不生成代码、不调用模型。
- 不把「能编译」当作验收通过。
