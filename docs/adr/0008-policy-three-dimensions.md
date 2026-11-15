# ADR 0008 · 合规模型改为三维度：技术性转换可做、分发受限

- **状态**：Accepted（v0.6，2026-11-15）
- **修正**：ADR 0006 中「ND 资产一律 `oracle-only`、不读内容」的判定；M2 任务包的资产策略
- **触发**：用户指出「最终目的肯定还是要转化，不能按 CC BY-NC-ND 4.0 来」「不读代码怎么做移植」

## 背景：上一版错在哪

ADR 0006 把 CC BY-NC-ND 4.0 的 ND 条款理解为「不能读取、不能转换」，据此把 TaCZ 资产判为 `oracle-only`，M2 的资产子 agent 只能列路径与计数。用户指出这会让移植本身无法进行。核查后确认**这个收紧是错的**，且混淆了三件事：

### 1. 「代码」与「资产」适用不同许可证

`mods.toml` 写的是 `license = "GPL3 / CC BY-NC-ND 4.0"`：代码 GPL-3.0，资产 CC BY-NC-ND 4.0。**我们从未停止读代码**——双轨反编译与常量池解析一直是 `full-inspection`（实测 4156 方法 / 3184 字符串）。`oracle-only` 只作用于资产侧。提问中「不读代码怎么做移植」的担心不成立，是我表述含混导致的误解。

### 2. ND 限制的是「分享改编版」，不是「本地制作/使用」

CC 官方 deed（by-nc-nd/4.0）中文措辞：「若你重混、轉換本素材，或依本素材建立新素材，**則你不得散佈改作後的素材**」；英文：「If you remix, transform, or build upon the material, **you may not distribute the modified material**」。CC 官方 QA 另有：**"Format-shifting alone is not an adaptation"**。NC 只限制商业目的使用。

因此：**本地、非商业、语义不变的纯技术性格式转换是可行的**；被禁止的是把改编版分发出去、商用、以及创造性改编（重绘、改模型造型、二次创作）。

### 3. Horizon 官方 cleanroom 政策是「发布侧」政策，不是本地移植门槛

`third_party/horizon/docs/modpacks.md`：
- `:131` **Local by default** —— 流水线在玩家自己机器上跑，产物留在本地，不重新分发；
- `:137-142` **Publishing needs permission** —— ND/NC 许可「从不发布」，但**本地 port 只是给一条 warning**；
- `:143-149` 禁止读的是 **mod code**，并明确把 *"its own data files"* 列为允许的移植依据；
- `:153` 自述 "This is engineering policy, not legal advice"。

也就是说，官方对 ND 的处理是「本地可做、勿发布」，与 ADR 0006 的 `oracle-only` 完全不同。此前把这条政策当成阻塞，是把「贡献上游/发布」的要求错套到了「本地移植」上。

## 决策：三维度正交模型

放弃单一 `policy_mode` 一刀切，改为三个互不替代的维度：

| 维度 | 取值 | 含义 |
|---|---|---|
| `inspection` | `full` / `metadata-only` / `none` | 能不能读、读到什么深度 |
| `transformation` | `technical-only` / `creative` / `none` | 能不能转；技术性 = 语义不变的格式/结构等价转换 |
| `distribution` | `local-only` / `redistributable` | 能不能分发；`local-only` 表示产物只留本机 |

`policy_mode` 保留为 `inspection` 档位（下游解析器兼容），但决策对象新增 `transformation` 与 `distribution`。

### TaCZ 的修正判定

| scope | license | inspection | transformation | distribution |
|---|---|---|---|---|
| code | GPL-3.0 | `full` | `port`（Rust 重写） | `local-only`（若发布需同协议开源并公布源码） |
| assets | CC BY-NC-ND 4.0 | **`full`** | **`technical-only`** | **`local-only`** |

即：M2 现在**可以**读取 `geo_models/*.json`、`*.animation.json`、`display/*.json`、`index/*.json`、PNG、OGG，并做**格式等价转换**（Bedrock geometry → 目标侧等价结构、动画时间轴 → 目标侧时间轴、贴图/音效必要的技术性重编码）。产物只留本地 `work/`，不发布、不商用、不重绘、不改变艺术内容。

### 仍然保留的硬边界

1. **不分享任何改编版**：`distribution: local-only`，`.gitignore` 排除全部第三方产物；要发布必须先取得作者书面授权或换成自有/宽松许可资产。
2. **不做创造性改编**：重绘贴图、改造模型造型、改写动画表现属 `creative`，需授权。
3. **非商业**：NC 条款。
4. **模糊地带走人工**：某项转换是否「语义不变的技术性修改」不确定时，置 `review_required: true` 并由人判定，不静默放行。
5. **代码侧不变**：GPL-3.0 本地研究可行；发布衍生需同协议。
6. **贡献 Horizon 上游时另说**：若要进入其仓库/发布链，仍需切回「不读 mod code」模式，用行为 oracle + 自有数据文件复现结论。方法本身不变，只换样本与输入。

> 本 ADR 是**工程政策判断，不是法律意见**。发布、商用或对外分发前需法务确认与权利人授权。

## 落地

- `policy/license-profiles.json`：新增 `dimensions` / `mode_profiles`，每条规则带 `transformation` / `distribution`。
- `policy-gate`：输出按 scope 的三维决策 + `distribution_conditions`；`default_deny` 仍作用于「未知/冲突」，但默认值改为 `local-only` 而非 `oracle-only`。
- `orchestration/task-templates/m2.json`：资产任务从 `oracle-only` 改为 `full-inspection` + `technical-only` + `local-only`；`forbidden_actions` 明确禁止 `creative_adaptation` / `publish_adapted_material` / `commercial_use`。
- `plan-dispatch` / `dispatch-pack.schema.json`：任务包传导三个维度。
- `collect-results`：越界检查从「不得含资产内容」改为「不得含发布/商用/创造性改编字段」+ `distribution` 必须 `local-only`。
- `docs/05-m2-plan.md` §1 与 §7 重写：M2 从「规格级差异分析」升级为「可执行的格式等价转换 + 契约对齐」。

## 后果

**正面**

- M2 不再被自设的合规门槛阻塞，可以做真实转换与验证。
- 政策与 CC 官方文本、Horizon 官方「local by default」一致，未来发布路径清晰（拿授权或换资产）。
- 三个维度可独立配置：同一个 mod 可以「读得深、只做技术转换、绝不发布」。

**负面 / 代价**

- ADR 0006 的 `oracle-only` 结论被推翻，v0.4/v0.5 的相关文档、任务包、报告需同步修订；这是一次实质性的政策回退，必须留痕。
- `technical-only` 与 `creative` 的边界需要人工判断，`review_required` 会成为常态。
- 所有产物仍**不可发布**，M2 的成果只能本地验证；若要交付给用户之外的人，需另走授权流程。

## 复核条件

1. 任何发布、商用、对外分发计划出现时（必须重新评估并取得授权）；
2. 决定把成果贡献 Horizon 上游时（切回不读 mod code 模式）；
3. 目标 mod 许可证或权利人声明变更时；
4. 出现无法确定是否属于「技术性修改」的转换类型时，由人裁定并记录。
