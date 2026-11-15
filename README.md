# rustmc-skills

为 **Horizon**（Rust 重写的 Minecraft）提供 Java mod 的成熟可移植方法：一套由大量 AI skills 组成的工具链，把「靠模型临场翻译」变成「可复现、可回归、可批量执行」的流水线。

> **范围声明**
> 本仓库只含方法论、schema、判定规则、映射表、能力词汇表、测试夹具与工具链。
> **不包含**任何 mod 的源代码、jar、class、贴图、模型或音效（TaCZ 代码 GPL-3.0 / 资产 CC BY-NC-ND 4.0，见 `.gitignore`）。
> **不包含**任何整合包特定内容；与「亡灵战争整合包」及本工作区其他既有资产没有任何关系。
> 首个验证样本是 Java 版 **TaCZ** 1.20.1 Forge 1.2.0；包结构一律由实际反编译结果生成，不预先写死。

## 核心主张

1. 移植的交付物不是「一段 Rust 代码文本」，而是**带证据、可版本化的 manifest** 加上可复现的规则、转换器、映射表与测试夹具。前者不可回归，后者可以。
2. 第一个 skill 是**分类 skill**，不是移植 skill。分类质量决定整个工程的上限。
3. **确定性的归机器，语义的归模型，决策的归人。**
4. **规则必须由真实样本反推**，不能只靠推演；判定以字节码轨为准。

## 三项基础决策（v0.1 已冻结）

| # | 待决问题 | 决策 | 依据 |
|---|---|---|---|
| 1 | Horizon 架构暂时未知 | 引入平台无关的**能力契约层**：上游 skill 只依赖 capability id，不依赖任何 Horizon API；Horizon 明确后只填 `target/horizon.capabilities.json` | [ADR 0001](docs/adr/0001-target-agnostic-contract.md) |
| 2 | 只做 Forge，版本随时会变 | 规则库只写**符号模式**，版本字面值全部收进可插拔 `profiles/forge/<version>.json`；规则与 schema 中不出现任何 MC 版本号 | [ADR 0002](docs/adr/0002-forge-version-agnostic.md) |
| 3 | skills 是集群，由很多 skill 构成 | 每个 skill = `SKILL.md`（意图层）+ `run.py`（确定性执行层）+ `tests/`（黄金用例）；**skill 之间禁止直接调用**，只通过 manifest 的 delta 交互 | [ADR 0003](docs/adr/0003-skill-cluster-protocol.md) |

## v0.2 · 实证校准（TaCZ 1.20.1 Forge）

用官方源码、Modrinth 编译 jar、Vineflower 反编译产物构成**三条轨**，跑同一套规则，用数据反推分类法。详见 [03 · 实证校准报告](docs/03-empirical-calibration.md) 与 [ADR 0004](docs/adr/0004-empirical-rule-calibration.md)。

| 指标 | 校准前 | 校准后 |
|---|---|---|
| C6 占比（源码轨 / 字节码轨） | 0.2328 / 0.1866 | **0 / 0** |
| 兜底单元 | 186 / 198 | **0 / 0** |
| 源码 vs 字节码 分类一致率 | 0.8108 | 0.8734 |
| 规则数 | 10 | **20** |

由数据推出的四条结论：① 最大盲区是「引用 `net.minecraft.*` 但无 Forge 注解」的类；② 基线把 99 个 `@SerializedName` 数据 POJO **误判成 C1 直译金矿**（比 C6 更危险）；③ 注册 ID 实际来自 `.register("id", ...)` 调用；④ 枚举与平台无关接口分别是状态契约与接口契约，却因「无 import/方法」落入 C6。

实验链已沉淀为 6 个新 skill：`fetch-mod-artifact`、`decompile-forge-jar`、`parse-java-source`、`parse-bytecode`、`compare-tracks`、`calibrate-classification`。

## 流水线

```
S0 规范化  →  S1 机械分诊  →  S2 建图切簇  →  S3 语义裁决  →  S4 人工关卡  →  S5 冻结
 (三轨留存)    (规则, 100%)    (调用图+常量池)   (仅低置信项)     (C6/语义等价)    (hash 锁定)
```

所有阶段读写的都是同一份 `manifest`。分类法见 [docs/01](docs/01-java-decompiled-classification.md)，总纲见 [docs/00](docs/00-methodology.md)，集群协议见 [docs/02](docs/02-skill-cluster-protocol.md)。

## 快速开始

仅依赖 Python 标准库，无需安装任何包。

```bash
# 集群一致性自检：schema、规则符号、registry DAG、frontmatter、golden、幂等
python tools/validate.py            # 30 项全绿

# 对示例 artifact-index 跑确定性分诊
python tools/classify.py \
  --index   tests/fixtures/artifact-index.sample.json \
  --profile profiles/forge/_template.json \
  --rules   rules/classification.rules.json \
  --out     out/classification.delta.json
```

复现完整实验（需先由 intake 系列 skill 把产物放进 `work/`）：

```bash
python tools/experiment.py --profile profiles/forge/1.20.1.json \
  --rules rules/classification.rules.json \
  --out reports/calibration-1.20.1.json --label after
```

`work/` 与 `out/` 已被忽略。产物是 delta（补丁），不是整份 manifest 的覆写，便于 review、回退与并行执行。

## 目录

| 路径 | 内容 |
|---|---|
| `docs/` | 方法论总纲、五维分类法、集群协议、实证校准报告 |
| `docs/adr/` | 四项架构决策记录 |
| `schemas/` | `manifest` / `delta` / `artifact-index` / `capability` 四份 JSON Schema |
| `rules/` | 版本无关的分类判定规则（20 条，符号模式 DSL） |
| `capabilities/vocabulary.json` | 平台无关能力词汇表（26 项） |
| `profiles/forge/` | `_template.json` 模板 + 经实证校准的 `1.20.1.json` |
| `target/horizon.capabilities.json` | Horizon 绑定表，当前全部 `unbound` |
| `skills/` | 12 个 skill；`registry.json` 是 DAG 与读写声明的唯一来源 |
| `tools/` | 分诊器、双轨事实提取库、实验编排器、集群自检器 |
| `tests/` | 夹具（17 个单元）与 golden 输出 |
| `reports/` | 校准前后统计报告（脱敏，不含第三方源码） |

## 边界：明确不做的事

- 不提交任何第三方 mod 的二进制或美术资产；报告只含统计与 unit_id。
- 不在规则、schema、skill 中硬编 MC 版本号或类名 FQN。
- 不绑定 Horizon 的具体运行时（ECS / WASM / trait / 脚本层均未假定）。
- 不实现 Fabric 或其他加载器；但五维分类与 manifest schema 不封死，未来加 `loader_profile` 即可扩展。
- 不把「AI 生成的一段代码」当作 skill 的合格产物。
- **不为了让 C6 数字好看而放宽兜底**；反编译失败与信息不足仍必须显式进人工关卡。

## v0.3 · Horizon 目标侧已明确

查阅工作区内的 Horizon 源码快照（`third_party/horizon`），把 ADR 0001 里「全 unbound」的占位表换成真实绑定。Horizon 是 Rust + wgpu/Vulkan（MIT，MC 26.3），mod 分 **content mod `.hmod`（纯数据/资产）** 与 **native mod `.hnmod`（Rust via horizon-mixins）**；Java mod 不能原样运行。`native-hooks.json` 有 **434 hooks / 177 helpers，318 个带 NeoForge 事件映射**。

26 个 capability 现有 **17 implemented / 8 declared / 1 明确缺口： `animation_driver`**（骨骼动画驱动，0.5 规划未落地）。上游规则、schema、12 个 skill 一行未改——ADR 0001 的隔离设计得到验证。详见 [ADR 0005](docs/adr/0005-horizon-target-binding-and-policy-boundary.md)。

**一处必须知道的边界**：Horizon 官方 `docs/modpacks.md` 的 cleanroom 政策禁止读第三方 **mod code**，但明确允许 *"its own data files"*，且自述为发布侧工程政策（`:153` "engineering policy, not legal advice"）。本仓库是独立方法论仓库、本地研究，读代码在 GPL-3.0 下可行；若要贡献上游或发布，才需切回「不读 mod code」模式。ADR 0005 §4 的方案 C 已拍板，ADR 0008 修正了资产侧边界。

## v0.4 · 方案 C 落地与 M0/M1 交付

- **方案 C 已拍板并工程化**（[ADR 0006](docs/adr/0006-policy-tiered-inspection.md)，资产侧判定已被 **[ADR 0008](docs/adr/0008-policy-three-dimensions.md)** 修正）：`policy-gate` 是 S0 第一道门禁；`(scope × license)` 分档；`default_deny`。
- **M0**：`policy/license-profiles.json`、`policy-gate` skill、两个解析器的 `--policy-mode`、schema 的 `source.policy`。
- **M1**：`mappings/forge-to-horizon.json`（从 Horizon `native-hooks.json` 生成 **162 条事件映射**）、`mappings/disposition-to-tier.json`（C1–C6 → API tier）、`build-hook-mapping` skill。
- **路线图**：[docs/04-roadmap.md](docs/04-roadmap.md)（M0–M4，含验收、依赖、风险与度量）。
- **合规成本实测**（TaCZ 799 单元）：`full-inspection` C6 = 0；`metadata-only` C6 = 0.0013、C1 从 21 降到 17、warnings 4 → 660。签名级元数据仍够用，代价在证据强度而非覆盖率。
- **代码侧始终 `full-inspection`**：v0.2 的 4156 方法 / 3184 字符串事实保留，`oracle-only` 从未作用于代码。

## v0.5 · 子 agent 分工与 M2 规划

- **开箱即用的分工能力**（[ADR 0007](docs/adr/0007-subagent-dispatch.md)）：`estimate-complexity → plan-dispatch → collect-results` 三个 skill；复杂度由**九信号确定性评估器**给出，禁止模型自评；角色与模板由主 agent 维护，子 agent 只收自包含任务包。
- 任务包含 `policy_mode` / `allowed_actions` / `forbidden_actions` / `input_hash` / `acceptance`；子 agent 禁止互相通信，结果由唯一入口汇总并做越界扫描。
- **M2 规划完成**（[docs/05-m2-plan.md](docs/05-m2-plan.md)）：真实输入 4436 资产（94.5% 在内置枪包）；当前实测 **score 0.4255 → M 档 → 2 workers → 12 任务包 / 4 wave → human_gate**（v0.5 时为 0.5255/L/4，合规收紧解除后下降）。
- 实际派出 2 个调研子 agent 并行复核，并**纠正了一处推断偏差**：`roadmap.json:712` 的 set aside 只针对整包移植总目标，0.5 动画仍是 Planned 未实现。
- 硬缺口 `animation_driver` 不变；不依赖 0.5 的两阶段路径：**A** 布尔条件模型 + 静态注册保证逻辑闭环，**B** `render_hand`(cancel) + `render_hand_pose` + `draw_*` + `camera_pose` 做逐块姿态近似。

## v0.6 · 合规模型三维度修正（ADR 0008）

- **上一版收得过紧**：把 CC BY-NC-ND 4.0 的 ND 条款误当成「不能读、不能转」。核查 CC 官方 deed（「若你重混、轉換本素材…**則你不得散佈改作後的素材**」）、CC 官方 QA（*"Format-shifting alone is not an adaptation"*）与 Horizon `modpacks.md:131/141/143/153` 后修正。
- **三维度正交**：`inspection`（能否读）/ `transformation`（能否转，`technical-only` = 语义不变的格式等价转换）/ `distribution`（能否发，`local-only`）。
- **TaCZ 实测修正**：代码 `full-inspection / port / local-only`；资产 `full-inspection / technical-only / local-only`。
- **因此 M2 能做真实转换了**：可读取 `geo_models/*.json`、`*.animation.json`、`display/*.json`、`index/*.json`、PNG、OGG 并做格式等价转换；产物只留 `work/`，**不发布、不商用、不重绘**。
- 发布、商用、贡献上游仍须另走授权或换样本流程；本结论是工程政策判断，**非法律意见**。

## v0.7 · 跨层切片、目标侧源码研读与 M2 真实执行（ADR 0009）

针对「动画 = 美术资产 + Java 状态机 + 目标侧 hook + 同步契约」这类复合体，**按文件分工会失效**——资产组与代码组各自宣布完成，却没人负责缝合，典型事故是「逻辑已换弹、动画还在装填」。

- **跨层特性切片**：`build-feature-slices` 把四层绑成单一可判定单元，`shared_states` 是唯一状态来源。实测 73 个动画文件里其实有 **157 个状态 / 365 个骨骼名**，参数化压到 **110**（压缩 29.94%，映射可逆），10 个切片 `unmatched = 0`、`closed = true`，**2 portable / 8 needs_workaround**。
- **目标侧源码研读做成三路 skill**（`06-target-study`）：`tools/lib_horizon_source.py` + 三份探针配置，真实派出 3 个子 agent 并行读 Horizon Rust 源码，产出可回归取证报告（25 文件 / 424 声明 / `missing_files` 全空）。**纠正 5 处推断**：`Custom` 仅布尔、`foreign.rs` 静默降级第三方 property、`ModelPart` 逐部件姿态可用但无骨骼插值、`mod_api` 无 tier 字段、dev-only Java oracle / coverage 已有实现。精确正则全仓 0 命中证明无 Bedrock geometry / glTF / .bbmodel 读取器。
- **真实格式等价转换落地**：5 个转换器（状态参数化 / 骨骼轨道 / geometry IR / 命名空间重写 / 二进制搬运），**3683 源文件 → 3215 输出，roundtrip 全闭合**，210 MB 产物只留 `work/`。`schema_status` 三态诚实分级：`1 partial / 2 unbound / 2 bound`——`unbound` 不是失败，但绝不写成「已转换完成」。
- **修掉政策断点**：ADR 0008 放宽了政策，但 `roles.json` 的角色权限没跟上，任务包实际仍禁止转换。已同步白名单与角色，并加 3 条回归检查。
- **M2 闭合**：17 任务包 / 4 wave 全部完成，`collect-results` verdict = **COMPLETE**（0 缺失 / 0 越界）；首波改为三路目标侧源码研读。

详见 [执行报告](docs/06-m2-execution.md)、[ADR 0009](docs/adr/0009-cross-layer-slices-and-target-study.md)、`reports/m2-feature-slices.json`、`reports/m2-conversion.json`。

## v0.8 · M3 harness 对接、M4 泛化验证与子 agent 闭环（ADR 0010）

- **M3 修正了一半理解**：真读源码后确认官方 `mod_port_harness.py` 的 10 个 check 全是 **data/资产层 carry 对比，没有 Java 逻辑行为录制**。因此分两层：A 把我们的结论桥接成官方 `harness/result.json` 形状（让 `report.rs` 消费进 coverage），B 自建平台无关的 C1/C2 录制契约与逐 tick 差分断言。`diff-test-harness` 由 `specified` → `implemented`。实测 **23 个契约、PASS 68 项全绿、FAIL 精准抓到 3 类失配**（含「逻辑已换弹、动画还在装填」）。**离线 fixture 不等于真机 oracle 录制**，M3b 仍需可运行的 Java 与 26.3 实例。
- **M4 泛化验证**：同一套 1.20.1 profile + 规则跑四个真实 mod（TaCZ / Farmer's Delight / Create / Iron's Spellbooks），阈值实验前写死 → **C6 与兜底全部为 0，verdict = generalizes**。过程修掉三个真实问题：单段许可证只判一个 scope（门禁广播，TaCZ 基线零变化）、泛型签名被误当类引用（四样本伪引用归零）、`CreateMixinPlugin` 新盲区 → **新增 R021 + golden 用例**，规则 20 → 21 条。
- **子 agent 闭环实证**：3 个独立子 agent 各领 2 个任务，**真实执行命令并各自写 result**，主 agent 只做汇总裁决 → 7/7 COMPLETE、0 越界。抽查 5 项上报数值全部与真实产物一致，并修正 1 处字段类型歧义（`failures` 计数 vs 数组）——`collect-results` 查得了 hash 与越界，查不了语义漂移。

详见 [执行报告](docs/07-m3-m4-execution.md)、[ADR 0010](docs/adr/0010-m3-harness-bridge-and-m4-generalization.md)、`mappings/harness-contract.json`、`reports/m4-generalization.json`。

## v0.9 · M5 单枪竖切：第一次产出目标侧能接受的东西（ADR 0011）

M0–M4 证明了「判断得对」，M5 证明「交得出去」。选 AK-47 一把枪做端到端竖切，五步全部有确定性产物：

| 步 | skill | 实测 |
|---|---|---|
| 状态机 IR | `translate-lua-statemachine` | 18 状态 / 44 转移 / 22 输入 / 8 守卫；53 个 Lua 全部语法解析，2 个完整展开，26 条 unresolved 带原因 |
| 内容包 | `build-content-mod` | `tacz_ak47_pilot.hmod`（6227 B）过官方 `cargo-horizon-mod check` → `ok:true`；两次打包 SHA-256 一致 |
| 原生模块 | `port-native-module` | 纯 std engine，`cargo test --offline` 13/13；18 个状态 id 与 IR 集合相等 |
| 注入点预检 | `verify-hook-catalog` | 2 注入点 / 1 crate 全部命中 434 个 hook；负例报 `E_HOOK_UNKNOWN` 并列候选 |
| 行为差分 | `playable-diff-harness` | 200 tick 剧本 23/23 事件、drift 0；弹匣改成 29 的负例在首个 `Shot` 被抓 |

三处实测纠正：① `minecraft:max_stack_size` 不能放 `components`，官方要求顶层字段；② `transitions[].on` 起初全是 `*`，输入藏在 guard 里，引擎无法消费，改为输入名（只保留 2 条 guard 非空的每 tick 条件驱动）；③ 本机 Horizon 快照没有 `.git`，`horizon_revision` 改用目录指纹并显式标注不等于上游 HEAD。

**M5b 已把 bundle 真的编进游戏**：`horizon-mixins plan/apply` → `cargo build -p horizon-client`（7 min）→ `--dedicated --nogui` 无头服务端启动 48 s，首 tick 打出 `load probe … engine states=18`。路上撞到 4 条 mixins 硬约束（crate 不能带 `Cargo.lock`、快照无 `.git` 时不能钉版本、helper 必须一个私有函数且无 `//!`、`STATES` 在子模块）与 3 条中文路径/安全策略环境坑，全部回写进 skill 与预检。

**四条边界**：`.hmod` 只证明内容被加载器接受；`bindings = []` 仍是空接线，**没有开火**；动画仍 `unbound`；差分的期望值来自数据文件，不是真机录制。详见 [08 · M5 执行报告](docs/08-m5-execution.md) 与 [ADR 0011](docs/adr/0011-vertical-slice-and-native-module.md)。

## 状态与下一步

**v0.9 — M5 单枪竖切完成**：28 个 skill、**112 项自检全绿**、5 个任务包 5/5 COMPLETE、SSH 持续推送。

按 `docs/04-roadmap.md` 推进：

- **M5b**：`horizon-launcher native-build` 把 bundle 编进游戏，在可运行实例里用 `use_item` 打出第一发；这一步才能把 `source_only` 升到 `verified_in_game`。
- **M3b**：搭最小可运行 Java oracle，把 23 个契约的 `oracle.status` 从 `pending` 推到 `recorded → replayed → verified`。
- **M4b**：换跨 MC 版本或混淆样本检验规则泛化，必要时新增 version profile。
- 用实际耗时校准复杂度模型九信号权重（ADR 0007 复核条件）。

五条边界保持诚实：C6 = 0 只是「四个 mod / 同一版本 / 带调试信息」的样本结论；`animation_driver` 仍 **unbound**；`geometry_ir` / `bone_tracks` 只是可逆的中间表示，目标侧没有消费者；**离线 fixture 不等于真机录制**；**官方内容包校验通过不等于游戏里能用**。不用 workaround 冒充已解决。
