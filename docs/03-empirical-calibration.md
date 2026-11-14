# 03 · TaCZ 1.20.1 Forge 实证校准报告

> 本报告全部数字来自本机实际运行，可用文末命令复现。**报告与仓库内不含任何 TaCZ 源码、jar、贴图或模型**；只保留统计、unit_id 与规则。

## 1. 数据来源与版权边界

| 项 | 值 |
|---|---|
| 源码 | 官方 `MCModderAnchor/TACZ` 仓库 `1.20.1` 分支（codeload zip） |
| 二进制 | Modrinth `tacz-forge-1.20.1-1.2.0.jar`（版本清单来自 Modrinth 公开 API） |
| 反编译器 | Vineflower 1.12.0（Maven 镜像） |
| mappings | Mojmap + Parchment（profile 中记录，不硬编进规则） |
| 许可 | Code GPL-3.0 / Assets CC BY-NC-ND 4.0 |

所有第三方产物只落在 `work/`，已被 `.gitignore` 排除。仓库内只有 `reports/*.json`（统计）、`rules/`、`profiles/`、`skills/`、`tools/`。

## 2. 实验设计：三条轨，同一套规则

```
官方源码 .java ──> index.source.json ──┐
                                        ├─> 同一 rules + 同一 profile ─> delta → 统计
jar 内 .class  ──> index.bytecode.json ─┤
                                        │
反编译 .java   ──> index.decompiled.json┘
```

- **源码轨**：解析 package / import / 注解 / 字符串字面量 / 声明类型。
- **字节码轨**：解析 class 常量池与 `RuntimeVisibleAnnotations`，纯标准库，不依赖 javap。
- **反编译轨**：Vineflower 输出，再走源码解析器，用来量化信息损失。

规则与 profile 完全相同，因此三轨差异只来自**事实提取能力**，不来自判定逻辑。这正是「字节码是 ground truth」这一断言的可证伪形式。

## 3. 规模

| 轨 | 单元数 |
|---|---|
| 官方源码 `.java` | 799 |
| jar 内 `.class` | 1061 |
| Vineflower 输出 `.java` | 799 |

262 个内部类 / lambda / 合成类在编译期生成，又被反编译器折叠回外层文件；输出中找不到 `access$` / `lambda$` / `$SwitchMap$` 标记。**结论：伪影折叠不能靠数输出文件，必须靠字节码轨。**

## 4. 基线（校准前）

| 指标 | 源码轨 | 字节码轨 |
|---|---|---|
| C1 / C3 / C4 / C5 / C6 | 66 / 273 / 9 / 265 / 186 | 130 / 371 / 29 / 333 / 198 |
| C6 占比 | **0.2328** | 0.1866 |
| 兜底 R010 单元 | 186 | 198 |
| 源码/反编译 分类一致率 | 0.9837 | — |
| 源码/字节码 分类一致率 | 0.8108 | — |

对 186 个兜底单元做聚合诊断（包 / 注解 / import 前缀），而不是逐个打补丁：

- 包分布集中在 `util` / `block` / `entity/shooter` / `resource/manager` / `command/sub`；
- 注解以 `@Override`、`@Nullable`、`@SerializedName`、`@SuppressWarnings` 为主，几乎没有平台注解；
- 共同特征：**引用 `net.minecraft.*` 但不含 Forge 事件或注解**。

## 5. 四条由数据推出的结论

1. **最大的系统性盲区是「Minecraft 原生 API 依赖」**。旧规则只识别 Forge 事件与 Mixin，把这 186 个类整个漏掉，全推进 C6。补 R017（`vanilla_api` → C3）后归位。
2. **基线把数据 POJO 误判成 C1 纯逻辑金矿**。99 个类带 `@SerializedName`，旧规则因它们没有 MC import 而判 C1——这比 C6 更危险，会让人以为可以直接直译。补 R013（`gson_pojo` → C4）。C1 从 66 降到 21，是**纠错**而非退化。
3. **注册 ID 的真实来源不是静态常量**。`ModItems` 实测有 17 处 `.register("id", ...)` 调用。补 R012 用 `DeferredRegister` / `RegistryObject` / `EventBusSubscriber` 等符号识别注册中心，而不是靠猜常量数。
4. **枚举与平台无关接口是契约的最佳来源，却因「无 import / 无方法」落入 C6**。`ShootResult` 是纯状态枚举；接口是天然的平台无关契约边界。补 R018（C1 `state_enum`）、R019（C2 `api_contract`），并在 `artifact-index` 中新增 `declared_kind` 一维。

另外，剩余两个「空文件 / 空类」由 R020 折叠为 `artifact`，不占用人工关卡；反编译失败与信息不足的样本仍由 `tests/fixtures` 保留为 C6 用例，确保兜底逻辑有回归覆盖。

## 6. 校准动作

新增规则：R011 Mixin 注入族、R012 延迟注册、R013 Gson POJO、R014 内容包资源层、R015 网络同步、R016 可选兼容层、R017 MC 原生依赖、R018 状态枚举、R019 接口契约、R020 空单元折叠。

新增 `profiles/forge/1.20.1.json`：Mixin 注解族（Inject / At / Shadow / Unique / ModifyArg / Accessor…）、Forge 注册类型、Gson 注解、包路径 glob（network / resource / compat / api）。`_template.json` 保持同一符号集合，保证规则换 profile 即可跨版本回归。

所有新增规则都在 `tests/fixtures/artifact-index.sample.json` 中有对应用例，golden 已重生成。

## 7. 校准后

| 指标 | 校准前 | 校准后 |
|---|---|---|
| C6 占比（源码轨 / 字节码轨） | 0.2328 / 0.1866 | **0.0000 / 0.0000** |
| 兜底单元（源码轨 / 字节码轨） | 186 / 198 | **0 / 0** |
| 源码/反编译 分类一致率 | 0.9837 | 0.9900 |
| 源码/字节码 分类一致率 | 0.8108 | 0.8734 |
| C1 / C2 / C3 / C4 / C5（源码轨） | 66 / 0 / 273 / 9 / 265 | 21 / 2 / 390 / 121 / 265 |

`validate.py` 30 项全绿（含 golden 逐字段一致、幂等、registry 无环、frontmatter 一致、写冲突检测）。

## 8. 双轨对照：为什么必须以字节码为准

| 指标 | 值 |
|---|---|
| 注解集合完全相等 | 502 / 798（0.6291） |
| 字节码独有字符串字面量 | 665 |
| 字节码独有的类单元 | 262 |

以 `GameRendererMixin` 为例：源码轨与字节码轨提取出**完全相同的注解集合**，但字节码轨额外拿到 `@At` 的注入点描述符、`"HEAD"` / `"INVOKE"`、`renderLevel` 等方法名——这些正是 Mixin 行为增量所需的 `delta_target` 证据。

## 9. 复现

```bash
# 基线（用旧规则快照时需切回对应提交）
python tools/experiment.py --profile profiles/forge/_template.json \
  --rules rules/classification.rules.json --out reports/calibration-before.json --label before

# 校准后
python tools/experiment.py --profile profiles/forge/1.20.1.json \
  --rules rules/classification.rules.json --out reports/calibration-1.20.1.json --label after

python tools/validate.py
```

前置输入由 `fetch-mod-artifact` / `decompile-forge-jar` / `parse-java-source` / `parse-bytecode` 四个 skill 生成，均只写 `work/`。

## 10. 未决问题（留待下一个样本）

- C6 归零是在**未混淆、带调试信息**的单一 mod 上取得的，不能外推。下一个样本应选混淆或跨版本差异更大的 mod。
- 双轨一致率 0.8734 的剩余差异中，有多少是解析器缺陷、多少是真实信息差，尚未逐条归因。
- `declared_kind` 已能区分 interface / enum / record，但 `api_contract`（C2）目前只覆盖 2 个单元，契约层规则样本不足。
- 美术资产链（C4 资源）尚未用真实 `assets/` 跑过端到端分类。
