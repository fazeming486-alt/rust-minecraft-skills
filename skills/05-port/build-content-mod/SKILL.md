---
id: build-content-mod
version: 0.1.0
stage: 05-port
execution: deterministic
status: implemented
reads: ["orchestration/m5-slice.json", "slice.source.texture_slot (PNG)", "third_party/horizon/target/debug/cargo-horizon-mod.exe"]
writes: ["work/m5/content-mod/<mod_id>/**", "work/m5/<mod_id>.hmod", "reports/m5-content-mod.json"]
depends_on: []
acceptance: ["目录符合 docs/modpacks.md 的 .hmod 布局（horizon-mod.toml + data/ + assets/，无代码）", "官方 cargo-horizon-mod build 打包后，check --kind mod --json 返回 ok=true", "item 声明 template 等于 slice，max_stack_size 在顶层且为 1，components 含 custom_data", "26.3 的 items/models/item/lang 引用闭合，贴图字节与源文件逐字节一致", "同一输入连续两次打包的 .hmod SHA-256 一致", "负例（删掉 item 的 template）被官方工具拒绝"]
---

# build-content-mod

把 slice 描述的一件武器打成 Horizon **内容包**（`.hmod`，API 0.2）：只做声明与资源，
不含任何代码。AK-47 只是 `orchestration/m5-slice.json` 的一组取值；换武器改 slice，不改脚本。

```bash
python skills/05-port/build-content-mod/run.py \
  --slice orchestration/m5-slice.json \
  --official-tool third_party/horizon/target/debug/cargo-horizon-mod.exe \
  --report reports/m5-content-mod.json
```

产物：

| 路径 | 说明 |
|---|---|
| `work/m5/content-mod/<mod_id>/` | 未打包的内容包目录（`target/` 是官方工具自己的产物） |
| `work/m5/<mod_id>.hmod` | 官方工具打包后拷贝出来的内容包 |
| `reports/m5-content-mod.json` | 含官方 check 原始 JSON、哈希、逐项自检、负例结果 |

## .hmod 契约

内容包是一个 zip，根上只有 `horizon-mod.toml`、`assets/`、`data/`，**没有 `mod.wasm`、
`Cargo.toml` 或任何 `.rs`**（`cargo-horizon-mod` 见到 `Cargo.toml` 直接拒绝）。manifest
由 `crates/horizon-mods/src/manifest.rs` 以 `deny_unknown_fields` 解析，本 skill 只写这些字段：

```toml
id = "tacz_ak47_pilot"
name = "AK-47 Pilot"
version = "0.1.0"
description = "Local research build ...; not published, not for redistribution."
authors = []
api = "0.2"              # 内容包线
side = "both"
capabilities = ["registries"]   # 内容包必须含
namespaces = []
```

`id` 只能 `[a-z0-9_]{1,64}`；`namespace` 不能占用 `minecraft`、`c`、`horizon`。

## 物品声明与 26.3 资源

物品声明在 `data/<mod_id>/horizon/item/<item>.json`，由 `content.rs` 的 `ItemFile` 解析：

```json
{
  "template": "minecraft:crossbow",
  "max_stack_size": 1,
  "components": { "minecraft:custom_data": { "tacz:gun": "ak47" } }
}
```

- `template` 必须是 vanilla 物品（`minecraft:...`）。
- **`minecraft:max_stack_size` 不能写进 `components`**：`check_item` 对
  `max_stack_size` / `rarity` 两个字段只认顶层。实测按旧写法（放进 `components`）运行时，
  官方工具报 `component "minecraft:max_stack_size": set max_stack_size instead`；
  改为顶层后通过。报告 `notes` 保留了这条原因。
- `components` 是 26.3 数据组件补丁，只放身份标记 `minecraft:custom_data`；它是否产生
  游戏内行为本 skill 不验证。

26.3 资源包（namespace 即 mod id）：

| 文件 | 内容 |
|---|---|
| `assets/<ns>/items/<item>.json` | `{"model":{"type":"minecraft:model","model":"<ns>:item/<item>"}}` |
| `assets/<ns>/models/item/<item>.json` | `{"parent":"minecraft:item/generated","textures":{"layer0":"<ns>:item/<item>"}}` |
| `assets/<ns>/textures/item/<item>.png` | 从 slice 的 `source.texture_slot` 原样拷贝 |
| `assets/<ns>/lang/en_us.json` | `{"item.<ns>.<item>": "<slice.target.mod_name>"}` |

`minecraft:item/generated` 与 `assets/minecraft/items/crossbow.json` 都在 26.3 客户端 jar 内，
引用闭合由脚本自检（items 定义 → 模型 → 贴图 → 语言键）。

## 官方工具

1. `cargo-horizon-mod.exe build`，**cwd 为内容包目录**，产出 `target/horizon-mod/<id>.hmod`；
   它先做一遍与游戏相同的 `Content::read` 校验，再按固定条目顺序写 zip。
2. 拷贝到 `work/m5/<id>.hmod` 后执行
   `cargo-horizon-mod.exe check <hmod> --kind mod --json`；只有 JSON 里 `ok` 为 `true` 才算通过。
3. 失败时原样记录 stdout/stderr 到报告，不绕过、不改判。

## 可复现打包

官方 zip 使用 `SimpleFileOptions::default()`（固定 1980 时间戳、固定 deflate），条目顺序
由 `Content::read` 排序，因此同一输入可复现。脚本连续 `build` 两次，比较两次 `.hmod` 的
SHA-256；不一致就写 `reproducible: false` 并附两次哈希，不伪造。报告本身也不含时间戳，
重复运行字节一致。

## 负例自检

把内容包复制到 `work/m5/content-mod/_negative/<id>/`，删掉 item 声明的 `template` 字段，
再跑一次官方 `build`，**必须失败**（`missing field \`template\``）。失败信息进
`negative_control`，用来证明官方校验不是摆设；若 build 意外通过，则再用 `check` 兜底，
两者都通过则 `ok=false`。

## 明确不做的事

- 不生成 Rust 代码、不建 native bundle（那是 native-module 的职责）。
- 不重绘、不缩放、不重新编码贴图；只搬原字节。
- 不写 `data/minecraft/`、不声明方块/配方/创造标签（本切片只需要物品）。
- 不运行游戏、不证明物品能在游戏里出现或开火；官方 check 只证明声明与包结构合法。
- 不发布、不商用；TaCZ 贴图只进 `work/`，报告只含文件名、尺寸与 sha256。
- 不改 `skills/registry.json`、`tools/validate.py`、`docs/`、`orchestration/`。
