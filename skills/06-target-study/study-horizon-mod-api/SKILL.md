---
id: study-horizon-mod-api
version: 0.1.0
stage: 06-target-study
execution: deterministic
status: implemented
reads: ["third_party/horizon/crates/horizon-mod-api-gen/**/*.rs", "third_party/horizon/crates/horizon-mods/**/*.rs", "third_party/horizon/crates/horizon-port-pack/**/*.rs", "orchestration/horizon-probes/mod-api.json"]
writes: ["reports/horizon-mod-api.json"]
depends_on: []
acceptance: ["证明 mod_api 不含 tier 字段且 tier 归属 horizon-port-pack 分类逻辑", "0.5 仅声明未实现有行号证据", "dev-only Java oracle / coverage 实现存在且 M3 应对接", "报告不含源码正文"]
---

# study-horizon-mod-api

## 目的

搞清 **Java mod 逻辑重写成 Rust native mod 时，最小可用 API 面是什么**，以及官方移植流水线里哪些轮子已经有了。避免 M3 重造 harness。

```bash
python skills/06-target-study/study-horizon-mod-api/run.py \
  --horizon-root D:/RUST重写mc项目/third_party/horizon \
  --out reports/horizon-mod-api.json
```

## 实测结论（v0.7，纠正了两处推断）

1. **`native-hooks.json` 的 `mod_api` 没有 `tier` 字段**。实测 434 条 hook 的 `mod_api.tier` 全为 `None`；字段是 `contract`（listen / collect / cancel / replace）与 `modifiers`。`crates/horizon-mod-api-gen/src/lib.rs` 从 `api["contract"]` 生成 `Hooks` trait 并决定分发体。
   `data(0.2) / logic(0.3) / machines(0.4) / deep(0.5) / client / none` 是 **`docs/modpacks.md` 的移植分层**，由 `crates/horizon-port-pack/src/classify.rs` 消费，不是 hook 元数据。`orchestration/slice-anchors.json` 的 `api_tier` 是「建议分层」，含义已写进 note。
2. **0.5 仅声明、未实现**。`crates/horizon-mods/src/manifest.rs:20-22` 的 `APIS` 止于 `0.1 / 0.2 / 0.3`；`tree_scan` 对 `animated_model|BedrockGeometry` 为 0 命中。`docs/modpacks.md:183` 把「Bedrock geometry + animations」列为 planned，今日状态为「—」。`roadmap.json:712` 的 *set aside* 只针对 whole-modpacks 总目标，**不能据此说 0.5 动画被搁置**（v0.5 子 agent 已纠正过一次）。
3. **dev-only Java oracle 与 coverage 已有实现**：`crates/horizon-port-pack/src/oracle.rs`（1027 行）、`report.rs`（816 行，含 `coverage.json`）、仓库根 `tools/mod_port_harness.py`。所以 M3 的 `diff-test-harness` 应当**对接现成 harness**，不是自建。
4. **加载链**：`.hmod` content mod 走 `crates/horizon-mods/src/content.rs` + `manifest.rs`；`.hnmod` native 走 `crates/horizon-mods/src/index/native.rs`（cdylib ABI）与 `crates/horizon-mod-registry/src/lib.rs`（`ModType` 分流）；mod API 由 `crates/horizon-mod-api-gen/src/build.rs` 在构建期生成。
5. **最小 API 面**（按分层）：注册 `items` / `blocks` / `data`（0.2）→ tick `server_tick` / `player_tick` / `level_tick_pre`（0.3）→ 输入 `input_key` / `mouse_button_pre`、网络 `client_packet` / `net_send_to_player`（0.4）→ 渲染 `render_hand` / `render_hand_pose` / `standalone_models` / `item_model_property`（client）。

## 与 M3 的关系

`docs/04-roadmap.md` 的 M3 原计划「接 `horizon-ctl` harness」应改为：**复用 `horizon-port-pack` 的 oracle / coverage 链**，我们的 `diff-test-harness` 只负责产出 harness 可消费的录制契约与差分断言。

## 验收

- `missing_files` 为空（v0.7 已把 `build.rs`、`native.rs`、`mod_port_harness.py` 三处路径校准到真实位置）。
- `tree_scan` 的 `api_tier|ApiTier` 保持 0 命中；一旦出现，说明 tier 进入代码层，需重新核对分层口径。
