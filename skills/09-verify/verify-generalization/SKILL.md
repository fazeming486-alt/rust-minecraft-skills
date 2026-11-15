---
id: verify-generalization
version: 0.1.0
stage: 09-verify
execution: deterministic
status: implemented
reads: ["orchestration/m4-samples.json", "profiles/forge/1.20.1.json", "rules/classification.rules.json", "work/m4/*.jar", "work/m4/*.policy.json"]
writes: ["reports/m4-generalization.json"]
depends_on: ["classify-java-decompiled", "policy-gate", "parse-bytecode"]
acceptance: ["至少两个与基线形态不同的真实 mod 参与", "阈值先于实验写死且不事后调参", "报告只含统计与包名计数，不复制第三方实现", "发现新盲区时必须新增规则并附 golden 用例，随后复跑归零"]
---

# verify-generalization

## 目的

检验 v0.2 的「C6 = 0」是不是只对 TaCZ 成立。同一套 `profiles/forge/1.20.1.json` + `rules/classification.rules.json`，换真实 mod 重跑，看规则是否过拟合。

**只消费字节码轨**（纯标准库 class 常量池解析），不需要反编译、不需要源码、不需要网络。jar 与 policy decision 只留 `work/`。

```bash
python skills/09-verify/verify-generalization/run.py \
  --samples work/m4/samples.json --out reports/m4-generalization.json
```

## 判定标准（先于实验写死）

`c6_ratio <= 0.05` 且 `fallback_ratio <= 0.05`，对每个非基线样本在 `full-inspection` 档成立 → `generalizes`；否则 `needs_new_rules`。同时跑 `metadata-only` 档作为合规成本对照。

## 实测（v0.8）

四个样本，全部 Forge 1.20.1（只检验「换 mod」，不检验跨版本）：

| 样本 | class | 许可证 | C6 (full) | 兜底 |
|---|---:|---|---:|---:|
| TaCZ（基线） | 1061 | GPL3 / CC BY-NC-ND 4.0 | 0 | 0 |
| Farmer's Delight | 289 | MIT | 0 | 0 |
| Create | 2687 | MIT | 0 | 0 |
| Iron's Spellbooks | 1264 | All Rights Reserved | 0 | 0 |

**结论：`generalizes`**。但过程比结论重要，跑出了三个真实发现：

1. **合规门禁缺陷**：单一许可证串（如 `MIT`）原本只判 code 侧，assets 侧落到 `default_deny` 变 `oracle-only`；`All Rights Reserved` 更错乱（code 最保守、assets 却 full-inspection）。已修为「单段单命中时跨 scope 广播 + 强制 review_required」，明确分段的多段串（TaCZ）不受影响，基线判定零变化。
2. **常量池解析缺陷**：泛型签名 `Ljava/util/Set<...>;` 被整体当成类引用，产生 `java.util.Set<Ljava.lang.` 这类假包前缀（TaCZ 1390 个、Create 4829 个）。已加 `re.fullmatch` 校验，四样本伪引用归零。
3. **新盲区 → 新规则**：Create 的 `CreateMixinPlugin`（`IMixinConfigPlugin`，引用 ASM、无 `@Mixin`、无 MC 前缀）原本掉进兜底。新增 `R021` 归 `C5 / mixin_infrastructure`，并补 golden 夹具用例；复跑后四个样本 C6 与兜底全部归零。

## 一处必须说清的区分

v0.4 记录 `metadata-only` 下 C6 = 0.0013，本轮四个样本在 `metadata-only` 下 C6 均为 0。原因是 **合规成本是轨相关的**：v0.4 测的是源码轨（降级后丢 import 证据），本轮测的是字节码轨（`import_prefixes` / `declared_kind` 在签名级仍保留）。两个数字都对，不可混用。

## 局限

- 所有样本同为 Forge 1.20.1，未检验跨版本；跨 MC 版本需要新 profile。
- ARR 样本触发 `review_required`，其 `full-inspection` 结果仅用于本地统计比较，不作发布依据。
- 规则从 20 → 21 条后，C6 = 0 的可信度提升，但仍是「四个 mod / 同一版本」的样本结论，不外推到混淆样本。
