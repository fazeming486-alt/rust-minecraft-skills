---
id: build-hook-mapping
version: 0.1.0
stage: 03-map
execution: deterministic
status: implemented
reads: []
writes: []
depends_on: []
acceptance: ["映射条目可回溯到 hook 名 / side / contract", "none (无对应事件) 与真实映射分开统计", "生成物不含任何 Horizon 源码"]
---

# build-hook-mapping

## 目的

从 Horizon 的 `native-hooks.json` 生成 **NeoForge 事件 → Horizon 命名 hook** 映射表，供 `api-mapping-table` 与 `behavior_delta → event_hook` 路由查询。直接复用官方成果，不另造一套映射。

## 数据来源与许可

Horizon 是 MIT。`native-hooks.json` 含 434 hooks / 177 helpers，其中 318 个带 `neoforge` 字段；但实测 **161 个是 `none (NeoForge has no ...)`**（官方明确无对应事件），真正有事件名的是 157 个，拆分「A / B」多事件后得到 **162 条映射 / 156 个不同事件**。

生成物只存名称与契约元数据（hook 名、事件名、side、contract、cancellable、target 符号），**不复制任何源码**；`mappings/forge-to-horizon.json` 顶部记录快照路径与许可说明。升级 Horizon 快照后重跑即可，映射表本身不要手改。

## 为什么这件事重要

`docs/native-hooks-neoforge.md` 说明 Horizon 的新钩子刻意按 NeoForge 26.3 事件命名与建模，并明确 `@SubscribeEvent` 方法可映射到 hook 名。于是：

- 我们 v0.2 的 `C5 / behavior_delta`（Mixin、Forge 事件）不再是「舍弃」这么笼统，而是**可查表的具体 hook**；
- `GameRendererMixin → camera_pose / render_hand_pose / compute_fov`、`MouseHandlerMixin → mouse_button_pre` 这类映射有了机器可读依据；
- 查不到映射的事件即记为**能力缺口**，不得猜测。

## 边界

- 不翻译事件语义，只建立名称级映射；语义等价仍需 `api-mapping-table` 由人确认。
- 不把 Horizon 的 hook 实现、Rust 代码或文档正文写进本仓库。
- 不假设快照永久有效：`NATIVE_HOOKS_API` 会升级，映射表需随快照重生成。

## 运行

```bash
python skills/03-map/build-hook-mapping/run.py \
  --horizon-root "D:/RUST重写mc项目/third_party/horizon" \
  --out mappings/forge-to-horizon.json
```
