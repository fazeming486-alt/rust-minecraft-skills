---
id: compare-tracks
version: 0.1.0
stage: 00-intake
execution: deterministic
status: implemented
reads: []
writes: []
depends_on: ["parse-java-source", "parse-bytecode"]
acceptance: ["输出两轨的单元数差与分类一致率", "输出注解集合相等率与字节码独有字符串数", "明确写出以字节码轨为准的结论"]
---

# compare-tracks

## 目的

量化「源码轨 vs 字节码轨」的事实差异，把「字节码是 ground truth」从断言变成可测量的数字。

## 实测（TaCZ 1.20.1，校准后）

| 指标 | 值 |
|---|---|
| 源码 / 反编译 / 字节码单元数 | 799 / 799 / 1061 |
| 字节码独有的类单元 | 262 |
| 源码 vs 反编译 分类一致率 | 0.9900 |
| 源码 vs 字节码 分类一致率 | 0.8734 |
| 注解集合完全相等 | 502 / 798（0.6291） |
| 字节码独有字符串字面量 | 665 |

## 怎么解读

- **0.99**：未混淆、带调试信息的 mod，反编译保真度很高，源码轨可用于人工阅读。
- **0.8734 与 0.6291**：字节码轨确实含有源码轨不可见的事实（注解参数、注入点、内部类、常量池引用），所以分类判定以字节码轨为准。
- **262**：内部类/lambda/合成类在编译期生成、又被反编译器折叠，这直接证明「数文件」无法发现伪影。

差异不是噪声，是证据；`compare-tracks` 的产物应随每次规则升级一起归档，用于判断一致率是否退化。

## 边界

- 不修改任何 index 或 delta，只读、只出报告。
- 不把一致率低直接判为错误——要先定位是解析器缺陷还是真实信息差。

## 运行

```bash
python skills/00-intake/compare-tracks/run.py \
  --source-index work/index.source.json --bytecode-index work/index.bytecode.json \
  --source-delta work/delta.source.json --bytecode-delta work/delta.bytecode.json \
  --out work/compare-tracks.json
```
