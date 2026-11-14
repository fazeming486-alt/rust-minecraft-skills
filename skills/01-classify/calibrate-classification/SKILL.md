---
id: calibrate-classification
version: 0.1.0
stage: 01-classify
execution: deterministic
status: implemented
reads: ["units[].semantic", "units[].disposition", "units[].evidence"]
writes: []
depends_on: ["compare-tracks", "classify-java-decompiled"]
acceptance: ["输出校准前后 C6 占比与兜底单元数", "报告只含统计与 unit_id，不含第三方源码", "每条新增规则都有 golden 用例覆盖", "规则升级后 validate.py 全绿"]
---

# calibrate-classification

## 目的

**用真实 mod 反复跑分类，靠数据而不是直觉改规则。** 这是「通过实践完善 skill」的执行入口。

## 流程（固定，不可跳步）

1. 用当前规则 + 当前 profile 跑三轨，产出 `reports/calibration-before.json` 基线。
2. 诊断 `fallback_samples` 与 `c6_samples`：按包、注解、import 前缀聚合，找**系统性盲区**（不是逐个打补丁）。
3. 把新符号补进 `profiles/forge/<version>.json`，把新判定写成规则（符号模式，不写字面 FQN）。
4. 给 `tests/fixtures/artifact-index.sample.json` 补对应单元，重生成 golden。
5. 重跑实验产出 `reports/calibration-<version>.json`，与基线对比；`validate.py` 必须全绿。
6. 把结论写进 `docs/03-empirical-calibration.md` 与 ADR。

## 实测：TaCZ 1.20.1 一次校准的结果

| 指标 | 校准前 | 校准后 |
|---|---|---|
| C6 占比（源码轨） | 0.2328 | **0.0000** |
| 兜底单元 | 186 | **0** |
| 源码/字节码一致率 | 0.8108 | 0.8734 |
| 纯逻辑 C1 误判 | 66（含大量数据 POJO） | 21 |

**四条由数据推出的结论**（不是拍脑袋）：

1. 基线最大的盲区是「引用 `net.minecraft.*` 但不含 Forge 事件/注解」的类——186 个全落 C6。补 R017 后它们进 C3 平台适配。
2. 基线会把 `@SerializedName` 数据 POJO 误判成 C1 纯逻辑金矿（99 个）。**这比 C6 更危险**，因为会让人以为可以直接直译。补 R013 后归 C4。
3. 注册 ID 实际来自 `.register("id", ...)` 调用（实测 `ModItems` 有 17 处），不是静态 `ResourceLocation` 常量。补 R012。
4. 枚举与平台无关接口没有 import/方法特征，原本落 C6；它们分别是状态契约与接口契约的最佳来源。补 R018（C1 `state_enum`）/ R019（C2 `api_contract`）。

## 边界

- 报告**只含统计与 unit_id**，绝不写入第三方源码、字符串内容或资产。
- 不为凑好看的数字而放宽兜底：C6 归零的前提是每条新规则都有真实依据与 golden 覆盖。
- 不修改规则库之外的代码来「适配」某个 mod；差异必须沉淀成 profile 或规则。

## 运行

```bash
python skills/01-classify/calibrate-classification/run.py \
  --profile profiles/forge/1.20.1.json \
  --rules rules/classification.rules.json \
  --out reports/calibration-1.20.1.json --label after
```
