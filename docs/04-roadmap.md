# 04 · 路线图：从分类法到可执行的 Horizon 移植流水线

> 状态：v0.4 规划（2026-11-15）。用户已就 ADR 0005 §4 拍板 **方案 C：按许可证分档**。
> 本文件是执行顺序的唯一依据；里程碑按顺序推进，不跳步。每完成一个更新本文件状态并推送。

## 0. 目标与不变式

**目标**：把 rustmc-skills 从「能分类一个 mod」推进到「能按合规边界，把一类 mod 稳定地路由到 Horizon 的具体落地点」。

四条不变式，任何里程碑都不能破坏：

1. **上游不绑目标侧**：规则、schema、manifest 只引用 capability id；Horizon 变化只改 `target/` 与 `mappings/`。
2. **确定性归机器、语义归模型、决策归人**：模型不参与 S1 机械分诊。
3. **合规前置**：任何事实提取之前先过 policy gate；不确定时取最严格档。
4. **产物可回归**：每次改动 `validate.py` 全绿，报告可复现，第三方内容不入库。

## 1. 现状（v0.3 已完成）

| 项 | 状态 |
|---|---|
| 五维分类法 + 20 条实证规则 | 已冻结，TaCZ 1.20.1 上 C6 = 0 |
| 三轨事实提取（799/1061/799） | 可运行，双轨一致率 0.8734 |
| skill 集群 12 个 / registry DAG | `validate.py` 33 项全绿 |
| Horizon 目标侧绑定 | 26 能力：17 implemented / 8 declared / **1 unbound (`animation_driver`)** |
| Git | SSH 已通，`main` 持续推送 |

## 2. 方案 C 的工程化（本轮首要工作）

C 不是一句原则，要落成**可执行的门禁 + 可降级的事实提取 + 可审计的证据**。

### 2.1 双维度分档

不能只按「一个 mod 一个许可证」判定。实测 TaCZ 的 `mods.toml` 写的是：

```
license = "GPL3 / CC BY-NC-ND 4.0"
```

即**代码与资产适用不同许可证**，且不是 SPDX 标准串。因此分档是 `(scope: code | assets) × (license)`，并强制 `default_deny`：解析不出来就取最严格档。

单一 `policy_mode` 一刀切被证明过严：v0.4 曾把 ND 资产判为 `oracle-only`，导致 M2 根本无法做转换。**v0.6 按 ADR 0008 改为三个正交维度**：

| 维度 | 取值 | 说明 |
|---|---|---|
| `inspection` | `full-inspection` / `metadata-only` / `oracle-only` | 能否读、读到什么深度（保留给两个代码解析器） |
| `transformation` | `technical-only` / `creative` / `port` / `none` | `technical-only` = 语义不变的格式等价转换；CC 官方称 format-shifting 不构成改编 |
| `distribution` | `local-only` / `redistributable` | ND 限制的是**分享改编版**与商用，不是本地制作；默认 `local-only` |

TaCZ 实测判定：

| scope | inspection | transformation | distribution |
|---|---|---|---|
| code | `full-inspection` | `port`（Rust 重写） | `local-only` |
| assets | **`full-inspection`** | **`technical-only`** | **`local-only`** |

硬边界：产物只留 `work/`，不发布、不商用、不做创造性改编（重绘/改造型/改写动画表现）；「是否属技术性修改」不确定时 `review_required`；发布须先取得授权或换自有资产。工程政策判断，非法律意见。

### 2.2 门禁位置

```
fetch-mod-artifact → policy-gate ─┬─> full-inspection: parse-java-source + parse-bytecode（代码，现状）
                                  ├─> metadata-only  : 两个解析器降级，只出签名
                                  ├─> oracle-only    : 不解析内容，只出路径清单；交给行为 oracle
                                  └─> 资产链          : technical-only 格式等价转换，local-only 不发布
```

`policy-gate` 是 **S0 的第一道工序**，输出 `work/policy-decision.json` 与 `artifact-index.source.policy`。任务包把三个维度一起下发；`collect-results` 检查发布/商用/创造性改编越界。

### 2.3 与 Horizon 官方政策的对齐程度

官方 `docs/modpacks.md` §Licences 是**发布侧工程政策**：`:131` local by default、`:141-142` ND/NC 的本地 port 只给警告且从不发布、`:143-149` 禁止读的是 **mod code** 并明确允许 *"its own data files"*、`:153` 自述 "engineering policy, not legal advice"。

- **本地研究**：代码 GPL-3.0 可读、资产可做技术性转换，与官方 local by default 一致；
- **贡献上游 / 发布时**：切回「不读 mod code」模式，用行为 oracle + 自有数据文件复现结论，方法本身不变；
- 始终**不复制、不引用、不复述**第三方实现，报告只含统计与 unit_id。

## 3. 里程碑

### M0 · 合规门禁与降级提取（本轮交付）

| 项 | 内容 |
|---|---|
| 交付 | `policy/license-profiles.json`；`policy-gate` skill（含 `run.py`）；两个解析器的 `--policy-mode`；schema 的 `source.policy`；`validate.py` 越界检查；ADR 0006 |
| 验收 | TaCZ 的非标准 license 串能被拆成 code/assets 两档；`metadata-only` 产物中 `methods` / `constant_strings` 全空；`default_deny` 有专门用例；33+ 项自检全绿 |
| 依赖 | 无 |
| 风险 | 许可证字符串是自然语言，规则匹配必然有漏；靠 `review_required` 强制人工兜底，不追求 100% 自动判对 |

### M1 · API 映射表（本轮交付骨架）

| 项 | 内容 |
|---|---|
| 交付 | `mappings/forge-to-horizon.json`（从 Horizon `native-hooks.json` 的 `neoforge` 字段生成）；`build-hook-mapping` skill；`C1–C6 → Horizon API tier` 路由表；`api-mapping-table` 改为消费该表 |
| 验收 | 映射条目数 ≥ 318 且每条可回溯到 hook 名 + side + contract；Mixin/事件样本的 `behavior_delta → event_hook` 能查到具体 hook；映射表不含任何 Horizon 源码 |
| 依赖 | M0（映射表只消费公开元数据，不受 policy 限制，但流程顺序仍前置 M0） |
| 价值 | 直接复用官方 318 条 NeoForge 映射，省掉自建映射表；C5「舍弃/替身」从此变成可查表路由 |

### M2 · 美术链与 `animation_driver` 缺口

> **v0.7 状态：已执行并闭合**，详见 `docs/06-m2-execution.md` 与 `docs/adr/0009`。17 个任务包 / 4 wave 全部完成，`collect-results` verdict = **COMPLETE**（0 缺失 / 0 越界）。

| 项 | 内容 |
|---|---|
| 交付 | 三路 Horizon Rust 源码探针 skill（`06-target-study`）；`build-feature-slices`（10 个四层切片）；`technical-convert-assets`（5 个 roundtrip 闭合的转换器 / 3683 源文件 → 3215 输出）；`reports/m2-feature-slices.json`、`reports/m2-conversion.json`；ADR 0009 与执行报告 |
| 验收 | 切片四层齐全、`unmatched = 0`、roundtrip 闭合、目标侧符号全解析；5 个转换器全部 roundtrip 闭合；产物只留 `work/`；`validate.py` 67 项全绿 |
| 依赖 | M0（三维度门禁）、M1；政策断点已在 v0.7 修复（角色 `allowed_actions` 与策略白名单同步，并加 3 条回归检查） |
| 风险 | **硬缺口未消除，只定位得更精确**：Horizon 有 `ModelPart` 逐部件静态姿态与变换栈，但**无骨骼/蒙皮/关键帧插值与动画驱动**；源码级全仓 0 命中证明无 Bedrock geometry / glTF / .bbmodel 读取器。0.5 为 Planned 未实现（`docs/modpacks.md:183`、`crates/horizon-mods/src/manifest.rs:20-22`），`roadmap.json:712` 的 set aside 只针对整包移植总目标。两阶段 workaround 见 `orchestration/slice-anchors.json#workaround_catalog`，**不得写成「已支持动画」**。`geometry_ir` / `bone_tracks` 标 `unbound`，只是中间表示 |

### M3 · 对接官方 harness（v0.8 离线闭环完成）

> 详见 `docs/07-m3-m4-execution.md` 与 ADR 0010。

| 项 | 内容 |
|---|---|
| 交付 | `mappings/harness-contract.json`（官方字段/路径/生命周期全表）；`schemas/recording-contract.schema.json`；`tools/build_recording_contract.py`；`tools/diff_assertions.py`；PASS/FAIL 两组离线 fixture；`diff-test-harness` 由 `specified` → `implemented` |
| 验收 | 23 个真实 C1/C2 录制契约（`oracle.status=pending`、不编造观测）；PASS 68 项全绿；FAIL 抓到 3 类失配；产出官方形状 `result.json` 可被 `report.rs:283-306` 消费 |
| v0.8 修正 | **官方 harness 只覆盖 data/资产层 carry 对比**（10 个 check），**没有 Java 逻辑行为录制**。所以 M3 分两层：A 桥接结论到官方 `result.json`，B 自建平台无关录制契约与逐 tick 差分。不得把 A 说成「已接入 Java oracle」 |
| 关键坑 | `carry()` 每次删除旧 `harness/result.json`（`carry.rs:1000`），harness 必须在 carry 之后重跑；`report.rs:292` 动态遍历 `checks`，故自定义 check 可被消费 |
| 风险 / 未决 | **真机端到端录制（M3b）未跑**：需 `tools/neoforge_oracle.py export`（1.20.1 NeoForge 实例）+ `cargo build -p horizon-client-lib --example mod_port_probe` + 26.3 客户端资源 + Java 侧行为录制 |

### M4 · 第二样本与泛化验证（v0.8 完成）

| 项 | 内容 |
|---|---|
| 交付 | 三个形态差异大的真实 Forge 1.20.1 mod（Farmer's Delight / Create / Iron's Spellbooks）+ TaCZ 基线；`orchestration/m4-samples.json`；`verify-generalization` skill；`reports/m4-generalization.json` |
| 验收 | 同一套 1.20.1 profile + 规则，阈值实验前写死（C6/兜底 ≤ 0.05）；四样本 **C6 = 0、兜底 = 0 → `generalizes`** |
| 过程发现 | 修掉 3 个真实问题：① 单段许可证只判一个 scope（门禁广播修复，TaCZ 基线零变化）；② 泛型签名被误当类引用（TaCZ 1390 / Create 4829 个假包前缀，四样本归零）；③ `CreateMixinPlugin` 新盲区 → 新增 R021 + golden 用例，规则 20 → 21 条 |
| 局限 | 四样本同为 1.20.1 且带调试信息，**跨版本与混淆样本未验证**；ARR 样本触发 `review_required`，结果仅作本地统计比较 |

### M5 · 单枪竖切（AK-47，v0.9 完成）

> 详见 `docs/08-m5-execution.md` 与 ADR 0011。

| 项 | 内容 |
|---|---|
| 交付 | 5 个 skill（`translate-lua-statemachine` / `build-content-mod` / `port-native-module` / `verify-hook-catalog` / `playable-diff-harness`）、新 stage `05-port`、`schemas/state-machine-ir.schema.json`、`orchestration/m5-slice.json`、`task-templates/m5.json`、5 份报告 |
| 验收 | IR 18 状态 / 44 转移且幂等；`.hmod` 过官方 `check`（`ok:true`）且两次打包同 SHA；engine `cargo test` 13/13 且状态集合与 IR 相等；注入点预检 0 错误、负例 `E_HOOK_UNKNOWN`；差分 23/23、drift 0、负例失败 |
| 关键事实 | 内容与逻辑必须分离：`.hmod` 只装 data/assets（官方拒绝 `Cargo.toml`），行为只能进 `.hnmod` bundle；crate 不允许依赖 `horizon-client`，反而给出可离线 `cargo test` 的纯逻辑单元 |
| 风险 / 未决 | `bindings = []` 已在 M5c 解决；动画仍 `unbound`；差分期望值来自数据文件而非 oracle；快照无 `.git`，`horizon_revision` 只能留空 |
| M5b/M5c | **已完成**：`plan/apply` → 编译 7 min → 无头探针命中；真实 `(game, stack, claimed)` 绑定，`horizon-ctl use-item` 4 次点击 4 次 claim。5 条硬约束与 3 条环境修复已回写 |
| M5d 状态 | **已解除**：不是 IO 崩溃，是启动参数错（resources 指向未 prepare 的 `minecraft-26.3/`、`eula.txt` 读进程 cwd）。改正后 `--dedicated` 34.5 s 起服、无头客户端 153 s 进世界 |
| M5e | **已完成**：31 次 `use-item` → 30 发（ammo 29→0）+ 1 空仓拒绝；`swings` 停在 30 证明空仓不 claim；异物不触发；干净 apply 19 s 且产物与已验证源码逐 token 一致（reports/m5e-ammo.json、m5e-clean-apply.json） |
| 下一步 | ① probe bundle 扩成 crate + 三个钩子，一次 apply/build/run 同时验状态机与开火；② 弹药落可变钩子（现在是 `static AtomicU32`）；③ 子弹实体 + 射线命中 + 伤害 |

## 4. 度量（每次里程碑后记录）

| 指标 | 当前值（v0.8） | 目标 |
|---|---|---|
| C6 占比（源码/字节码） | 0 / 0（TaCZ） | 第二样本上仍 < 0.05 |
| **M4 泛化** | **4 样本 C6 = 0、兜底 = 0 / verdict = generalizes** | 跨版本与混淆样本仍成立 |
| 双轨一致率 | 0.8734 | 逐条归因后 ≥ 0.90 |
| Horizon 能力缺口 | 1（`animation_driver`，源码级定位） | 明确临时方案，不假装已解决 |
| policy 覆盖率 | 100% 样本过门禁；单段广播 + review_required | 解析失败强制 review |
| NeoForge → hook 映射 | 162 条 / 156 事件 | 随 Horizon 快照重生成 |
| 分类规则 | **21 条（R021 由 M4 新增，有 golden 用例）** | 新盲区必须附用例 |
| 子 agent 任务包 | M2 17（COMPLETE）；**M3/M4 7（6 个由 3 个独立子 agent 真跑真写，COMPLETE）** | 用实际耗时校准并行收益 |
| 跨层切片 | **10（157→110 状态，2 portable / 8 needs_workaround）** | 第二样本检验锚点是否需扩展 |
| 格式等价转换 | **5 个转换器 / 3683 源文件 / roundtrip 全闭合 / 1 partial + 2 unbound + 2 bound** | 内容级转换需在可运行环境验证 |
| 目标侧源码探针 | **3 路 / 25 文件 / 424 声明 / missing_files 全空** | 随 Horizon 快照重跑比对 |
| M3 harness 对接 | **离线闭环完成（23 契约 / PASS 68 项 / FAIL 抓 3 类失配）** | M3b 真机录制 |
| `validate.py` 检查数 | **130** | 随里程碑递增，始终全绿 |
| **M5 内容包** | **官方 check ok=true / 6227 B / 两次打包同 SHA-256** | 游戏内注册与显示 |
| **M5 状态机 IR** | **18 状态 / 44 转移 / 22 输入 / 26 unresolved 带原因** | 与运行时转移序列对齐（需 oracle） |
| **M5 原生模块** | **cargo test 13/13 / 状态集合与 IR 相等 / bindings 已绑定并在游戏内命中** | 可变状态钩子 |
| **M5b 编译加载** | **plan ok / apply 110s / build 7min / 无头服务端首 tick 探针命中** | 第一人称表现 |
| **M5c 开火路径** | **内容包注册成功（1659 items）/ 4 次右键 4 次 claim** | 弹药、子弹、命中、同步 |
| **M5e 弹匣语义** | **31 点击 = 30 发（29→0）+ 1 空仓；swings 停在 30；异物不触发** | 每玩家/每物品栈弹药、换弹 |
| **M5e 干净 apply** | **19 s / 1 injection / 与就地补丁逐 token 一致** | 一次 apply 出全量钩子（crate + 3 hooks） |
| **M5 差分** | **23/23 事件、drift 0、负例失败** | 覆盖后坐/散布/命中/同步 |
| **M5 子 agent** | **5 任务 / 3 wave / 5 COMPLETE / 0 越界** | 与 M2 的 17 任务对比并行收益 |

**合规成本实测（M0，TaCZ 799 单元，同一套 20 条规则）**：

| 档位 | C1 | C2 | C3 | C4 | C5 | C6 | C6 占比 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `full-inspection` | 21 | 2 | 390 | 121 | 265 | 0 | 0.0000 |
| `metadata-only` | 17 | 2 | 390 | 121 | 268 | 1 | **0.0013** |

降级只让 1 个单元落入 C6、4 个纯逻辑类失去 C1 证据，但 warnings 从 4 涨到 660（证据变少导致低置信与下钻告警激增）。结论：**签名级元数据足以支撑大部分分类判定**，合规代价主要在证据强度而非覆盖率。这个数字要随每次规则升级重测，不能只报一次。

## 5. 明确不做

- 不在 `full-inspection` 之外读取第三方源码正文或常量池字符串。
- 不把 Horizon 源码、TaCZ jar/源码/资产复制进本仓库。
- 不赌 Horizon 0.5 的排期，不把「未来会有」写成「现在可用」。
- 不为了让指标好看而放宽兜底或跳过人工复核。
- 不把本仓库成果宣传为「Horizon 官方兼容方法」；上游贡献需另走 cleanroom 合规。

## 6. 决策台账

| ADR | 决策 |
|---|---|
| 0001 | 平台无关能力契约层，隔离 Horizon 不确定性 |
| 0002 | 只做 Forge、版本无关（符号模式 + profile） |
| 0003 | skill 集群双形态 + 仅经 delta 交互 |
| 0004 | 规则升级由真实样本驱动，判定以字节码轨为准 |
| 0005 | Horizon 目标侧绑定、tier 路由、cleanroom 政策边界 |
| 0006 | 方案 C：按许可证分档的合规门禁（资产侧判定已被 0008 修正） |
| 0007 | 子 agent 分工：确定性复杂度 + 自包含任务包 |
| 0008 | **合规模型三维度：技术性转换可做、分发受限（v0.6）** |
| 0009 | **跨层特性切片、目标侧源码研读三路探针、真实格式等价转换与政策断点修复（v0.7）** |
| 0010 | **M3 harness 对接分层、M4 第二样本泛化、单段许可证广播与独立子 agent 闭环实证（v0.8）** |
| 0011 | **单枪竖切优先、内容包与原生模块分离、状态机 IR 为跨层契约（v0.9）** |
