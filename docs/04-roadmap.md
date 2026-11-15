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

> **v0.5 状态：规划完成**，详见 `docs/05-m2-plan.md`。12 个任务包已生成，2 个调研任务已完成、10 个待派发；分工机制见 ADR 0007。

| 项 | 内容 |
|---|---|
| 交付 | TaCZ 资产清单与格式差异报告（Bedrock geometry / glTF 动画 / 贴图通道 / 音效）；`art-asset-classify` 执行层；0.5 落地前的两阶段渲染方案；跨层契约 `shared_states` 用例 |
| 验收 | 资产完整性清单闭合；逻辑状态机与动画状态机状态枚举一致；产出「不依赖 0.5」的最小可玩表现路径 |
| 依赖 | M0（三维度门禁：`technical-only` + `local-only`）、M1 |
| 风险 | **全项目最大技术风险**：当前 Horizon 无任何骨骼动画 hook/helper；0.5 为 Planned 未实现（`docs/modpacks.md:183`），`roadmap.json:712` 的 set aside 只针对整包移植总目标，不可据此判定 0.5 状态（M2 子 agent 复核纠正，见 ADR 0007）。不赌排期，先做 `item_model_property` + `standalone_models` 压缩姿态，再用 `render_hand`/`render_hand_pose`/draw-list 自建插值 |

### M3 · 对接官方 harness

| 项 | 内容 |
|---|---|
| 交付 | `diff-test-harness` 接入 `horizon-ctl`；dev-only Java oracle 录制格式；状态序列重放比对；视觉快照用例 |
| 验收 | 至少一个 C1 单元完成「Java oracle 录制 → Rust 侧重放」闭环；差异可定位到 unit_id 与 tick |
| 依赖 | M1、M2；需要可运行的 Horizon 实例（工作区已有 `undeadwar-horizon/bin`，D 盘） |
| 风险 | Java oracle 需要 26.3 与 1.20.1 的行为差异对齐；先选不依赖版本语义的纯算法单元 |

### M4 · 第二样本与泛化验证

| 项 | 内容 |
|---|---|
| 交付 | 第二个真实 mod（优先混淆、或跨 MC 版本差异大）；新的 version profile；校准前后报告；过拟合分析 |
| 验收 | 新样本不修改规则主体即可达到可接受 C6 占比；差异只落在 profile 与新增规则；`validate.py` 全绿 |
| 依赖 | M0–M3 |
| 价值 | 检验 v0.2 的「C6 = 0」是否只是 TaCZ 过拟合 |

## 4. 度量（每次里程碑后记录）

| 指标 | 当前值（v0.5） | 目标 |
|---|---|---|
| C6 占比（源码/字节码） | 0 / 0（单一样本） | 第二样本上仍 < 0.05 |
| 双轨一致率 | 0.8734 | 逐条归因后 ≥ 0.90 |
| Horizon 能力缺口 | 1（`animation_driver`） | 明确临时方案，不假装已解决 |
| policy 覆盖率 | 100% 样本过门禁 | 解析失败强制 review |
| NeoForge → hook 映射 | 162 条 / 156 事件 | 随 Horizon 快照重生成 |
| 子 agent 任务包 | 12（4 wave / 2 worker，2 已完成） | M2 全部 result 闭合 |
| `validate.py` 检查数 | 49 | 随里程碑递增，始终全绿 |

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
