# 08 · M5 执行报告：AK-47 单枪竖切

> 状态：v0.9（2026-11-15）。M5 第一次产出**能被目标侧工具接受**的东西：一个官方校验通过的 `.hmod`、一个 `cargo test` 全绿的纯 Rust engine、一份逐 tick 对得上的行为差分；M5b 把它**真的编进 Horizon 并跑起来**；M5c 让真实玩家右键**命中我们的 `use_item`**（4/4）。仍然没有子弹——弹药状态还没接，这条边界写在每一份报告里。

## 1. 这一步到底证明了什么

| 层 | 产物 | 证据 | 等级 |
|---|---|---|---|
| 内容 | `work/m5/tacz_ak47_pilot.hmod`（6227 B） | `cargo-horizon-mod check --kind mod --json` → `ok: true` | `verified_by_official_tool` |
| 状态机 | `work/m5/state-ir/ak47.json` | 18 状态 / 44 转移 / 8 守卫 / 22 输入，schema 通过、幂等 | `verified_by_schema` |
| 逻辑 | `work/m5/native/tacz_ak47_pilot/engine` | `cargo test --offline` 13/13，纯 std、零依赖 | `verified_by_test` |
| 接线 | `horizon-mixin.toml`（2 个注入点） | 与 `native-hooks.json` 目录逐条对上，负例报 `E_HOOK_UNKNOWN` | `source_only` |
| 行为 | `reports/m5-diff.json` | 200 tick 剧本 23/23 事件匹配、drift 0；负例失败 | `verified_by_test` |
| 编译加载 | `reports/m5b-native-build.json` | 编进 `horizon-client`，无头服务端首 tick 打出 `load probe … engine states=18` | `compiled_and_loaded` |
| 开火路径 | `reports/m5c-firing.json` | 无头玩家 4 次右键，4 次命中 `native_use_item`，helper 拿到 `(game, stack, claimed)` | `fired_in_game` |

**没证明**：物品在游戏里出现、开火被真正调用、第一人称表现、动画、网络同步、伤害结算。`bindings = []`，右键触发没有玩家可测。

## 2. 五步链路

### 2.1 Lua 状态机 → IR（`translate-lua-statemachine`）

输入是 TaCZ 的 `ak47_state_machine.lua` 与它 `require` 的 `tacz_default_state_machine_v2.lua`。解析器是自己写的 Lua 子集解析器（不是正则、不跑 Lua），展开 `setmetatable` 继承后得到：

- 18 个状态：`main.{start,idle,inspect}`、`bolt.{normal,bolt_caught}`、`ads.{normal,aiming}`、`movement.{idle,walk,run}`、`slide.{normal,slide}`、`fire_mode.{draw,semi,auto}`、`gun_kick`、`base_track`、`final`；其中 `origin=base` 13 个、`origin=gun` 5 个。
- 44 条转移、22 个被实际引用的输入、8 个守卫。
- 26 条 `unresolved`：`INPUT_*` / `SEMI` / `AUTO` 这类运行时注入常量只保留符号名，静态拿不到数值——**显式记录，不猜**。
- 覆盖率：53 个 `*state_machine*.lua` 全部做过语法级解析（failed = 0），只有 AK-47 与基类做了完整展开，其余 51 个如实标 `not_flattened`。

三轮才收敛的问题（都写进了报告）：

1. `transitions[].on` 一开始全是 `"*"`，输入藏在 guard 的 `(input == INPUT_RELOAD)` 里 → 改为 `on` 直接取输入名，guard 只留剩余条件。
2. 基类与子类叠加导致重复转移（51 → 44）→ 按 `(on, guard, target, animations)` 去重，保留 `origin=gun`。
3. 剩下 2 条 `on="*"` 是 `slide` 的**每 tick 条件驱动**转移（守卫 `should_slide() && ...`），不是委托 → 保留，并在 schema 里把 `*` 定义为「guard 非空的条件驱动」。

`schema` 也补了一条：`*` 只允许出现在 guard 非空时，无条件通配是非法的。

### 2.2 内容包（`build-content-mod`）

产物结构（6 个文件）：

```
horizon-mod.toml                      api="0.2" side="both" capabilities=["registries"]
data/tacz_ak47_pilot/horizon/item/ak47.json      template=minecraft:crossbow, max_stack_size=1
assets/tacz_ak47_pilot/items/ak47.json           26.3 的 items 定义
assets/tacz_ak47_pilot/models/item/ak47.json     parent=item/generated, layer0
assets/tacz_ak47_pilot/textures/item/ak47.png    从 TaCZ slot 贴图逐字节拷入 work/
assets/tacz_ak47_pilot/lang/en_us.json
```

两次 `build` 的 SHA-256 完全一致（`1f5b4b50…`），说明官方打包器在这个输入上是确定性的。

**实测纠正**：任务原稿把 `minecraft:max_stack_size` 放进 `components`，官方 `check` 直接拒绝并提示 `set max_stack_size instead`。改成顶层字段后通过。这不是我们放宽了校验，是按目标侧的真实约束改的。

负例：删掉 item 的 `template` 后，官方 `build` 报 `missing field template` 并退出 1。校验器是有效的。

### 2.3 原生模块（`port-native-module`）

```
work/m5/native/tacz_ak47_pilot/
  horizon-mixin.toml        [[injection]] use_item(v1) / player_tick(v1)，bindings=[]
  on_use.rs / on_tick.rs    helper 占位，调用 engine
  data/ak47.json            数值快照
  engine/                   纯 std crate：状态机 + consts + states + trace bin + 13 个测试
```

engine 的 18 个状态 id 与 IR **集合相等**（不是数量相等），改名即非零退出。`cargo test --offline` 13/13，覆盖连发 30 发空仓、半自动需松扳机、战术换弹 40 tick、换弹中不能开火、切模式。

### 2.4 注入点预检（`verify-hook-catalog`）

解析 `horizon-mixin.toml`（自带 TOML 子集解析器），逐条对照 `native-hooks.json`：2 个注入点、2 个 helper、1 个 crate，434 个 hook 的目录里全部命中，`errors = []`。

负例把 `use_item` 改成 `use_itme`：立即返回 `E_HOOK_UNKNOWN`，并给出最接近的 3 个候选（`use_item` / `use_item_on` / `use_animation`）。这把原本要等 12 分钟游戏构建才会暴露的错误提前到了秒级。

一个环境事实：本机的 `third_party/horizon` **不是 git checkout（没有 `.git`）**，所以 `horizon_revision` 无法用 commit；预检改用 `native-hooks.json` 的内容指纹 `snapshot:d709ee26dc82`，并在报告里明确「这只证明同一份快照，不等于上游 HEAD」。

### 2.5 行为差分（`playable-diff-harness`）

200 tick 剧本：连发 10 发（600 rpm → 每 2 tick 一发）→ 战术换弹（2.0 s → 40 tick）→ 5 发 → 切 semi → 单发 3 次 → 再换弹。

结果：**23/23 事件匹配，max drift = 0**，`ammo_after` 逐发相等；状态集合相等；把期望弹匣改成 29 的负例在第一个 `Shot` 上就被抓住。产出同时写了官方形状的 `harness/result.json`，`report.rs` 可以消费。

## 3. 五个 skill 与派发

| 任务 | skill | 角色 | 结果 |
|---|---|---|---|
| m5-01 | `translate-lua-statemachine` | state-machine-translator | COMPLETE（3 轮修正） |
| m5-02 | `build-content-mod` | content-mod-packager | COMPLETE |
| m5-03 | `port-native-module` | native-port-engineer | COMPLETE |
| m5-04 | `verify-hook-catalog` | hook-catalog-verifier | COMPLETE |
| m5-05 | `playable-diff-harness` | slice-harness-runner | COMPLETE |

复杂度评估：`score 0.4456 / band M / 2 workers`，硬门槛 2（`animation_driver` 缺口、`local-only`）。5 个任务包 / 3 个 wave（`work/dispatch/m5/index.json`）。

分工方式沿用 ADR 0007：3 个子 agent 各领 1–2 个任务、自己跑命令、自己写 result；主 agent 只做契约、语义复核与汇总。**语义复核确实抓到了东西**：`on="*"`、重复转移、`inputs` 集合不匹配三处都是主 agent 读 IR 时发现的，`collect-results` 的哈希与越界扫描查不出来。

## 4. 复现

```bash
# 1. 状态机 IR
python skills/05-port/translate-lua-statemachine/run.py --slice orchestration/m5-slice.json \
  --out work/m5/state-ir/ak47.json --report reports/m5-state-ir.json

# 2. 内容包（官方工具需先 cargo build -p cargo-horizon-mod --offline）
python skills/05-port/build-content-mod/run.py --slice orchestration/m5-slice.json \
  --official-tool third_party/horizon/target/debug/cargo-horizon-mod.exe \
  --report reports/m5-content-mod.json

# 3. 原生 bundle（含 cargo test）
python skills/05-port/port-native-module/run.py --slice orchestration/m5-slice.json \
  --ir work/m5/state-ir/ak47.json --out work/m5/native/tacz_ak47_pilot \
  --report reports/m5-native-module.json --cargo D:/RUST重写mc项目/dev/cargo/bin/cargo.exe

# 4. 注入点预检
python skills/05-port/verify-hook-catalog/run.py --bundle work/m5/native/tacz_ak47_pilot \
  --catalog third_party/horizon/native-hooks.json --horizon-root third_party/horizon \
  --report reports/m5-hook-catalog.json

# 5. 差分
python skills/09-verify/playable-diff-harness/run.py --slice orchestration/m5-slice.json \
  --ir work/m5/state-ir/ak47.json --engine work/m5/native/tacz_ak47_pilot/engine \
  --cargo D:/RUST重写mc项目/dev/cargo/bin/cargo.exe --report reports/m5-diff.json
```

## 5. M5b：真的编进游戏并跑起来

M5 收尾后立刻做了 M5b——不满足于「源码看起来对」。四步全部真跑：

| 步 | 工具 | 结果 |
|---|---|---|
| 目录预检 | `horizon-mixins plan` | `status: ok`，3 injections / 1 crate / 1 data，70.8 s |
| 应用补丁 | `horizon-mixins apply` | `stage_changed: true`，110.2 s；workspace 加成员、客户端加依赖、3 处调用注入 |
| 编译 | `cargo build --profile fast -p horizon-client --offline` | **成功**，7 min 10 s |
| 运行 | `horizon-client --dedicated --nogui` | 服务端 48.4 s 启动完成，首 tick 打出探针 |

探针不是摆设：bundle 里加了一个 `server_tick` 注入，只在第一次 tick 打印一行：

```
[tacz_ak47_pilot] load probe: first server tick, engine states=18
```

这一行同时证明三件事：bundle 被编进游戏、钩子点真的被调用、`ak47_engine` 被链接且 18 个状态在运行时可见。

### 路上撞到的四条硬约束（都回写进了 skill）

| 错误 | 规则 | 修法 |
|---|---|---|
| `E_CRATE` | bundle 的 crate 不能带 `Cargo.lock` | 生成器在 `cargo test` 后清掉 `target/` 与 `Cargo.lock` |
| `E_REVISION` | 快照没有 `.git` 时，任何 `snapshot:` 值都被拒 | 无 git 时**省略** `[compatibility]`，不钉版本；指纹只写进报告 |
| `E_INVALID_HELPER` | helper 必须恰好一个**私有**函数，且不能有文件级属性 | `pub fn` → `fn`；`//!` → `//`（`//!` 会变成 `file.attrs`） |
| `E0425` | `STATES` 在 `states` 模块而不是 crate 根 | 探针改用 `ak47_engine::states::STATES` |

`verify-hook-catalog` 已把前三条做成编译前检查（`E_CRATE_ARTIFACT` / `E_REVISION_INVALID` / `E_INVALID_HELPER`），下次不用等 `apply` 才发现。

### 三条环境修复（中文路径 + 安全策略）

- `CFLAGS=/utf-8`、`CXXFLAGS=/utf-8`：MSVC 才能读中文路径，否则 `cl.exe` 报 C1083；
- `MSYS_NO_PATHCONV=1`：否则 Git Bash 把 `/utf-8` 转成本机路径（实测 `CL=/utf-8` 会被转坏）；
- `RC_PATH=<Windows SDK>/rc.exe`：构建脚本查注册表被安全策略拦（`reg.exe` 在黑名单），资源编译找不到 `rc.exe`。

### 副作用与恢复

`third_party/horizon` 现在**已是被打过补丁的树**（含 `native-crates/` 与三处注入）。原始副本在 `work/m5/src`；再次 `plan/apply` 前必须从它恢复，否则 mixins 会报 `E_INVALID_PATH`（workspace 里已存在 staging 路径）。

### M5b 仍然没有证明什么

- **没有开火**：无头服务端没有玩家，`use_item` 触发不了；`bindings = []` 也拿不到物品栈。
- **没有第一人称**：渲染、后坐、换弹动作需要可观测客户端。
- **动画仍 unbound**：`animation_driver` 的缺口没有被 M5b 触碰。
- 探针证明的是「钩子被调用」，不是「弹道/伤害/同步正确」。

## 6. M5c：真实绑定与开火路径贯通

M5b 只证明「钩子被调用」，helper 还是空参。M5c 把 `bindings` 换成真实三元组，并让一个真实玩家在真实进程里右键：

```toml
bindings = [
  { name = "game",    ty = "&mut crate::game::Game<'_>",     value = "&mut *self" },
  { name = "stack",   ty = "&crate::items::ItemStack",        value = "stack" },
  { name = "claimed", ty = "&mut bool",                        value = "&mut *claimed" },
]
```

helper 只认自己的物品并把使用 claim 掉：

```rust
fn on_use(game: &mut crate::game::Game<'_>, stack: &crate::items::ItemStack, claimed: &mut bool) {
    let _ = game;
    if &*stack.item != "tacz_ak47_pilot:ak47" { return; }
    *claimed = true;
    eprintln!("[tacz_ak47_pilot] use_item claimed: {}", stack.item);
}
```

测试路径（全部 headless，无窗口）：`horizon-client --headless --control-socket … --dev-mod tacz_ak47_pilot.hmod` → `horizon-ctl give` → `horizon-ctl use-item` ×4。

结果：**4 次点击，4 行 claim**，一次一枪，与文档「Each click reaches it once」一致：

```
[tacz_ak47_pilot] load probe: first server tick, engine states=18
[17:30:47] [Server thread/INFO]: Player09064 logged in with entity id 1
[tacz_ak47_pilot] use_item claimed: tacz_ak47_pilot:ak47   ×4
```

### 又一条实测约束

`minecraft:custom_data` **不是 26.3 的已知组件类型**。把它写进 item 的 `components` 会让整个内容包拒绝加载：

```
mod tacz_ak47_pilot content not loaded: tacz_ak47_pilot:ak47: minecraft:custom_data is not a known component type
```

`build-content-mod` 已改为不写任何 `components`，身份用 `stack.item` 判断；并加 `item_no_unknown_components` 检查。注意：官方 `cargo-horizon-mod check` **当时是 ok 的**——静态校验过不代表游戏内注册成立，这条只有真机能发现。

### 这次没做到的（重要）

- **没有弹药**：`use_item` 只给 `&ItemStack`，写不了组件；要改走可变背包钩子或玩家状态存储。
- **没有子弹、伤害、音效**：claim 之后什么都没发生，只是把原版弩的行为挡住了。
- **没有第一人称表现**：headless 无窗口；动画仍 `unbound`。
- 最终注入块是**就地补丁**写进 `native_hooks.rs` 的：上一次 `apply` 用了过期的 `mods.incoming`（缺 bindings），发现后按 mixins 同形代码替换并重编。**干净的 apply → build 尚未重跑**，这是明确的复现欠账。

## 7. 边界与下一步

- **接线已验证，但只到 claim**：`(game, stack, claimed)` 在真实右键里命中；弹药、子弹、伤害都还没有。
- **行为只覆盖 C1**：engine 的射速/弹匣/换弹在单测与 trace 里成立，但**没有接进游戏**——游戏内的 `GunState` 还没被任何地方持有。
- **动画仍 `unbound`**：IR 里的 44 条转移只是状态层，73 个 animation.json 与骨骼插值在 Horizon 侧仍无消费者。
- **期望值不是 oracle**：来自 TaCZ 的 `ak47_data.json`，不是真机录制；M3b 仍未做。

下一步（M5d）三件事，按依赖排序：① 用当前 bundle 重跑一次干净的 `apply → build`，消掉就地补丁欠账；② 把弹药状态放到可变钩子（背包/玩家存储），让每次 claim 扣一发、空仓打不出；③ 用 `horizon-ctl` 的 `state.inventory` 与 `events` 做断言，而不是只看日志。

在那之前，「AK-47 已经搬过来」仍不成立——现在可以说的是：**物品能注册、右键能进我们的代码、逻辑单元对得上；枪还不会打子弹**。
