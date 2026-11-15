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

**M5b/M5c 已把它放进真实进程**：`horizon-mixins plan/apply` → `cargo build -p horizon-client`（7 min）→ 无头服务端首 tick 打出 `load probe … engine states=18`；再把 `bindings` 换成 `(game, stack, claimed)`，用 `horizon-client --headless --control-socket` + `horizon-ctl give/use-item` 让真实玩家右键——**4 次点击 4 次命中 `native_use_item`**。路上撞到 5 条硬约束（crate 不能带 `Cargo.lock`、快照无 `.git` 时不能钉版本、helper 必须一个私有函数且无 `//!`、`STATES` 在子模块、`minecraft:custom_data` 不是已知组件会让内容包拒绝加载）与 3 条中文路径/安全策略环境坑，全部回写进 skill 与预检。

**四条边界**：`.hmod` 只证明内容被加载器接受；右键只证明进了我们的代码，**没有弹药、没有子弹**；动画仍 `unbound`；差分的期望值来自数据文件，不是真机录制。详见 [08 · M5 执行报告](docs/08-m5-execution.md) 与 [ADR 0011](docs/adr/0011-vertical-slice-and-native-module.md)。

## v0.10 · M5e/M5f 弹匣语义闭环，且与状态机同处一份二进制（不是「枪能打」）

M5c 只做到「右键进了我们的代码」。M5e 把**扣弹与空仓拒绝**在真实无头客户端里观测到；M5f 又把它和 engine 放进同一份构建：

| 断言 | 观测 |
| --- | --- |
| 一次右键一发 | 30 次 `use-item` → 30 行 `shot, ammo=29…0` |
| 空仓拒绝 | 第 31 次打印 `trigger on empty magazine`，不再 shot |
| 只对自己的物品生效 | 切到 `minecraft:apple` 右键，日志无新增 |
| 空仓不自愈 | 之后两次点击仍是 empty |
| 同一份二进制含状态机 | 同进程打出 `load probe: first server tick, engine states=18` |

顺带把两次「运行期卡死」的错误结论纠正了：真正的原因是 ① `--resources` 必须指向 `.local/horizon-client/26.3`（带 `horizon-resources.json`），`minecraft-26.3/` 只是原版安装；② `eula.txt` / `server.properties` 读的是进程 cwd，`--universe` 不负责这件事。M5f 还补一条：apply 出来的 stage 里 `.local/` 是空壳，不能拿它当 `--resources`。

**clean room 的欠账消了**：`probe/ak47_probe` 从 pristine 重跑 apply → `ok`、1 injection、**19 秒**，注入块与就地补丁**逐 token 一致**；随后用完整 bundle（3 注入 + 1 crate）跑通 plan **8.9 s** → apply **20 s** → build **7m46s** → 无头客户端 48 s 进世界。

**一处自我更正**：M5e 首版拿 `state.swings` 当 claim 计数器（30 次慢速点击恰好 30）。M5f 里同一份二进制快速连点 31 次，发数仍是 30 而 `swings` 只有 15——它是会合并/衰减的挥手计数，不能作判据。「空仓不 claim」现在只写成源码级事实（`left == 0` 直接 `return`，早于 `*claimed = true`）。

**状态机接管了弹匣（M5g）**：`engine/src/runtime.rs` 提供进程级共享槽（`on_use` 与 `on_tick` 是两个注入函数，各自 `static` 会是两份状态），一次右键 = `tick(Some(Shoot))` + `release()`，每 tick 由 `on_tick` 推进冷却。探针打出 `states=18 ammo=30 state=main.idle`，23 次点击把 ammo 从 30 打到 7——数字来自 `GunState`，不再是 helper 的常量；engine 单测 13 → **14/14**。

**但射速门控没能观测**：`FIRE_INTERVAL_TICKS=2`（100 ms）比 `horizon-ctl` 单次 `use-item` 往返（实测 161 ms）还短，串行点击永远跨过 3 个 tick；18 个并发点击只有 3 次真正到达游戏。所以「代码与单测在，游戏内证据只到 ammo 由状态机持有并递减」。要验射速必须换驱动通道——这是下一步的前置。

**全自动交给 `player_tick`（M5h）**：`use_item` 只扣扳机（`pull_trigger()` 不推进冷却），开火在 `on_tick` 里按 `FIRE_INTERVAL_TICKS` 走；顺手修掉引擎的 off-by-one（原先 2 tick 间隔实际 3 tick 才发一发）。游戏内：**单击恰好 1 发、没有残余连发**；按住 20 tick 打出 24 发，40 tick 打空 30 发——同一把枪在 M5g 版本按住 40 tick 只有 11 发（那时节奏是游戏自己的 4-tick 重复）。

**速率那条是我的错，已回滚（M5i）**：加计数探针实测 `player_tick` = **0.976 次/游戏 tick**，根本不存在「每 tick 两次」。24 发/26 tick 的真实原因是我把 `fire()` 的 `cooldown` 写成了 `interval-1`（引擎先减再判，存 `interval` 才是 2 tick 一发）。回滚后：单击 1 发、按住有效窗口 16 tick 打出 7 发 ≈ **8.8/s**（标称 10/s），日志还能看到 `blocked: ... cooldown=2`。也顺带更正了 M5g 的日志缺陷（自动射击当时没打印，日志 7 行而弹匣少了 27 发）。

**弹匣落到物品栈（M5j）**：`inventory_tick` 里用 `native_carried_stack(slot) -> &mut ItemStack` 把弹药写进 `minecraft:custom_data.ammo`（只在变化时写），两把 AK 各带各的弹匣。验证分两轮：A 打 5 发存档退出（30→25）；B 重启同一世界，探针先看到 30，**第一发是 `ammo=24`** —— 弹匣确实从物品栈读出来。engine 18/18。

**空仓自动换弹（M5k）**：服务端读不到换弹键，所以「空仓扣扳机」就是换弹入口——干火同时启动 52 tick 换弹。游戏内从 24 发起手：打空打印 `dry fire: magazine empty, reloading`；换弹中 8 次点击全部 `blocked ... cooldown=0 reloading=true`（冷却已 0，拒绝原因是换弹）；`reload finished, ammo=30`；下一发 `ammo=29`。engine 20/20。

**R 键手动换弹（M5l）**：接 `key` 钩子——**无头客户端里它真的会触发**。按 R → `manual reload started` → 40 tick 战术换弹 → `reload finished, ammo=30` → 下一发 29。单机能成立是因为客户端与集成服务端同进程共享状态；多人要模组消息上行（`docs/10` §6 记了单机 `native_net_send_to_server` 直接报错）。

**命中（M5m）**：没有自定义弹射物 API，弹道在 `use_item` 里自解——视线对每只 mob 做**竖直胶囊**垂距判定（半径 0.9），取最近且在首个方块之前的目标，再调 `native_hurt_entity` 走原版伤害管线。游戏内召唤一头牛：`hit minecraft:cow for 9 at 3.1m -> true`，`entities` 显示 **10 → 1 血**。第一版拿脚底点算锥角，因为 `look-at` 瞄眼睛差了 15° 连续失手，改成胶囊才对。

**仍然不是真枪**：伤害类型暂用 `minecraft:arrow` 占位（护甲/死亡消息按箭算），没有爆头、穿透、子弹实体、音效与动画；切枪没有两把 AK 的样本；开火到写回差 1 tick，同槽换枪分不清。仍不是每玩家。

详见 [08 · M5 执行报告](docs/08-m5-execution.md) 的 §8–16、`reports/m5e-ammo.json`、`reports/m5e-clean-apply.json`、`reports/m5f-combined-binary.json`、`reports/m5g-engine-driven-ammo.json`、`reports/m5h-fullauto.json`、`reports/m5i-hook-rate.json`、`reports/m5j-stack-magazine.json`、`reports/m5k-reload.json`、`reports/m5l-manual-reload.json`、`reports/m5m-hitscan.json`。

**两条研究线**（并行子 agent，含源码行号与置信度分级）：`docs/09-horizon-vs-java-world.md`（世界/生物）、`docs/10-horizon-vs-java-combat.md`（战斗/物品）。对下一步影响最大的三条：① 弹药能写回物品栈——`inventory_tick` 里的 `native_carried_stack(slot) -> Option<&mut ItemStack>`；② 没有自定义弹射物 API，要么 `native_summon` 一个雪球模板，要么自写 DDA 射线；③ 服务端读不到扳机/换弹键，必须走客户端 hook + `native_net_from_client` 上行。

## 状态与下一步

**v0.10 — M5e–M5m 弹药闭环 + 单二进制 + 状态机接管弹匣/全自动/持久化/换弹/命中**：28 个 skill、**161 项自检全绿**。

按 `docs/04-roadmap.md` 推进：

- **M5n**：自定义伤害类型（`tacz:bullet`）+ 爆头倍率 + 命中音效。
- **M5o**：切枪（两把 AK 的槽位弹匣）与多人（专用服务器 + 模组消息上行）。
- **M3b**：搭最小可运行 Java oracle，把 23 个契约的 `oracle.status` 从 `pending` 推到 `recorded → replayed → verified`。
- **M4b**：换跨 MC 版本或混淆样本检验规则泛化，必要时新增 version profile。

五条边界保持诚实：C6 = 0 只是「四个 mod / 同一版本 / 带调试信息」的样本结论；`animation_driver` 仍 **unbound**；`geometry_ir` / `bone_tracks` 只是可逆的中间表示，目标侧没有消费者；**离线 fixture 不等于真机录制**；**官方内容包校验通过不等于游戏里能用**。不用 workaround 冒充已解决。

