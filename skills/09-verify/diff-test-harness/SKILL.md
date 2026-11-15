---
id: diff-test-harness
version: 0.2.0
stage: 09-verify
execution: deterministic
status: implemented
reads: ["work/delta.source.json", "work/policy-decision.json", "reports/m2-feature-slices.json", "reports/m2-conversion.json", "tests/fixtures/recording-contract.sample.json", "mappings/harness-contract.json"]
writes: ["work/m3/recording-contracts.json", "work/m3/harness-*/result.json", "reports/m3-diff-*.json"]
depends_on: ["build-feature-slices", "technical-convert-assets", "extract-behavior-contract", "art-asset-classify"]
acceptance: ["C1/C2 单元有平台无关录制契约且只引用 capability id", "重放差异逐条可定位到 contract_id 与 tick", "跨层 shared_states 不一致即判失败", "产出的 result.json 符合官方形状且可被 report.rs 消费", "离线 fixture 的 PASS/FAIL 两例都能正确判定"]
---

# diff-test-harness

## 目的

兑现「成熟」二字：**比对行为，不比对源码**。本 skill 不改 manifest 标签，只输出报告与可被官方消费的 harness 结果。

## v0.8 关键结论：官方 harness 不覆盖逻辑录制

研读 `horizon-port-pack` 源码后确认，官方 `tools/mod_port_harness.py` 的 10 个 check 全是 **data/资产层 carry 对比**（`blocks / properties / sounds / shapes / drops / placement / tags / recipes / items / item_stats`），**没有 Java 逻辑行为录制**。所以 M3 不是「接上就好」，而是两层：

| 层 | 内容 | 谁来 |
|---|---|---|
| **A 桥接** | 把我们的检查结论写成官方 `harness/result.json` 形状，让 `report.rs` 能消费并进 coverage | 本 skill |
| **B 自建** | C1/C2 逻辑单元的平台无关录制契约 + 逐 tick 差分断言 | 本 skill（官方链无等价物） |

**不得把 A 说成「已接入 Java oracle」。** 字段、路径、生命周期与证据全部记在 `mappings/harness-contract.json`。

## 官方对接契约（源码核实）

`<work>/mods/<key>/harness/result.json`：

```json
{"mod": "…", "passed": true,
 "checks": {"<name>": {"passed": 3, "failed": 0, "examples": []}}}
```

`report.rs:283-306` 动态遍历 `checks` 键（不局限于官方 10 个常量），因此可加入三个自定义 check：`logic_replay` / `shared_states` / `asset_integrity`。`checked == 0` 会被记成 "harness has no checks"，文件缺失记成 "harness not run"。

**易踩的坑**：`carry()` 每次会删除旧的 `harness/result.json`（`carry.rs:1000`；`mod_port_harness.py:232-233`），harness 必须在 carry **之后**重跑。

## 平台无关录制契约

`schemas/recording-contract.schema.json`：只引用 `capabilities/vocabulary.json` 的 capability id，不出现 Java FQN / Rust 类型 / Horizon API（ADR 0001）。输入序列与状态序列按 tick 对齐，`shared_state` 必须来自 `feature-slices` 的 `shared_states` 全集——这是防「逻辑已换弹、动画还在装填」的断言。

```bash
# 从真实分诊结果生成 C1/C2 契约骨架（oracle.status=pending，不编造观测）
python skills/09-verify/diff-test-harness/run.py \
  --delta work/delta.source.json --policy-decision work/policy-decision.json \
  --slices reports/m2-feature-slices.json --conversion reports/m2-conversion.json \
  --contracts work/m3/recording-contracts.json

# 用观测序列跑差分断言并产出官方形状 result.json
python skills/09-verify/diff-test-harness/run.py \
  --slices reports/m2-feature-slices.json --conversion reports/m2-conversion.json \
  --contracts tests/fixtures/recording-contract.sample.json \
  --observations tests/fixtures/oracle-observations.pass.json \
  --result-out work/m3/harness-pass/result.json --report reports/m3-diff-pass.json
```

## 实测（v0.8）

- 真实 TaCZ 样本生成 **23 个契约（C1 21 / C2 2）/ 11 个 capability id / 157 个 shared_state 全集**，全部 `oracle.status = pending`。
- 离线 fixture 正反两例：PASS 用例 **68 项全绿**；故意注入失配的 FAIL 用例抓到 3 类问题——`rc-001[2]` 状态不同步（典型「逻辑已换弹、动画还在装填」）、`rc-003` 引用未声明 capability、观测状态越出 `shared_states` 全集。**断言器必须能抓错，不能只跑永远全绿的样例。**

## 三类验收

1. **行为差分**：`logic_replay` — 输入序列 / 状态序列逐 tick 比对，差异定位到 `contract_id` 与 tick。
2. **跨层契约**：`shared_states` — 状态枚举双向可查、参数化 roundtrip 闭合、观测状态不得越界。
3. **资产完整性**：`asset_integrity` — 5 个转换器 roundtrip 闭合且 `unbound` 被如实标注。

## 随机性

纯逻辑单元只能通过 `random_source` capability 取随机数且必须可注入种子，否则状态序列不可复现，差分失去意义。

## 边界

- **离线 fixture 只验证断言器本身正确**，不代表真机 Java oracle 录制。真机端到端录制需要 `tools/neoforge_oracle.py export`（1.20.1 NeoForge 实例）+ `cargo build -p horizon-client-lib --example mod_port_probe` + 26.3 客户端资源，留待 M3b。
- 不修改 unit 标签；发现问题只输出报告。
- 不生成代码、不调用模型、不把「能编译」当作通过。
