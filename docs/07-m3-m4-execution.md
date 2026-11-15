# M3 / M4 执行报告 · v0.8

> 依据 `docs/04-roadmap.md` M3 / M4 与 ADR 0009 §7 的未决项。本轮完成：**M3 harness 对接（离线闭环）**、**M4 第二样本泛化验证**、**独立子 agent 并行闭环实证**。
> 政策：代码侧 `full-inspection / port / local-only`，资产技术性转换 `technical-only / local-only`。第三方 jar 与产物只留 `work/`，仓库内只有统计与契约。工程政策判断，非法律意见。

## 1. 总览

| 指标 | v0.7 | v0.8 |
|---|---|---|
| skill 数 | 22 | **23**（新增 `verify-generalization`；`diff-test-harness` → implemented） |
| 分类规则 | 20 | **21**（R021） |
| M3 状态 | 规划 | **离线闭环完成**；真机录制留 M3b |
| M4 状态 | 未启动 | **4 样本 / verdict = generalizes** |
| 子 agent 闭环 | 主 agent 代写 result | **3 个独立子 agent 真跑真写，7/7 COMPLETE** |
| `validate.py` | 67 | **90 项全绿** |

## 2. M3：官方 harness 只覆盖一半，所以分两层

本轮真读 `horizon-port-pack` 源码，修正了 v0.7 的一半理解：官方 `tools/mod_port_harness.py` 的 10 个 check 全是 **data/资产层 carry 对比**（`blocks / properties / sounds / shapes / drops / placement / tags / recipes / items / item_stats`，`mod_port_harness.py:35`），比对 `facts.json` 与 26.3 `mod_port_probe` 输出，**没有 Java 逻辑行为录制**。

| 层 | 交付 | 证据 |
|---|---|---|
| **A 桥接** | `mappings/harness-contract.json`（官方字段/路径/生命周期/枚举全表）、`tools/diff_assertions.py` 产出官方形状 `result.json` | `report.rs:283-306`、`report.rs:17` Status、`check.rs:18` Verdict、`pipeline.rs:318` |
| **B 自建** | `schemas/recording-contract.schema.json`、`tools/build_recording_contract.py`、3 份 fixture | 官方链无等价物 |

关键事实：`report.rs:292` 动态遍历 `checks` 键，故可加入 `logic_replay` / `shared_states` / `asset_integrity` 三个自定义 check 并照常被累加判 gap。`carry()` 每次删除旧 `harness/result.json`（`carry.rs:1000`），harness 必须在 carry 之后重跑。

**离线实测**：

- 真实 TaCZ 分诊结果生成 **23 个录制契约（C1 21 / C2 2）/ 11 个 capability id / 157 个 shared_state 全集**，全部 `oracle.status = pending`、输入与状态序列为空（不编造观测）。
- PASS fixture：**68 项全绿**，`result.json` 顶层 `mod / passed / checks`、check 内含 `passed / failed / examples`。
- FAIL fixture：退出码 2（预期），**抓到 3 类失配** —— `rc-001[2] state static_idle vs reload_tactical`（逻辑已换弹、动画还在装填）、`rc-003` 引用未声明 capability、观测状态 `not_a_real_state` 越出 `shared_states` 全集。

**不宣称已完成的事**：真机端到端录制需要 `tools/neoforge_oracle.py export`（1.20.1 NeoForge 实例）+ `cargo build -p horizon-client-lib --example mod_port_probe` + 26.3 客户端资源 + Java 侧行为录制，本轮未跑，留 M3b。

## 3. M4：四个样本，先写死阈值再跑

只消费字节码轨（纯标准库 class 常量池），不反编译、不需要源码。全部 Forge 1.20.1，只检验「换 mod」。阈值 `c6_ratio <= 0.05 && fallback_ratio <= 0.05` 实验前写死。

| 样本 | class | assets | 许可证 | C6 (full) | 兜底 | C6 (metadata) |
|---|---:|---:|---|---:|---:|---:|
| TaCZ（基线） | 1061 | 4436 | GPL3 / CC BY-NC-ND 4.0 | 0 | 0 | 0 |
| Farmer's Delight | 289 | 992 | MIT | 0 | 0 | 0 |
| Create | 2687 | 5071 | MIT | 0 | 0 | 0 |
| Iron's Spellbooks | 1264 | 1832 | All Rights Reserved | 0 | 0 | 0 |

`verdict = generalizes`，规则命中分布也合理（R017 平台前缀兜底、R004 事件订阅、R012 注册在各样本均为主力，无单一规则垄断）。

### 过程中修掉的三个问题（比结论更重要）

1. **门禁缺陷**：单一许可证串只判一个 scope。`MIT` 的 assets 落 `oracle-only`；`All Rights Reserved` 的 code 最保守而 assets 却 `full-inspection`。修为 `single_license_broadcast`（单段单命中广播到其余 scope + 强制 `review_required`），**TaCZ 多段串不触发、判定零变化**。
2. **解析缺陷**：泛型签名 `Ljava/util/Set<Ljava/lang/String;>;` 被整体当类引用，产生 `java.util.Set<Ljava.lang.` 假包前缀（TaCZ 1390 / Create 4829 / Iron's 1654 / Farmer's 356 个）。加 `re.fullmatch` 校验后四样本归零。降级本身确实生效（methods 6172→0、strings 3299→0），不是没降级。
3. **新规则 R021**：Create 的 `CreateMixinPlugin`（`IMixinConfigPlugin` + ASM，无 `@Mixin`、无 MC 前缀）掉进兜底 → 归 `C5 / mixin_infrastructure`，补 golden 用例，复跑全归零。

### 与 v0.4 的数字区分

v0.4 的 `metadata-only` C6 = 0.0013 测的是**源码轨**；本轮四样本 `metadata-only` C6 = 0 测的是**字节码轨**（签名级仍保留 `import_prefixes` / `declared_kind`）。两者都对，合规成本是轨相关的，不可混用。

## 4. 子 agent 并行闭环（补齐 ADR 0009 §7）

`orchestration/task-templates/m3-m4.json`：7 任务 / 2 wave。wave 1 的 6 个任务由 **3 个独立子 agent 各领 2 个**，真实执行命令并各自写 result；主 agent 只做 wave-2 汇总。任务包新增可选 `command` 字段随包下发，`output_path` 改为跟随 `--out-dir`（原先硬编码 `work/dispatch/`，会污染 M2 结果目录）。

`collect-results`：**7/7 COMPLETE / 0 缺失 / 0 越界**，6 个 result 的 `input_hash` 全部与任务包匹配、evidence 非空、无发布/商用/创造性改编字段。

**主 agent 语义复核**：抽查 5 项上报数值全部与真实产物一致；发现 1 处字段类型歧义 —— `failures` 子 agent 写计数 `0`、报告里是数组 `[]`，语义等价但类型不一致，改为 `failure_count` + `failures_list` 并留痕。结论：`collect-results` 能查 `input_hash` 与越界，查不了语义漂移，主 agent 裁决不可省。

## 5. 未决风险

1. **M3b 真机录制**未跑通，需要可运行的 Java 1.20.1 NeoForge 与 Horizon 26.3 实例。
2. **跨版本 / 混淆样本未验证**：四样本同为 1.20.1 且带调试信息，混淆 jar 会让符号规则大面积失配。
3. `animation_driver` 仍 unbound；`foreign.rs` 静默降级、`ModelPart` 姿态预算未实测。
4. 复杂度模型九信号权重仍是 v0.1 初值。
5. ARR 样本触发 `review_required`，其 full-inspection 结果仅用于本地统计比较，不作发布依据。

## 6. 下一步

1. **M3b**：搭最小可运行 Java oracle，把 `oracle.status` 从 `pending` 推到 `recorded → replayed → verified`。
2. **M4b**：换跨 MC 版本或混淆样本，检验规则是否仍泛化；必要时新增 version profile。
3. 用实际耗时校准复杂度模型九个信号的权重（ADR 0007 复核条件）。
