# ADR 0010 · M3 harness 对接分层与 M4 第二样本泛化

- **状态**：Accepted（v0.8，2026-11-15）
- **触发**：按 `docs/04-roadmap.md` 继续执行 M3 / M4，并补齐 ADR 0009 §7 留下的「独立子 agent 并行收益未实证」
- **关联**：ADR 0001（能力契约隔离）、0004（实证校准）、0007（子 agent 分工）、0008（三维度政策）、0009（跨层切片）
- **不影响**：上游规则的分类语义、三层隔离结构、skill 集群协议

## 1. 决策 1：M3 不是「接上官方 harness」，而是分两层

v0.7 的源码研读结论是「dev-only Java oracle 与 coverage 已实现，M3 应对接而非重造」。本轮**真读 `horizon-port-pack` 源码后必须修正这个理解的一半**：

官方 `tools/mod_port_harness.py` 的 10 个 check 全是 **data/资产层 carry 对比** —— `blocks / properties / sounds / shapes / drops / placement / tags / recipes / items / item_stats`（`mod_port_harness.py:35`）。它比对的是「NeoForge 1.20.1 导出的 facts.json」与「Horizon 26.3 的 `mod_port_probe` 输出」，**没有任何 Java 逻辑行为录制、没有输入序列、没有状态机重放**。

因此 M3 拆成两层，缺一不可：

| 层 | 内容 | 状态 |
|---|---|---|
| **A 桥接** | 把我们的检查结论写成官方 `harness/result.json` 形状，让 `report.rs:283-306` 能消费并进 coverage | v0.8 完成 |
| **B 自建** | C1/C2 逻辑单元的平台无关录制契约 + 逐 tick 差分断言 | v0.8 完成离线闭环 |

**关键依据**：`report.rs:292` 是动态遍历 `h["checks"]` 的键，不局限于官方 10 个常量，所以可以加入 `logic_replay` / `shared_states` / `asset_integrity` 三个自定义 check 并照常被累加、判 gap。`coverage.json` 是 `Vec<Row>` 而非带外层键的对象（`pipeline.rs:318`），`Status` 是 kebab-case 四值（`report.rs:17`）。

**必须记住的生命周期坑**：`carry()` 每次会删除旧的 `harness/result.json`（`carry.rs:1000`；`mod_port_harness.py:232-233`），harness 必须在 carry **之后**重跑。

**明确不宣称的事**：离线 fixture 只验证断言器本身正确，不等于真机 Java oracle 录制。真机端到端需要 `tools/neoforge_oracle.py export`（1.20.1 NeoForge 实例）+ `cargo build -p horizon-client-lib --example mod_port_probe` + 26.3 客户端资源 + Java 侧行为录制，留待 M3b。

## 2. 决策 2：录制契约保持平台无关，结论单独桥接

`schemas/recording-contract.schema.json` 只引用 `capabilities/vocabulary.json` 的 capability id，**不出现 Java FQN、Rust 类型或 Horizon API**（ADR 0001 继续成立）。把目标侧字段全部外置到 `mappings/harness-contract.json`，桥接逻辑在 `tools/diff_assertions.py`。

这样 Horizon 快照升级时只改映射表，录制契约与断言器一行不动——与 v0.3「上游不引用 Horizon API」是同一个隔离决策。

**契约不编造观测**：`build_recording_contract.py` 生成的 23 个契约（C1 21 / C2 2）里 `oracle.status` 一律 `pending`，`input_sequence` / `state_sequence` 为空。真实序列必须由 dev-only Java oracle 产生，脚本或模型都不许填。

**断言器必须能抓错**：提供 PASS / FAIL 两组离线 fixture。PASS 68 项全绿；FAIL 故意注入三类失配并全部抓到 —— `rc-001[2]` 状态不同步（典型「逻辑已换弹、动画还在装填」）、`rc-003` 引用未声明 capability、观测状态越出 `shared_states` 全集。只跑永远全绿的样例不构成验证。

## 3. 决策 3：M4 用字节码轨 + 先写死阈值

验证「C6 = 0 是否过拟合」只需签名级事实，因此 **M4 只消费字节码轨**（纯标准库 class 常量池），不反编译、不需要源码、不需要网络。四个样本同为 Forge 1.20.1，只检验「换 mod」，不检验跨版本。阈值 `c6_ratio <= 0.05 && fallback_ratio <= 0.05` 在实验前写进脚本，不事后调参。

| 样本 | class | 许可证 | C6 (full) | 兜底 |
|---|---:|---|---:|---:|
| TaCZ（基线） | 1061 | GPL3 / CC BY-NC-ND 4.0 | 0 | 0 |
| Farmer's Delight | 289 | MIT | 0 | 0 |
| Create | 2687 | MIT | 0 | 0 |
| Iron's Spellbooks | 1264 | All Rights Reserved | 0 | 0 |

**verdict = generalizes**。但结论的可信度来自过程中修掉的三个真实问题，而不是这个 0。

## 4. M4 抓出并修掉的三个问题

1. **合规门禁缺陷（机制级）**：单一许可证串只判一个 scope。`MIT` 的 assets 侧因无匹配规则落到 `default_deny` 变 `oracle-only`；`All Rights Reserved` 更错乱 —— code 侧最保守、assets 却 `full-inspection`。这类样本根本没法解析。
   修复：`single_license_broadcast` —— 单段且只命中一条规则时把判定广播到其余 scope，广播一律 `review_required`；完全无匹配仍 `default_deny`。**明确分段的多段串（TaCZ）不触发广播，基线判定零变化**（已由回归检查锁死）。
2. **常量池解析缺陷（数据级）**：泛型签名 `Ljava/util/Set<Ljava/lang/String;>;` 被整体当成类引用，生成 `java.util.Set<Ljava.lang.` 这类假包前缀（TaCZ 1390 个、Create 4829 个、Iron's 1654 个、Farmer's 356 个）。虽然恰好仍以合法前缀开头、没改变分类结果，但污染事实清单与证据。修复：只对 `re.fullmatch(r"L[\w/$]+;", value)` 的整体描述符收集类引用，泛型实参仍由内部正则单独提取。四样本伪引用归零。
3. **新盲区（规则级）**：Create 的 `CreateMixinPlugin` 实现 `IMixinConfigPlugin`、引用 ASM，但无 `@Mixin`、无 MC 前缀，掉进兜底。新增 **R021** 归 `C5 / mixin_infrastructure`，补 golden 夹具用例，复跑后四样本 C6 与兜底全归零。规则 20 → 21 条。

## 5. 一个必须区分的既有结论

v0.4 记录 `metadata-only` 下 C6 = 0.0013，本轮四个样本在 `metadata-only` 下 C6 均为 0。**两者都对，因为合规成本是轨相关的**：v0.4 测源码轨（降级后丢 import 证据），本轮测字节码轨（`import_prefixes` / `declared_kind` 在签名级仍保留）。已实测降级确实生效（TaCZ methods 6172→0、strings 3299→0），不是脚本没降级。不可把两个数字混用或直接比较。

## 6. 决策 4：子 agent 闭环必须实证，主 agent 不代写 result

ADR 0009 §7 留的未决项本轮补齐：新建 `orchestration/task-templates/m3-m4.json`（7 任务 / 2 wave），**3 个独立子 agent 各领 2 个 wave-1 任务，真实执行命令并各自写 result**，主 agent 只做 wave-2 汇总裁决。`collect-results` 结果 **7/7 COMPLETE、0 缺失、0 越界**。

任务包新增可选 `command` 字段并随包下发（schema + `plan_dispatch.py` 同步），保证子 agent 自包含；`output_path` 从硬编码 `work/dispatch/` 改为跟随 `--out-dir`，避免 M3/M4 污染 M2 结果目录。

**主 agent 语义复核不可省**：抽查 5 项子 agent 上报数值全部与真实产物一致，但发现 1 处字段类型歧义 —— `failures` 子 agent 写成计数 `0`、报告里是空数组 `[]`，语义等价但类型不一致，已改为 `failure_count` + `failures_list` 并在 result 的 `summary` 里留痕。`collect-results` 能查 `input_hash` 与越界字段，查不了这种语义漂移。

## 7. 后果

- skill 22 → **23 个**（新增 `verify-generalization`；`diff-test-harness` 由 `specified` → `implemented`）。
- 规则 20 → **21 条**；`profiles/forge/{_template,1.20.1}.json` 新增 `MIXIN_PLUGIN` 前缀组。
- 新增：`mappings/harness-contract.json`、`schemas/recording-contract.schema.json`、`orchestration/{m4-samples.json,recording-capability-map.json,task-templates/m3-m4.json}`、`tools/{m4_generalize.py,build_recording_contract.py,diff_assertions.py}`、3 份 fixture、6 份报告。
- `policy-gate` 升到 0.3.0（输出新增 `single_license_broadcast`），TaCZ 的历史判定不受影响。

## 8. 未决

1. **M3b**：真机 Java oracle 录制与 Rust 重放尚未跑通，需要可运行的 1.20.1 NeoForge 与 Horizon 26.3 实例。本轮只完成离线闭环。
2. **跨版本泛化未验证**：四个样本同为 Forge 1.20.1。换 MC 版本需要新 profile，规则是否还成立未知。
3. **混淆样本未验证**：四个样本都带调试信息。混淆 jar 会让符号规则大面积失配，是下一个真实风险点。
4. `animation_driver` 仍 unbound；`foreign.rs` 静默降级、`ModelPart` 姿态预算未实测（ADR 0009 §7 继承）。
5. 复杂度模型九信号权重仍是 v0.1 初值。
