# ADR 0006 · 方案 C：按许可证分档的合规门禁

- **状态**：Accepted（v0.4，2026-11-15，用户拍板）；**部分被 ADR 0008 修正（v0.6）**
- **取代**：ADR 0005 §4 的「待拍板项」
- **修正提示**：本 ADR 中「ND 资产 → `oracle-only` / 不读内容」的判定**已废止**。CC BY-NC-ND 4.0 的 ND 只限制分享改编版与商用，本地语义不变的技术性格式转换可行；现行三维度模型见 [ADR 0008](0008-policy-three-dimensions.md)。以下原文保留作为决策历史。
- **相关**：`docs/04-roadmap.md`、`policy/license-profiles.json`、`skills/00-intake/policy-gate/`

## 背景

ADR 0005 发现本仓库 v0.2 的双轨事实提取与 Horizon 官方 cleanroom 政策（`docs/modpacks.md` §Licences 第 4 条：第三方 mod 代码不反编译、不阅读）不一致。给出 A 独立研究 / B 完全对齐 / C 按许可证分档三条路。用户选 **C**。

实测还暴露两个必须先解决的细节：

1. TaCZ 的 `mods.toml` 写的是 `license = "GPL3 / CC BY-NC-ND 4.0"` —— **不是 SPDX 标准串，且一个 mod 内代码与资产适用不同许可证**。按「一个 mod 一个标签」分档必然误判。
2. Horizon 官方 `horizon-port-pack events` 只列监听器签名、且明确「for a human to review; it doesn't translate them」——签名级提取是与上游兼容的，深度提取不是。这给了分档一个天然边界。

## 决策

### 1. 三档 `policy_mode`

| 档位 | 允许 | 禁止 |
|---|---|---|
| `full-inspection` | 源码正文、class 常量池、字符串字面量、注解参数值 | — |
| `metadata-only` | jar 元数据、资源清单、类签名（FQN / 注解类型名 / 父类 / 接口 / 声明类型） | 方法名、方法体、常量池字符串、注解参数值、源码正文 |
| `oracle-only` | 行为观测（dev-only Java oracle 的输入/输出）、公开文档、自有数据文件 | 上述全部，含签名级提取 |

`redistribution` 是**独立布尔量**：GPL 类 copyleft 允许本地研究但发布衍生需同协议开源；CC BY-NC-ND 禁止演绎，本地转换产物也不得发布。两者不得混为一个标签。

### 2. 双维度分档与 `default_deny`

分档维度是 `(scope: code | assets) × (license)`，不是 mod 级单标签。非标准许可证串按分隔符拆分后逐段匹配 `policy/license-profiles.json` 的规则；**任何解析失败、冲突或未知，一律落到最严格的 `oracle-only` 并置 `review_required: true`**。不追求自动判对 100%，靠人工兜底保证不越界。

TaCZ 的判定示例：

| scope | license | mode | redistribution |
|---|---|---|---|
| code | GPL-3.0 | `full-inspection` | false（copyleft，衍生需同协议） |
| assets | CC BY-NC-ND 4.0 | ~~`oracle-only`~~ → **`full-inspection` / `technical-only` / `local-only`**（ADR 0008 修正） | false（不得发布改编版、不得商用） |

这解释了为什么 v0.2 的**代码侧**双轨实验可以保留（本地研究、报告只含统计），而 **M2 美术链必须降级**：资产是 ND，不能做格式转换产物并发布。

### 3. 门禁位置与强制传导

`policy-gate` 是 S0 第一道工序，位于 `fetch-mod-artifact` 之后、任何解析器之前。它把决策写入 `work/policy-decision.json` 与 `artifact-index.source.policy`。下游 `parse-java-source` / `parse-bytecode` 必须接受 `--policy-mode` 并据此降级；`validate.py` 检查降级产物不含越界字段。

**禁止 skill 绕过门禁自行决定提取深度**；`policy_mode` 是 intake 的必填输入，缺失即失败。

### 4. 与上游政策的对齐程度（诚实表述）

- 对未授权 / ND / 未知样本：完整对齐官方 cleanroom；
- 对自有代码与宽松许可样本：保留完整双轨，这是本项目的研究对象与授权范围；
- 本仓库始终**不复制、不引用、不复述**任何第三方 mod 实现，报告只含统计与 unit_id。

因此方案 C 不是「已经合规到能贡献上游」，而是「把合规变成可按样本切换的机制」。真要贡献上游时，把 `full-inspection` 样本换成自有/授权样本即可，方法本身不变。

## 后果

**正面**

- v0.2 的实验成果不必推翻：代码侧在授权范围内，资产侧被正确隔离。
- 合规从「靠人记着」变成「门禁 + 降级 + 自检」三段可审计机制。
- 为将来贡献 Horizon 上游或处理不同许可证的 mod 留了明确路径。

**负面 / 代价**

- 两个解析器需要维护三档行为；`metadata-only` 下分类精度会下降——**这是合规成本，不是缺陷，必须如实记录**。TaCZ 799 单元实测：C6 从 0 升到 0.0013（1 个单元），C1 从 21 降到 17，warnings 从 4 涨到 660。签名级元数据仍足以支撑大部分判定，代价主要在证据强度。
- 许可证规则是自然语言匹配，需人工复核队列；`review_required` 会成为常态。
- M2 美术链在 ND 资产上只能做本地行为观测与格式差异分析，不能产出可发布的转换产物。

## 复核条件

1. 出现规则无法覆盖的许可证串（应触发 `default_deny` 并人工复核，而非静默放行）；
2. `metadata-only` 档下 C6 占比高到影响方法可用性时，需评估「用行为 oracle 补证据」而不是放宽提取；
3. 决定把成果贡献给 Horizon 上游、或对外发布任何衍生资产时；
4. 目标 mod 的许可证变更（重新过门禁，不得复用旧决策）。
