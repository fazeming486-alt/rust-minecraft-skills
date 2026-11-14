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

**一处必须知道的边界**：Horizon 官方 `docs/modpacks.md` 的 cleanroom 政策是「第三方 mod 代码不反编译、不阅读，只从行为 oracle / 公开文档 / 自有数据文件移植」。本仓库 v0.2 的双轨事实提取与之不一致。ADR 0005 §4 给出 A/B/C 三个处理方向（推荐按许可证分档的混合模式），**待用户拍板前不改变仓库定位**。

## 状态与下一步

**v0.3 — 方法已被真实样本验证，目标侧已绑定**：三轨事实提取、20 条实证校准规则、12 个 skill、31 项自检全绿、SSH 推送已通。

C6 归零是在**未混淆、带调试信息的单一 mod** 上取得的，不可外推。下一步（我制定的顺序）：

1. **建 API 映射表 skill**：直接消费 `native-hooks.json` 的 `neoforge` 字段，把 `@SubscribeEvent` / Mixin 映射到命名 hook，替代自建映射表；同时把 `C1–C6 → Horizon API tier (data/logic/machines/deep/client/none)` 路由写进 registry。
2. **补美术资产链缺口**：`animation_driver` 是当前唯一 unbound 能力。用 TaCZ 的 Bedrock geometry / glTF 动画资产做格式差异分析，产出「0.5 落地前可用的临时 draw-list 方案」与契约对齐用例。
3. **接官方 harness**：把 `horizon-ctl` 接入 `diff-test-harness`，用 dev-only Java oracle 作为录制端。
4. **换第二个真实 mod**（优先混淆或跨版本差异大的）验证规则是否过拟合 TaCZ；归因剩余 0.1266 双轨差异。

> 待用户拍板：ADR 0005 §4 的 cleanroom 政策定位（A 独立研究 / B 完全对齐 / **C 按许可证分档（推荐）**）。
