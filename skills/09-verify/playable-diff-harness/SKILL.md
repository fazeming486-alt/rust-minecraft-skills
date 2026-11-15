---
id: playable-diff-harness
version: 0.1.0
stage: 09-verify
execution: deterministic
status: implemented
reads: ["orchestration/m5-slice.json", "work/m5/state-ir/ak47.json", "work/m5/native/tacz_ak47_pilot/engine"]
writes: ["work/m5/diff/script.txt", "work/m5/diff/trace.jsonl", "work/m5/harness/result.json", "reports/m5-diff.json"]
depends_on: ["translate-lua-statemachine", "port-native-module"]
acceptance: ["同一 trace 重复运行结果一致", "PASS 用例全绿且负例必须失败", "差异定位到 tick", "不依赖游戏进程", "产出官方 result.json 形状"]
---

# playable-diff-harness

## 目的

回答一个很窄的问题：**这把枪的逻辑，和 TaCZ 的数值对得上吗？** 不比对源码，不比对动画，只比对「输入 → 事件时间线」。

M5 之前，仓库里的差分只到 `diff-test-harness` 的录制契约（离线 fixture，23 个契约全是 `oracle.status=pending`）。本 skill 接上真正的执行体：由 `port-native-module` 生成的纯 Rust engine，按 tick 跑剧本，逐事件比对。

## 为什么能离线跑

engine crate 只依赖 std（`crates/horizon-mods` 的 crate 规则也不允许它依赖 `horizon-client`），所以 `cargo run --bin trace` 不需要游戏、不需要 GPU、不需要 26.3 资源。这是 M5 里唯一一处「行为」可以真跑的地方。

**边界**：跑通不等于游戏里能开火。绑定签名（`bindings = []`）与 `native-build` 都还没验证，第一人称表现也无法 headless 观测。

## 输入

| 输入 | 用途 |
|---|---|
| `orchestration/m5-slice.json` | 数值参数：`rpm` / `ammo_amount` / `reload.feed` / `reload.cooldown` |
| `work/m5/state-ir/ak47.json` | 状态与输入集合；断言引擎没有改名 |
| `work/m5/native/tacz_ak47_pilot/engine` | `cargo run --bin trace` 的执行体 |

## 剧本（确定性，写在 run.py 里）

200 tick，覆盖五种行为：

| tick | 动作 | 期望 |
|---:|---|---|
| 0–18 | 按住扳机（auto） | 10 发，每 2 tick 一发（600 rpm @ 20 tps） |
| 20 | 松开 | 停火 |
| 22 | 换弹（战术，弹匣非空） | `ReloadStart(empty=false)`，40 tick 后 `ReloadEnd(ammo=30)` |
| 64–72 | 按住扳机 | 5 发 |
| 76 | 切射击模式 | `ModeSwitch(to=semi)` |
| 78/80/82 | 单发（每次都要松扳机） | 3 发，ammo 29/28/27 |
| 100 | 换弹 | 40 tick 后补满 |

换弹时长从 slice 取：`cooldown.tactical = 2.0s → 40 tick`；空仓换弹是 `2.6s → 52 tick`（本轮剧本不触发，测试里覆盖）。

## 判定

1. **事件序列**：`Shot / ReloadStart / ReloadEnd / ModeSwitch` 逐条比对，tick 容差 1，`ammo_after` 必须精确相等。
2. **状态集合**：engine 导出的 `STATES` 必须与 IR 的 `states[].id` 集合相等（改名即失败）。
3. **负例**：把期望弹匣改成 29 再比一次，**必须失败**并给出首个不一致的 tick。只跑永远全绿的样例不算验收。

## 用法

```bash
python skills/09-verify/playable-diff-harness/run.py \
  --slice orchestration/m5-slice.json \
  --ir work/m5/state-ir/ak47.json \
  --engine work/m5/native/tacz_ak47_pilot/engine \
  --cargo D:/RUST重写mc项目/dev/cargo/bin/cargo.exe \
  --report reports/m5-diff.json
```

产物：
- `work/m5/diff/script.txt`、`work/m5/diff/trace.jsonl`
- `work/m5/harness/result.json`（官方形状：`{mod, passed, checks{name:{passed,failed,examples}}}`，可被 `report.rs:283-306` 消费）
- `reports/m5-diff.json`

## 诚实边界

- 只覆盖 C1 逻辑（开火/换弹/切模式/弹药），**不覆盖**动画、后坐、散布、命中判定、网络同步。
- 期望值来自 TaCZ 的 `ak47_data.json`（经 slice 转写），不是真机录制；M3b 的真机录制仍未做。
- 容差 1 tick 是工程选择，不是等价证明；跨 tick 的插值/延迟补偿不在范围内。
