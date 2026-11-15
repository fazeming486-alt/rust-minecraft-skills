---
id: verify-hook-catalog
version: 0.1.0
stage: 05-port
execution: deterministic
status: implemented
reads: ["work/m5/native/tacz_ak47_pilot/horizon-mixin.toml", "third_party/horizon/native-hooks.json", "third_party/horizon/docs/native-mods.md", "work/m5/native/tacz_ak47_pilot/engine/Cargo.toml"]
writes: ["reports/m5-hook-catalog.json", "work/m5/native/_negative/*"]
depends_on: ["port-native-module"]
acceptance: ["所有 [[injection]] 的 hook 名存在于 native-hooks.json", "hook_version 等于目录里的 version", "helper 文件与 [[crate]] 目录/Cargo.toml 可解析且无 path/git 依赖", "horizon_revision 与快照一致（git 或明确标注的指纹回退）", "故意写错一个 hook 名必须返回非零并给出 E_HOOK_UNKNOWN"]
---

# verify-hook-catalog

## 目的

在跑 `native-build` 之前，把 bundle 的注入点、helper、crate 依赖与 Horizon 快照对齐，替代构建期才暴露的 `E_HOOK_UNKNOWN` / `E_HOOK_VERSION`。它是**静态**预检：不运行 horizon-mixins，不编译 helper。

```bash
python skills/05-port/verify-hook-catalog/run.py \
  --bundle work/m5/native/tacz_ak47_pilot \
  --catalog third_party/horizon/native-hooks.json \
  --horizon-root third_party/horizon \
  --report reports/m5-hook-catalog.json
```

退出码：`0` 全部通过（含负例被正确判失败），`1` 有错误。路径解析对“仓库根”和“工作区根”都兼容——`third_party/horizon` 实际是 `rustmc-skills` 的兄弟目录。

## TOML 子集解析器

只用标准库，覆盖 `horizon-mixin.toml` 需要的部分：

- `[table]`、`[[array-of-tables]]`，支持点分名；
- 基本字符串（含 `\" \\ \n \t \uXXXX`）、字面量字符串；
- 整数、浮点、布尔；
- 数组（可换行、尾逗号）、内联表 `{ name = "...", ty = "..." }`；
- 行内 `#` 注释（引号内的 `#` 不截断）。

解析失败抛 `E_TOML` 并带**行号**；例如缺 `]` 的表头会报 `line 1: unterminated table header`。重复键、未知裸值、未闭合数组同样带行号。

## 校验规则

### `[[injection]]`

| 检查 | 错误码 |
|---|---|
| `id` 存在且不重复 | `E_INJECTION_ID` / `E_INJECTION_DUPLICATE` |
| `hook` 在 catalog 的 `hooks[].name` 里 | `E_HOOK_UNKNOWN`（附最接近的 3 个候选） |
| `hook_version` 等于该 entry 的 `version`（整数） | `E_HOOK_VERSION` |
| `kind` 在已知集合里且非空 | `E_KIND_MISSING` / `E_KIND_UNKNOWN` |
| `helper` 是 bundle 内的相对路径且文件存在 | `E_HELPER_MISSING` / `E_HELPER_ESCAPE` |
| `bindings` 是数组 | `E_BINDINGS_SHAPE`；非空只给 `W_BINDINGS_UNVERIFIED` |

`kind` 集合取自 `docs/native-mods.md`：`HEAD / BEFORE_CALL / AFTER_CALL / AFTER_ASSIGN / RETURN / TAIL / INVOKE / FIELD / MODIFY_ARG / MODIFY_EXPRESSION_VALUE / OVERWRITE`。只写 `target` 的 raw 注入给 `W_RAW_TARGET`，因为目录无法离线证明它指向 hook point 的函数。

### `[[crate]]`

- 目录存在、含 `Cargo.toml`（`E_CRATE_MISSING` / `E_CRATE_NO_MANIFEST`），path 不得越出 bundle（`E_CRATE_ESCAPE`）；
- 递归检查所有 `dependencies` / `dev-dependencies` / `build-dependencies`：
  - `path = ...` → `E_CRATE_PATH_DEP`；
  - `git = ...` → `E_CRATE_GIT_DEP`；
  - 依赖 `horizon-client` → `E_CRATE_HORIZON_DEP`；
  - `workspace = true` → `E_CRATE_WORKSPACE_DEP`；
- crate 自身带 `[workspace]` → `E_CRATE_WORKSPACE`；带 `Cargo.lock` 只给 `W_CRATE_LOCK`；
- 有 registry 依赖时给 `W_CRATE_DEPS_UNVERIFIED`：本 skill **没有**把每个版本与 Horizon `Cargo.lock` 比对，那一步留给 `cargo fetch --locked` / `E_CRATE_DEPENDENCY`。

### `[compatibility].horizon_revision`

优先 `git -C <horizon-root> rev-parse HEAD`（只读 subprocess）。本机快照没有 `.git`，因此回退为 `snapshot:<sha256(native-hooks.json)[:12]>`：

- 声明值 != 解析值 → `E_REVISION_MISMATCH`（non-zero）；
- 回退时额外给 `W_REVISION_NOT_GIT`，报告写 `revision.verified = false`；
- `snapshot:` **不是 commit**，只能证明“同一份快照”。真实发布前必须换成上游 commit。

## 负例控制

每次运行都会：

1. 把 bundle 复制到 `work/m5/native/_negative/<bundle-name>/`（忽略 `target/`、`Cargo.lock`）；
2. 把第一个 `hook = "use_item"` 改成 `use_itme`；
3. 对副本跑同一套校验，要求退出码 `1` 且错误含 `E_HOOK_UNKNOWN`。

结果写进报告 `negative_control`：`ok`、`exit_code`、`codes`、`errors`、`mutation`。若正例本身无法解析（`E_TOML` 等），负例标 `skipped`，不会用一个无效输入去伪造“负例通过”。若负例没有失败，追加 `E_NEGATIVE_CONTROL` 并让本次运行失败。

## 报告形状

```json
{
  "status": "ok",
  "exit_code": 0,
  "checked": {"injections": 2, "helpers": 2, "crates": 1, "hooks_in_catalog": 434},
  "catalog": {"hooks": 434, "catalog_api": 1, "sha256": "..."},
  "revision": {"declared": "...", "resolved": "...", "source": "snapshot-catalog-sha256", "verified": false},
  "injections": [{"id": "...", "hook": "use_item", "hook_version": 1, "kind": "HEAD", "status": "ok"}],
  "crates": [{"id": "engine", "path": "engine", "dependencies": [], "status": "ok"}],
  "errors": [],
  "warnings": [{"code": "W_REVISION_NOT_GIT", "detail": "..."}],
  "negative_control": {"ok": true, "exit_code": 1, "codes": ["E_HOOK_UNKNOWN"]}
}
```

`catalog_api` = catalog 里所有 hook 的最大 `version`（本快照为 1）；不是 `NATIVE_HOOKS_API`（源码里是 415）。

## 没有验证的部分

- **不编译、不运行** helper：helper 的函数签名与 `bindings` 是否匹配 horizon-mixins 生成的 API，仍属未验证；
- registry 依赖未逐版本对 Horizon `Cargo.lock`；
- `horizon_revision` 在无 `.git` 的快照上只能做指纹一致性，不能证明等于上游 HEAD；
- 游戏内行为（开火、换弹、第一人称表现）完全未观测。
