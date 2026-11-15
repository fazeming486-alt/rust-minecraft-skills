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

## 7. M5d 尝试：被本机 IO 挡住

目标：① 用当前 bundle 重跑干净的 `apply → build`，消掉 M5c 的就地补丁欠账；② 让每次右键扣一发、空仓打不出。

**做到了**：`port-native-module` 的 `cargo test` 目录外置到 `work/m5/target-engine`（bundle 里不再出现 `target/`）；`on_use` helper 增加 30 发进程内弹匣（空仓不 claim 并打印）；另外准备了一个**无 `[[crate]]`** 的探针 bundle，用来绕开 `complete()`。

**没做到**：`horizon-mixins apply` 的 `complete()` 会把整个工作区复制到 `.horizon-mixins-lock-*` 再跑 `cargo update`；本机这一步退化到约 **2 秒/文件**（45 个文件耗 20 分钟，22 分钟后仍无 stage 输出）。随后的 `cargo build` 又遇到 rlib 被占用（`os error 5`），删掉重编 27 分钟仍未完成。同一条 apply 在 16:56 只要 140 秒——**是这台机器的 IO/安全扫描退化了，不是 bundle 不合法**（`plan` 仍 70 秒通过）。

因此 M5d **没有产生新的验证等级**：弹药逻辑只存在于生成器里，没有在游戏内观测；干净 `apply → build` 仍是欠账。详见 `reports/m5d-attempt.json`。

## 8. M5e：弹匣语义在真实进程里闭环

M5d 卡住的其实是**启动参数**，不是构建。把两处搞对之后，`--dedicated` 与无头客户端都能稳定跑起来：

- `--resources` 必须指向 `third_party/horizon/.local/horizon-client/26.3`（带 `horizon-resources.json`）。`minecraft-26.3/` 只是原版安装，报的是 `prepared game files are missing`。
- `eula.txt` / `server.properties` 读的是**进程 cwd**，`--universe` 不管这件事；要么用 `--game-dir` 明确指，要么在 cwd 写 `eula=true`。

复跑命令（153 s 完成加载，`content from 1 mod(s)`，items 1659）：

```
horizon-client.exe --resources <…>/.local/horizon-client/26.3 \
  --game-dir work/m5/ctl-home --home work/m5/ctl-home \
  --headless --control-socket work/m5/ctl-home/control.json \
  --dev-mod work/m5/tacz_ak47_pilot.hmod --quickPlaySingleplayer ak47probe
```

`horizon-ctl use-item` 连点 31 次的结果（`work/m5/ctl-home/_run7.log`，sha256 `9f29368…`）：

```
[ak47_probe] shot, ammo=29
…
[ak47_probe] shot, ammo=0
[ak47_probe] trigger on empty magazine
```

| 断言 | 观测 |
| --- | --- |
| 每次右键恰好一发 | 30 次点击 → 30 行 shot，ammo 29→0 |
| 空仓拒绝 | 第 31 次打印 empty，不再 shot |
| 只对自己的物品生效 | 切到 `minecraft:apple` 右键，日志无新增 |
| 空仓不自愈 | 之后两次点击仍是 empty |

> **`swings` 不能当 claim 计数器**（M5e 首版写错了，M5f 更正）：这一轮是「每次点击起一个 ctl 进程」的慢速点击，`state.swings` 恰好等于 30；M5f 里同一份二进制快速连点 31 次，发数仍是 30，`swings` 只有 15。它是带合并/衰减的挥手计数。**「空仓不 claim」是源码级事实**：helper 在 `left == 0` 时 `return`，早于 `*claimed = true`；对一个没有 vanilla use 的物品，运行期没有可分离的观测点。

**这不是真正的弹药**：`AMMO` 是 helper 里的 `static AtomicU32`，进程级、不是每玩家/每物品栈。`use_item` 只给 `&ItemStack`（不可变），写不回物品数据；换弹、子弹、命中、伤害都还没有。详见 `reports/m5e-ammo.json`。

### 干净 apply 的欠账消了（源码层）

用 `probe/ak47_probe` 这个带 `bindings` 的 bundle 从 pristine 重跑：

```
horizon-mixins apply --workspace work/m5/src --mods work/m5/probe --out work/m5/stage-probe
→ status: ok, 1 injection, 19 s（M5d 那次 22 分钟没输出，这次 19 秒；IO 恢复正常）
```

对照 `stage-probe` 与 `third_party/horizon` 里那份就地补丁：`native_use_item` 的注入块**逐 token 一致**，差异只有两处非语义的——mixins 丢掉了 helper 文件首行注释、没做 rustfmt（`fn on_use(…)` 参数被拆行）。整文件 3592 行差异全是 `use` 换行。

两条新的环境事实：`horizon-mixins` 需要 PATH 里有 cargo（否则 `E_METADATA`，61 s 退出）；一次 apply 曾崩在 `memory allocation of 131072 bytes failed`，同命令立即重试就过——属于瞬时分配失败，别为此改工作区。

**还没做**：没有用 `stage-probe` 重编（`CARGO_INCREMENTAL=0` 全量约 26 分钟），所以「同源同二进制」只有源码级证据；`stage-probe` 的 bundle 是 `crates=0`，**不含 engine 的 18 状态机**——状态机链接的证据仍只属于 M5b 那个二进制。一次 apply 出全量钩子（crate + on_load + on_tick + on_use）还没做。

## 9. M5f：一份二进制同时含状态机与开火

M5b 的 engine 链接、M5c/M5e 的扣弹，此前分属两个二进制。这一节把它们放进**同一份源码、同一次构建、同一个进程**：

| 步 | 命令 | 结果 |
|---|---|---|
| 生成 | `port-native-module/run.py --out work/m5/native-full/tacz_ak47_pilot` | 3 hook（`use_item` / `player_tick` / `server_tick`）+ 1 crate + 1 data；engine 13/13；无 `[compatibility]` |
| plan | `horizon-mixins plan … --mods work/m5/native-full` | `ok`，**8.95 s**，3 injections / 1 crate / 1 data |
| apply | `… apply --out work/m5/stage-full` | `ok`，**19.99 s**，`stage_changed` |
| build | `cargo build --profile fast -p horizon-client --offline`（`CARGO_INCREMENTAL=0`） | `ok`，**7m46s**，`target/fast/horizon-client.exe` 109,300,224 B |
| run | 无头客户端 + `--dev-mod tacz_ak47_pilot.hmod` | 48 s 进世界；`content from 1 mod(s)`；1659 items |

同一个进程里同时出现：

```
[tacz_ak47_pilot] load probe: first server tick, engine states=18
…
[tacz_ak47_pilot] shot, ammo=29
…
[tacz_ak47_pilot] shot, ammo=0
[tacz_ak47_pilot] trigger on empty magazine
```

31 次点击仍是 30 发 + 1 空仓；再点两次空仓 → empty 3、shot 仍 30；切苹果右键不触发。证据：`work/m5/ctl-home/_run8.log`，sha256 `a401f912…`。

### 两条新约束

- **stage 里的 `.local/` 是空壳**：apply 不复制 prepare 产物（`stage-full/.local` 0 个文件），`--resources` 指 stage 自己的 `.local` 会报 `prepared game files are missing`。要么指原 `third_party/horizon/.local/...`，要么重新 `horizon-prepare`。
- **本机后台 shell 会整个起不来**（sandbox 包装层 125：bash.exe / 插件 shim 文件读被拦），只能前台长命令 + 命令内脚本；游戏进程在命令结束后仍存活，可以接着用 `horizon-ctl` 驱动。

### 更正：`swings` 不是 claim 计数

同一份二进制里 31 次**快速**点击 → shot 30、`swings` 15；M5e 那次 30 次**慢速**点击 → shot 30、`swings` 30。`swings` 会合并/衰减，不能当判据。「空仓不 claim」现在只写成源码级事实（`left == 0` 直接 `return`，早于 `*claimed = true`），不再拿运行期计数冒充。

## 10. M5g：状态机接管弹匣（观测到一半）

M5f 的弹匣还是 helper 里的 `static AtomicU32`，18 个状态只被打印。这一节把弹药搬进 engine：

- `engine/src/runtime.rs`：`Mutex<Option<GunState>>` 进程级共享槽 + `with_gun()`。**必须放在 engine 里**——`on_use` 与 `on_tick` 是两个注入函数，各自写 `static` 会是两份状态。
- `GunState::release()`：点击后清锁存但不走 `tick`，否则一次点击要多吃一个 tick 的冷却，射速会被算快。
- `on_use`：一次右键 = `tick(Some(Shoot))` + `release()`；按 `Event::Shot` 决定 claim，`DryFire` 报干火，其余报 `blocked` 并带前后状态/冷却/是否换弹。
- `on_tick`：每 tick `tick(None)` 推进冷却与换弹计时。

```
[tacz_ak47_pilot] load probe: first server tick, engine states=18 ammo=30 state=main.idle
…
[tacz_ak47_pilot] shot, ammo=7
```

23 次成功点击把 ammo 从 30 打到 7，数字来自 `GunState`，不再是 helper 的常量。engine 单测 13 → **14/14**（新增 `one_state_across_calls`）。

### 没观测到的，以及为什么

| 项 | 状态 | 原因 |
|---|---|---|
| 射速门控（`FIRE_INTERVAL_TICKS=2`，100 ms） | `not_observed` | `horizon-ctl` 一次 `use-item` 往返实测 **161 ms**（10 次 1611 ms），串行点击永远跨过 3 个 tick，冷却必已归零 |
| 并发压点击 | `not_observed` | 18 个并发 `use-item` 只有 3 次真正到达游戏，其余在 socket 竞争里丢了 |
| `--hold 0.5` | `not_observed` | 只产生 3 次 use 调用，不是每 tick 调用 |
| 干火 | `not_observed` | 打到 ammo=7 时无头客户端进程消失（无 crash report），没打空 |

结论：**代码与单测在，游戏内证据只到「ammo 由状态机持有并递减」**。要验射速，得换驱动方式（批量/脚本通道，或一个 hold 期间每 tick 重放 use 的测试钩子），这是 M5h 的前置。

## 11. M5h：全自动交给 player_tick（观测到了，速率是标称的 2 倍）

M5g 卡在「输入侧最密 4 tick 一次，压不到 2 tick 冷却」。换思路：**`use_item` 只扣扳机，开火交给 `player_tick`**。

- engine：新增 `pull_trigger() -> Pull`，按需开火**不推进冷却**（`use_item` 的到达频率由游戏决定，不能顺带当时钟）。
- engine 修正：`fire()` 里 `cooldown_ticks` 存 `FIRE_INTERVAL_TICKS-1`。原先存 interval 本身，而 `tick` 是「先减后判」，2 tick 的间隔实际要 3 tick 才发一发——这是引擎自己的 off-by-one。
- runtime：`HOLD_GAP_TICKS=5` 判断「按住」（两次 use 相隔 <5 tick）；`HOLD_TIMEOUT_TICKS=6` 在停止重复后松扳机（`use_item` 没有 release 事件，只能靠重复调用推断）。

游戏内（`_run15.log`，sha256 `14685cf…`）：

| 动作 | 观测 |
|---|---|
| 单击 + 等 10 tick | **恰好 1 发**，没有后续 `auto` 行 |
| 按住 20 tick + 松开等 10 tick | 累计 **24 发**，全部是 `auto, ammo=` |
| 按住 40 tick（`_run13`） | 30 发打空（27 auto + 3 press），出现 dry fire |
| 同枪在 M5g 版本按住 40 tick（`_run11`） | 只有 11 发——那时节奏是游戏自己的 4-tick 重复 |

**新的偏差**：24 发落在 20+6(tail)=26 tick 的窗口里，约 **1 发/tick（20/s）**，是 `FIRE_INTERVAL_TICKS=2`（10/s）的两倍。最可能是 `player_tick` 在单机里每 tick 被调用两次（客户端 + 服务端线程各一次），把 2-tick 冷却走成 1 tick。**这条没有实测确认**——下次构建要在 `on_tick` 里累加调用计数并对齐 `wait 20` 才能定论。

**顺带更正 M5g 的日志缺陷**：那时自动射击根本没打印，日志只有 7 行 `shot`，而弹匣从 30 掉到 3。现在 `on_tick` 打印 `auto, ammo=N`，发数与弹匣变化对得上。

## 12. 边界与下一步

- **接线已验证，弹药与全自动都已进状态机，但仍不是「真的枪」**：单击一发、按住连发、空仓拒绝都在真实右键里成立；子弹实体、命中、伤害、音效、换弹全都没有。
- **速率还没对上标称**：engine 的 2-tick 间隔有单测，但游戏内观测到约 1 发/tick，疑似 `player_tick` 每 tick 被调用两次。
- **弹药是进程级共享量**：不是物品 NBT，也不 per-player；多人会串。
- **动画仍 `unbound`**：IR 里的 44 条转移只是状态层，73 个 animation.json 与骨骼插值在 Horizon 侧仍无消费者。
- **期望值不是 oracle**：来自 TaCZ 的 `ak47_data.json`，不是真机录制；M3b 仍未做。

下一步，按依赖排序：① 给 `on_tick` 加调用计数探针，确认 calls/tick 后把冷却折算对；② 接换弹输入（52 tick 空仓 / 40 tick 战术），验状态转移；③ `player_tick` 补玩家绑定做每玩家 `GunState`；④ 弹药落物品栈；⑤ 子弹 + 命中 + 伤害。

在那之前，「AK-47 已经搬过来」仍不成立——现在可以说的是：**物品能注册、右键能进我们的代码、单击一发、按住全自动、弹药与节奏都由 18 状态的状态机持有；枪还不会打子弹**。

