---
id: intake-jar
version: 0.1.0
stage: 00-intake
execution: deterministic
status: specified
reads: []
writes: ["source", "units[]"]
depends_on: []
acceptance: ["源码与字节码双轨留存", "每个 unit 有稳定 unit_id 与 path/kind", "常量池字符串全部进入 symbols.constant_strings"]
---

# intake-jar

## 目的

S0 规范化：把 mod jar 变成可判定的事实清单 `artifact-index.json`，供 S1 机械分诊消费。

## 必须做的事

1. 解包，**同时保留反编译源码与原始 class 字节码**。字节码是 ground truth，源码只供人和模型阅读。
2. 记录 mappings 命名空间与 `mapping_id`；名字可能仍是 SRG，不要假设已重命名。
3. 按路径与扩展名机械判定 `kind`：`class` / `resource` / `metadata` / `data` / `dependency` / `method_group`。
4. 逐 unit 抽取 `symbols`：注解描述符、父类/接口、import 前缀、引用类型、**常量池字符串**、方法签名。
5. 标记 `flags`：`synthetic` / `anonymous` / `decompile_failed` / `native` / `obfuscated` / `registration_id_count`。
6. 计算 `checksum_sha256`，生成稳定 `unit_id`。

## 两条硬规则

- **常量池必须扫**：注册名、`assets/...` 路径、`Class.forName`、资源重载 key 都藏在字符串里，类型引用图看不到。漏了这一步，美术资产与逻辑永远对不上。
- **不分类**：本 skill 只记录事实，任何 semantic/disposition 都不写。分类是下一个 skill 的职责。

## 边界

- 不提交 jar、class、贴图、音效到仓库（版权边界）。产物只进 `work/` 或 `out/`，均已被忽略。
- 不写字面符号展开逻辑；profile 由分类阶段加载。
- 不调用模型。

## 版本无关

`source.mc_version` 与 `source.mapping_id` 是**记录字段**，允许 `unspecified`；产物中的字面值原样保留，不做任何版本假设。
