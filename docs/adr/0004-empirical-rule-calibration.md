# ADR 0004 · 规则升级必须由真实样本驱动，判定以字节码轨为准

- **状态**：Accepted（v0.2，2026-11-15）
- **决策者**：本仓库（用户要求「通过试验的方法推出 Java 源码分类，通过实践完善 skill」）
- **相关**：`docs/03-empirical-calibration.md`、`tools/experiment.py`、`tools/lib_facts.py`、`profiles/forge/1.20.1.json`

## 背景

v0.1 的分类规则完全由方法论推演产生，未经真实 mod 验证。用户要求拿 TaCZ 1.20.1 Forge 的实际产物做实验，用结果反推分类法，并把过程中需要做的事都写成 skill。

实验暴露出的问题不是「几个标签不准」，而是**推演式规则存在系统性盲区**：基线把 23.28% 的单元推进 C6，同时把 99 个 Gson 数据 POJO 误判成可直接直译的 C1 金矿。后者尤其危险——它不会报错，只会让人对移植难度产生错误信心。

## 决策

### 1. 规则升级固定走六步闭环

`baseline → 聚合诊断 → 补 profile 符号 → 补规则 → 补 fixture/golden → after 对比 + ADR`

- 诊断必须**按包 / 注解 / import 前缀聚合**，找系统性盲区，禁止逐个样本打补丁。
- 每条新规则必须在 `tests/fixtures` 有对应用例，且 `validate.py` 全绿。
- 校准前后报告都归档在 `reports/`，可复现、可比较。
- 由 `calibrate-classification` skill 承载这一流程。

### 2. 判定以字节码轨为准（ground truth）

保留三条轨：官方源码、反编译源码、jar 内 class 常量池。三者跑同一套规则，但：

- 源码轨 / 反编译轨供人与模型阅读；
- **冲突时以字节码轨为准**，因为常量池、注解属性、内部类是源码轨不可见的事实（实测字节码独有字符串 665 个、内部类 262 个、注解集合完全相等率仅 0.6291）。
- 现代反编译器会折叠伪影，因此「数输出文件」不构成伪影判定依据。

实现上 `parse-bytecode` 用纯标准库解析 class 常量池与注解属性，不依赖 javap、反编译器或外部 mappings。

### 3. `declared_kind` 成为事实清单的一维，接口按契约处理

在 `artifact-index` 中新增 `declared_kind`（class / interface / enum / record / annotation）。理由由实验给出：

- 平台无关 **interface** 是天然的可移植契约边界 → `C2 api_contract`，进 portable contract，不直译实现；
- **enum** 是跨层状态枚举的直接来源 → `C1 state_enum`，其常量应作为 `shared_states` 候选；
- 这两类原本因「无 import / 无方法」落入 C6，是事实提取能力不足，不是语义不明。

### 4. 版权边界写进流程而非只写进文档

第三方源码 GPL-3.0、资产 CC BY-NC-ND 4.0。所有产物只落 `work/`；报告**只含统计与 unit_id**；`validate.py` 增加「`work/` 与二进制产物被排除入库」检查。skill 的 `fetch-mod-artifact` 记录 provenance，`decompile-forge-jar` 明确标注反编译源码不是 ground truth。

### 5. C6 归零不是目标，证据完整才是

C6 从 0.2328 降到 0 是**规则覆盖面**改善的结果，不是放宽兜底的结果。反编译失败、信息不足仍必须显式进人工关卡，并由 fixture 保留回归用例。禁止为了让数字好看而降低兜底标准。

## 后果

**正面**

- 规则从「推演」变成「有实测基线与回归用例」；下次升级可量化是否退化。
- 双轨差异从主观断言变成可测指标（一致率、注解相等率、独有字符串数）。
- 实验链本身沉淀为 6 个可复用 skill，后续换 mod / 换版本直接重跑。

**负面 / 代价**

- 需要维护第三条轨与对照逻辑，实验脚本复杂度上升。
- `declared_kind` 改动了 `artifact-index` schema，属 v0.2 兼容性变更；外部消费方需同步。
- 单一未混淆样本的 C6 归零容易被误读为「方法已完备」，已在 `docs/03` §10 显式标注不可外推。

## 复核条件

1. 第二个真实 mod（优先选混淆或跨版本差异大的）跑完同一流程；
2. 双轨一致率低于 0.85 且无法归因于解析器缺陷；
3. `api_contract`（C2）样本数足以支撑契约层规则；
4. 决定支持 Forge 之外加载器时，需重新验证三轨提取器。
