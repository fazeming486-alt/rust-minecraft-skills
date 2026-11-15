---
id: parse-bytecode
version: 0.1.0
stage: 00-intake
execution: deterministic
status: implemented
reads: []
writes: []
depends_on: ["fetch-mod-artifact"]
acceptance: ["每个 .class 生成一个 unit", "注解描述符与字符串常量来自常量池而非反编译文本", "Long/Double 双槽与 $ 嵌套类正确处理"]
---

# parse-bytecode

## 目的

解析 jar 内 `.class` 的常量池与属性，生成 `artifact-index.json`（**ground truth 轨**）。纯 Python 标准库，不依赖 javap、反编译器或外部 mappings。

## 实现要点

- 完整解析常量池 tag 1/3/4/5/6/7/8/9/10/11/12/15/16/17/18/19/20；Long/Double 占两个槽。
- 从 `RuntimeVisibleAnnotations` / `RuntimeInvisibleAnnotations` 提取类、字段、方法级注解；嵌套注解的 `$` 归一成 `.`。
- 从 `CONSTANT_String` 与注解 `element_value` 收集字符串字面量；从描述符 `Lxxx/yyy;` 收集类型引用。
- `access_flags` 判定 `declared_kind`（enum / interface / annotation / record）。
- 匿名内部类 `$N`、lambda 合成类单独标记。

## 实证：字节码轨为什么不可替代

对 `GameRendererMixin`，源码轨与字节码轨提取出**完全相同的注解集合**；但字节码轨额外拿到 `@At` 的注入点描述符（`Lnet/minecraft/...;popPush(...)`）、`"HEAD"` / `"INVOKE"`、`renderLevel` 等 665 个源码轨没有的字符串。这些正是 Mixin 行为增量的 `delta_target` 证据。

全库统计：注解集合完全相等的比例仅 0.629，字节码独有字符串 665 个，内部类多 262 个。

## 边界

- 不反编译、不生成 Java 源码。
- 不猜测 MC 版本；字面值原样保留，符号展开交给 profile。
- 不修改 jar。

## 运行

```bash
python skills/00-intake/parse-bytecode/run.py \
  --jar work/tacz-forge-1.20.1-1.2.0.jar \
  --policy-decision work/policy-decision.json \
  --out work/index.bytecode.json
```

**合规降级（ADR 0006）**：同 `parse-java-source`。`metadata-only` 只输出类签名（注解类型名、父类/接口、类型引用、declared_kind），不输出方法名、常量池字符串；`oracle-only` 连 class 字节都不读，只按 jar 内路径生成 unit 清单。决策写入 `artifact-index.source.policy`。ADR 0008 后资产侧改为 `full-inspection / technical-only / local-only`，本 skill 仍只处理代码轨，`transformation` / `distribution` 由 `plan-dispatch` 下发。
