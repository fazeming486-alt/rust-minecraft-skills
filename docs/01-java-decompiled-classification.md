# 01 · Java 反编译产物的分类方法（v0.1 冻结）

本文件是 `classify-java-decompiled` 及所有下游 skill 的规范性依据。修改它需要同步更新 `schemas/manifest.schema.json`、`rules/classification.rules.json` 与 golden 用例，并走 PR。

## 1. 分类的对象不是「代码」

一个 Forge mod jar 拆开后是七类东西的混合物：

| # | 类别 | 典型位置 | 备注 |
|---|---|---|---|
| 1 | 反编译源码 | `*.java` | 供人和模型阅读，**不是 ground truth** |
| 2 | 字节码 | `*.class` | 供程序做精确判定，ground truth |
| 3 | 静态资源 | `assets/<ns>/models,textures,sounds,lang,shaders,particles` | 归美术链 |
| 4 | 数据与内容包 | `data/<ns>/...`、模组自定义内容包 JSON | 数据驱动层 |
| 5 | 元数据 | `META-INF/mods.toml`、`mixins.json`、AccessTransformer、MANIFEST、嵌套 jar | 决定加载与行为增量 |
| 6 | 内嵌依赖 | shaded 库、`META-INF/jars` | 单独识别，别当成 mod 自身逻辑 |
| 7 | 构建残留与反编译伪影 | 合成类、桥接方法、IDE/测试残留 | 折叠剔除 |

**双轨原则**：S0 同时保留源码与字节码。反编译产物会造出合成方法、`access$000`、`$SwitchMap$`、`Outer$1`、`lambda$...` 桥接，泛型被擦除，名字可能还停在 SRG。分类判定以字节码结构特征为准，名字只作为可替换的证据源。

**常量池原则**：跨层引用大量藏在字符串里（注册名、`assets/...` 路径、`Class.forName`、资源重载 key），类型引用图上完全看不见。S2 必须扫常量池并建成跨层边，否则美术资产与逻辑永远对不上。

## 2. 单元（unit）

分类的最小单位是 `unit`：一个类、一个资源文件、一个 JSON、或一个方法簇。每个 unit 有稳定 `unit_id`（由相对路径 + 类型生成），所有 skill 只按 `unit_id` 引用它。

## 3. 五维分类

分类不是打一个标签，而是给每个 unit 挂一组坐标。五维正交，缺一不可。

### A · 载体（carrier）— 物理形态

`source` / `bytecode` / `resource` / `metadata` / `data` / `dependency` / `build_residue`

先按载体切开，避免把贴图当代码分析。载体由 `intake-jar` 按路径与扩展名机械判定，不参与模型裁决。

### B · 语义（semantic）— 功能角色

| 值 | 含义 |
|---|---|
| `registry` | 注册与生命周期：主类、注册表、事件订阅、初始化 |
| `domain_logic` | 真正的游戏规则：状态机、数学、判定、属性叠加 |
| `data_model` | POJO、codec、序列化、配置、数据定义 |
| `platform_glue` | Forge/MC API 调用、Mixin、事件总线、Capability、网络包 |
| `presentation` | 渲染、GUI、粒子、模型加载、动画驱动 |
| `io_persistence` | 存档、网络同步、配置读写、资源重载 |
| `tooling` | datagen、构建、开发期工具 |
| `artifact` | 反编译伪影，不计入移植范围 |

**`platform_glue` 必须单独隔离**：它划出一个 mod 的不可移植面。

### C · 处置（disposition）— 路由键

`C1` 直译 · `C2` 契约重写 · `C3` 平台适配 · `C4` 数据转换 · `C5` 舍弃/替身 · `C6` 人工裁决

详见 [00 · §5](00-methodology.md)。这一维直接决定 unit 交给哪个 skill，是 registry 路由的依据。

### D · 证据（evidence）— 可信度

每条标签必须附带 `evidence[]`，元素形如：

```json
{ "rule_id": "R003", "kind": "annotation", "matched": "org.spongepowered.asm.mixin.Mixin", "source": "bytecode" }
```

`kind` 取值：`annotation` / `import_prefix` / `superclass` / `method_signature` / `package_glob` / `constant_string` / `call_graph` / `flag` / `kind` / `path` / `fallback`。

`confidence ∈ [0,1]`；低于 `0.70` 的 unit 强制进入 S3 语义裁决；`review_state` 为 `unreviewed` / `model_adjudicated` / `human_confirmed`。**没有证据的标签等于没有标签。**

### E · 耦合（graph）— 关系图

`edges[]` 的 `kind`：`inherits` / `implements` / `calls` / `field_ref` / `event_subscription` / `constant_ref` / `registry_id` / `cross_layer_contract`。

`cluster_id` 由 S2 聚类产生，用于功能簇切分与影响面分析。`cross_layer_contract` 边必须双向可查，且指向 manifest 顶层的 `cross_layer_contracts[]` 条目。

## 4. 确定性判定规则

规则库位于 `rules/classification.rules.json`。规则按 `priority` 升序执行（**执行顺序由 priority 决定，不是 id 顺序**），**首个命中的规则给出 semantic + disposition**，所有命中规则都记入 `evidence[]`。确定性、可复现、零模型参与。

下表的 R011–R020 由 [03 · 实证校准](03-empirical-calibration.md) 从真实样本反推得出，**不是推演产物**。按 `priority` 升序列出：

| priority | ID | 命中特征 | semantic | disposition | 来源 |
|---|---|---|---|---|---|
| 10 | R001 | `synthetic` / 无意义匿名类 | `artifact` | `C5` | v0.1 |
| 12 | R020 | 空源码单元（无 import / 方法 / 注解 / 常量） | `artifact` | `C5` | 实验 |
| 20 | R002 | `decompile_failed` / native / 混淆 | 保留原值 | `C6` | v0.1 |
| 25 | R009 | 按 `kind` 分流资源/元数据/数据/依赖 | 按载体 | `C4` / `C5` | v0.1 |
| 30 | R003 | `@Mixin` | `platform_glue` | `C5` | v0.1 |
| 32 | R011 | Mixin 注入族（Inject/At/Shadow/Unique/Accessor…） | `platform_glue` | `C5` | 实验 |
| 35 | R012 | `DeferredRegister` / `RegistryObject` / `EventBusSubscriber` | `registry` | `C3` | 实验 |
| 40 | R004 | 事件订阅注解 / Forge 包前缀 | `platform_glue` | `C3` | v0.1 |
| 45 | R013 | `@SerializedName`（Gson POJO） | `data_model` | `C4` | 实验 |
| 50 | R005 | JSON/codec 解析 或 data 路径常量 | `data_model` | `C4` | v0.1 |
| 60 | R006 | client/render/gui/model 路径 或 渲染类型 | `presentation` | `C5` | v0.1 |
| 62 | R014 | `resource/{pojo,manager,index,serialize,modifier}` 包 | `data_model` | `C4` | 实验 |
| 64 | R015 | `network` / `entity/sync` 包 | `io_persistence` | `C3` | 实验 |
| 66 | R016 | `compat` 包（可选第三方集成） | `platform_glue` | `C5` | 实验 |
| 70 | R007 | 注册 ID 计数密集 | `registry` | `C3` | v0.1 |
| 78 | R018 | 平台无关 `enum` | `domain_logic` | `C1` | 实验 |
| 79 | R019 | 平台无关 `interface` | `api_contract` | `C2` | 实验 |
| 80 | R008 | 无平台前缀且有方法/import 证据的纯逻辑 | `domain_logic` | `C1` | v0.1 |
| 90 | R017 | 引用 `net.minecraft.*` 但无 Forge 事件/注解 | `platform_glue` | `C3` | 实验 |
| 999 | R010 | 兜底 | `unknown` | `C6` | v0.1 |

**R017 是降 C6 的主力**：它接住了基线里 186 个被系统性漏掉的 Minecraft 原生 API 依赖类。**R013 是纠错的关键**：基线把 99 个数据 POJO 误判成 C1 直译金矿，这比落 C6 更危险。

规则里**不写字面 FQN，也不写 MC 版本号**，只写符号名；符号到字面值的展开由 `profiles/forge/<version>.json` 提供。profile 缺符号时 `validate.py` 直接报错，不允许静默失配。

## 5. 反编译伪影的折叠

以下一律判为 `artifact`，不进入移植范围，也不计入工作量估算：

- 合成访问器 `access$NNN`、桥接方法、编译器生成的 `<clinit>` 巨型初始化；
- `$SwitchMap$...`、`Outer$N` 匿名编号类（且无有意义成员）；
- lambda 合成方法 `lambda$xxx$N`；
- 泛型擦除造成的强转与裸类型，不作为语义证据；
- 反编译器为不可达代码补出的占位语句。

折叠需保留 `artifact` 记录与来源，便于复核，但不得删除原始 class 文件。

## 6. Mixin 与事件回调是「行为增量」，不是独立功能

Mixin / Forge 事件回调是对原版行为的 **delta**。必须成对记录：

```json
{ "delta_target": "<被修改的原版目标>", "delta_semantics": "<增量语义>", "hook_candidate": "event_hook" }
```

翻译成目标侧的 hook / 系统扩展点，**不能当普通类直译**。当成普通类处理会得到一堆没有宿主的逻辑碎片——这是 Java mod 移植里最系统性的错误。`extract-behavior-contract` 负责把这类 delta 收敛进 portable contract。

## 7. 混合层下钻

一个 unit 同时命中多条规则是常态，不是异常。规则给出主标签后，若 `mixed_signals ≥ 2`，标记 `requires_drilldown: true`，由 S2 下钻到方法级重新分类，而不是硬塞一个标签。

### 7.1 声明类型（declared_kind）

`artifact-index` 的 `symbols.declared_kind` 由 `parse-java-source` / `parse-bytecode` 提取，取值 `class` / `interface` / `enum` / `record` / `annotation`。它由实证引入：枚举与平台无关接口通常没有 import 或方法特征，旧规则会把它们推进 C6，而它们恰恰是**状态契约**与**接口契约**的最佳来源。

- `enum` → C1 `state_enum`，常量作为 `shared_states` 候选；
- `interface` → C2 `api_contract`，进 portable contract，不直译实现；
- `record` / `annotation` 暂按普通类走后续规则，样本不足，待下一轮校准。

## 8. 输出到 manifest

分类结果写入 `units[]` 的 `carrier` / `semantic` / `semantic_subtype` / `disposition` / `evidence` / `confidence` / `review_state` / `graph.cluster_id` / `provenance`。**写 delta，不覆写整份 manifest**；`provenance.input_hash` 是幂等键的一部分。

## 9. 待真实样本校准

以下参数目前是保守初值，拿到真实反编译产物后必须校准，并作为规则版本升级记录在 ADR 中：

- R007 的「注册 ID 常量密集」阈值；
- `confidence < 0.70` 的裁决门槛；
- `mixed_signals` 的下钻阈值；
- 各 mod 的 C6 占比基线。
