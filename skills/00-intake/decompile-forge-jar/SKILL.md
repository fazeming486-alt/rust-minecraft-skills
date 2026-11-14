---
id: decompile-forge-jar
version: 0.1.0
stage: 00-intake
execution: deterministic
status: implemented
reads: []
writes: []
depends_on: ["fetch-mod-artifact"]
acceptance: ["记录反编译器文件名与反编译出的 java 文件数", "输出目录位于 work/", "明确标注反编译源码不是 ground truth"]
---

# decompile-forge-jar

## 目的

编排 Vineflower 把 mod jar 反编译为 Java 源码树，形成「源码 → 编译 → 反编译」的第三条轨，用来量化信息损失。

## 实测结果（TaCZ 1.20.1 / Vineflower 1.12.0）

| 轨 | 文件数 |
|---|---|
| 官方源码 `.java` | 799 |
| jar 内 `.class` | 1061 |
| Vineflower 输出 `.java` | 799 |

反编译输出与官方源码**几乎逐行一致**（仅格式缩进不同），分类一致率 0.99。同时 **262 个内部类/lambda/合成类被折叠回外层文件**，且输出中找不到 `access$` / `lambda$` / `$SwitchMap$` 标记。

结论有两个，都已写进方法论：

1. 现代反编译器会消除大部分伪影，所以「伪影折叠」不能靠数输出文件，必须靠字节码轨；
2. 源码轨（无论官方还是反编译）都不是 ground truth，**判定必须以字节码轨为准**。

## 边界

- 不依赖反编译器做分类判定；它只提供给人/模型阅读的源码。
- 不把反编译源码提交进仓库。
- 不假定所有 mod 都未混淆；混淆/native 由 `classify-java-decompiled` 的 R002 标 C6。

## 运行

```bash
java -jar work/vineflower-1.12.0.jar work/tacz.jar work/decompiled
# 或
python skills/00-intake/decompile-forge-jar/run.py \
  --decompiler work/vineflower-1.12.0.jar \
  --input work/tacz.jar --out work/decompiled \
  --report-out work/decompile-report.json
```
