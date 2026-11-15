---
id: policy-gate
version: 0.1.0
stage: 00-intake
execution: deterministic
status: implemented
reads: []
writes: ["source.policy"]
depends_on: ["fetch-mod-artifact"]
acceptance: ["非标准 license 串按 scope 拆分", "解析失败强制 oracle-only + review_required", "下游解析器按 policy_mode 降级"]
---

# policy-gate

## 目的

S0 的**第一道合规门禁**（ADR 0006 方案 C）。在任何事实提取之前，判定这个样本允许被分析到什么深度，并把决策传导给下游。**禁止 skill 绕过门禁自行决定提取深度。**

## 为什么必须双维度

实测 TaCZ 的 `mods.toml` 是 `license = "GPL3 / CC BY-NC-ND 4.0"`：不是 SPDX 标准串，且**代码与资产适用不同许可证**。按「一个 mod 一个标签」必然误判。

分档 = `(scope: code | assets) × (license)`，另加独立的 `redistribution` 布尔量：

| 档位 | 允许 | 禁止 |
|---|---|---|
| `full-inspection` | 源码正文、常量池、字符串、注解参数值 | — |
| `metadata-only` | 类签名（FQN / 注解类型名 / 父类 / 接口 / 声明类型） | 方法名、方法体、常量池字符串、注解参数值、源码正文 |
| `oracle-only` | 行为观测、公开文档、自有数据文件 | 上述全部，含签名级提取 |

**v0.6 按 ADR 0008 改为三维度输出**：`inspection`（上表三档）/ `transformation`（`technical-only` | `creative` | `port` | `none`）/ `distribution`（`local-only` | `redistributable`）。ND 只限制**分享改编版与商用**，本地语义不变的格式等价转换可行；CC 官方称 format-shifting 不构成改编。

TaCZ 实测：代码 `full-inspection / port / local-only`；资产 **`full-inspection / technical-only / local-only`**（v0.4 曾误判为 `oracle-only`，已废止）。因此 M2 可以读取资产数据文件并做格式等价转换，产物只留 `work/`，不发布、不商用、不重绘。

## 决策规则

- 非标准串按 `/ ; | , and &` 拆分后逐段匹配 `policy/license-profiles.json`。
- 每段取最高优先级规则；同 scope 多段取**最严格**档。
- **任何未匹配、缺失或冲突 → `default_deny`（`oracle-only`）+ `review_required: true`**。不追求自动判对 100%，靠人工兜底保证不越界。
- 用户可用 `--override` 显式覆盖，但覆盖本身会置 `review_required`。

## 输入输出

```
输入: --jar（读 META-INF/mods.toml 或 fabric.mod.json）或 --license "<原始串>"
输出: work/policy-decision.json，并把 policy_mode 写入 artifact-index.source.policy
```

## 边界

- 不做法律判断；本 skill 是工程门禁，不是许可合规意见。
- 不读取任何 mod 代码或资产内容，只读元数据。
- 不缓存旧决策：许可证变更必须重新过门禁。

## 运行

```bash
python skills/00-intake/policy-gate/run.py \
  --jar work/tacz-forge-1.20.1-1.2.0.jar \
  --artifact-id tacz-1.20.1 \
  --out work/policy-decision.json
```
