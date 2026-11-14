---
id: parse-java-source
version: 0.1.0
stage: 00-intake
execution: deterministic
status: implemented
reads: []
writes: []
depends_on: ["fetch-mod-artifact"]
acceptance: ["每个 .java 生成一个 unit", "注解简单名必须解析成 FQN", "字符串字面量与 .register 调用计数全部保留"]
---

# parse-java-source

## 目的

把 Java 源码树解析成 `artifact-index.json`（源码轨）。产物结构与字节码轨完全一致，便于对照。

## 提取的事实

- `package` / `import`（含通配符）、注解（**简单名 → FQN**，含 `@Mod.EventBusSubscriber` 这类嵌套注解）
- `declared_kind`：class / interface / enum / record / annotation
- 字符串字面量（含注解参数，如 `@SerializedName("ammo")`、`@Inject(method="renderLevel")`）
- 方法名、`.register("id", ...)` 调用计数 → `flags.registration_id_count`
- 文件头 BOM 容错；package 缺失时按相对路径回推

## 为什么注解必须转 FQN

规则库用符号模式，profile 里存的是 FQN 字面值。源码写 `@Mixin`、字节码写 `Lorg/spongepowered/.../Mixin;`，只有都归一成 FQN，两条轨才能共用同一套规则。实践里这一步做对后，Mixin 类的注解集合在两轨上完全一致。

## 边界

- 不做语义分析、不编译、不调用模型。
- 不读 jar、不处理 class（属于 `parse-bytecode`）。
- 不把源码内容写进报告；只输出结构化事实。

## 运行

```bash
python skills/00-intake/parse-java-source/run.py \
  --root work/TACZ-1.20.1 --source-root src/main/java \
  --out work/index.source.json
```
