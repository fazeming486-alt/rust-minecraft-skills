# ADR 0002 · Forge 单加载器 + 版本无关的规则机制

- **状态**：Accepted（v0.1，2026-11-15）
- **决策者**：本仓库（用户明确：只做 Forge，版本无所谓，随时会变）
- **相关**：`rules/classification.rules.json`、`profiles/forge/_template.json`、`tools/classify.py`

## 背景

目标加载器限定为 Forge，但 MC 版本会持续变化，不由本项目固定。传统做法把注解 FQN、包名前缀、mappings 名硬编在分类规则或脚本里，结果是每换一个版本就要改规则、改代码、重做测试——而本仓库要维护的是**大量 skill**，这种耦合会让规则库迅速腐化，且不同版本的判定结果无法互相回归。

## 决策

**规则库只写符号模式（symbol pattern），版本字面值全部外置到可插拔的版本档（profile）。**

1. `rules/classification.rules.json` 中只出现符号引用，例如 `("annotation", "Mixin")`、`("type_prefix", "FORGE")`；**不出现**任何类名 FQN、包名字符串或 MC 版本号。
2. `profiles/forge/<mc-version>.json` 提供「符号 → 该版本字面值列表」的展开表，以及 mappings 命名空间、包前缀、路径 glob。`_template.json` 是模板，`mc_version: null` 表示版本未指定。
3. `tools/classify.py` 在执行时把规则里的符号按 profile 展开后再与 `artifact-index` 中从**字节码读出的原始字面值**比对。版本变了只换 profile，规则、schema、脚本、golden 用例都不动。
4. manifest 的 `source.mc_version` 与 `source.mapping_id` 是**记录字段**，不是约束字段：schema 不枚举版本，允许 `unspecified`。同一套规则可用多个 profile 跑同一份 index 做跨版本回归。
5. **profile 缺符号必须报错**：`validate.py` 检查规则引用的每个 `(group, name)` 在 profile 中存在；`classify.py` 遇到未展开符号直接失败。禁止静默失配——静默失配会把「版本没适配」伪装成「规则没命中」。
6. 优先使用**字节码结构特征**（继承、注解描述符、方法签名、常量池）而非名称匹配；名字只是可替换的证据源。

## 范围

- 当前**只实现 Forge**。`artifact-index.schema.json` 的 `source.loader` 允许其他值但 v0.1 只有 Forge profile；不实现 Fabric 判定规则。
- 五维分类、manifest schema、delta 协议不封死加载器：未来加 `loader_profile` 与对应 profile 即可扩展，无需重构上游。

## 后果

**正面**

- 新增 MC 版本的成本 = 新增一个 JSON profile + 跑一次 golden，不动代码。
- 规则库可跨版本回归，命中率差异可度量。
- 规则与证据解耦：同一判定在不同版本可回溯到不同字面值。

**负面 / 代价**

- 多一次符号展开；规则可读性对新人略差，必须配合 `docs/01` 的规则表阅读。
- profile 需要有人维护，且必须与实际反编译所用 mappings 一致；不一致会导致系统性漏判（由缺符号报错部分缓解）。
- 版本间语义差异（不只是名字差异）无法靠 profile 解决，需由 `extract-behavior-contract` 在契约层处理，并在 ADR 中记录。

## 复核条件

1. 首个真实版本的 profile 落地时；
2. 出现「同一语义在不同版本需不同规则」而非「仅名字不同」时（此时需引入版本化规则覆盖机制）；
3. 决定支持 Forge 之外的加载器时。
