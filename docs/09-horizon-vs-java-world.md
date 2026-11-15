# 09 · Horizon 与原版 Java（26.3）在世界与生物上的差异

> 范围：生物（种类、AI/寻路、生成、掉落、刷怪笼、村民交易、Boss）与世界（地形、群系、结构、光照、红石、流体、方块更新/随机 tick、天气）+ 存档/多人。
> 对象：`third_party/horizon`（本机检出，目标版本 **Minecraft Java 26.3**，DataVersion 5023，protocol 777 —— `crates/horizon-core/src/version.rs:1-15`）。

## 0. 怎么读这份文档

置信度三级：

| 等级 | 含义 |
|---|---|
| **源码实证** | 我读过 Horizon 的 Rust 源码，能给出 `路径:行号` |
| **官方文档** | Horizon 仓库内的文档/README/ROADMAP 或 playhorizon.dev 的自述，未逐行回源码 |
| **社区说法** | 第三方站点/新闻/论坛，未证实，只作旁证 |

**必须注意的一件事：Horizon 自己的 `docs/` 里有相当一部分"已知缺口"已经过时。** 我对每条能核对的都回了源码，至少四处已修复但文档仍写着"未实现"：

- `docs/parity/blocks.md:179-180` 说"未实现：sculk 振动系统、creaking hearts、闪电（`tickThunder`）" —— 实际 `crates/horizon-client/src/game/sculk.rs`、`game/block_entity_ticks.rs:75`（`tick_creaking_heart`）、`game/lightning.rs:72`（`fn tick_thunder`）都存在。
- `docs/parity/blocks.md:182` 说"未存档：点燃的 TNT、漏斗冷却" —— 实际 TNT 的 `fuse` 会写进 NBT（`crates/horizon-client/src/entity_nbt.rs:2837-2865`），漏斗的 `TransferCooldown` 会读写（`crates/horizon-client/src/game/machines.rs:49-58`）。
- `docs/parity/blocks.md:170-176` 说"发射器没有刷怪蛋行为、船/矿车/投掷物不是实体" —— 实际发射器有 `dispense_spawn_egg`（`crates/horizon-client/src/game/dispenser.rs:720,1095-1120`），船与矿车也各有实现（`game/boats.rs`、`game/minecarts.rs`）。
- `docs/parity/blocks.md:175-176` 说"海龟幼崽不生成" —— 实际 `hatch_turtles` 存在（`crates/horizon-client/src/game/creatures.rs:3681-3684`）。

所以下文凡是标"官方文档"的，都是我没有回源码逐行确认的；标"源码实证"的可以放心引用。

**第二件必须注意的事：`native-hooks.json` 只是索引，不能当契约读。** 它的 `contract`（`listen`/`cancel`/`collect`）与 `cancellable` 字段至少两处与源码不符：`explosion_knockback` 标 `collect`，实际签名是 `knockback_velocity: &mut [f64; 3]`（`crates/horizon-client/src/game/native_hooks.rs:8534-8540`）；`item_damaged` 标 `cancel`，实际是 `amount: &mut i32, cancel: &mut bool`（`native_hooks.rs:9238-9245`，由 horizon-combat-research 发现，我已核对）。本文只在两类地方用它：**hook 名称的有无**（例如"没有 `worldgen`/`structure`/`goal`/`path` 命名的 hook"）和**数量统计**；凡是涉及可变性/能否取消的判断，一律以 `native_hooks.rs` 的签名为准。

## 1. 一页结论

1. **"有没有"基本不是问题，"留下没做"才是问题。** 生物种类、AI、刷怪、交易、Boss、地形、群系、结构、光照、红石、流体、天气都有真实实现（`mobs.rs` + `mobs/` 共 111,984 行，`worldgen/` 顶层 33,046 行，`game/` 下 542 个条目），差异集中在少数被明确标注的留白上，其中影响最大的是：数据包新增的**生物群系会被直接丢弃**（`worldgen/overrides.rs:228-241`）。
2. **世界生成的残差出在装饰顺序，不在噪声/地形。** 地形、群系、结构起点几乎逐块一致（`docs/parity/world-compare.md:43-53`），但树和植被的命中率低于 vanilla 与自身对比的下限（橡木原木 52.7% vs vanilla 自比 59.7%，`world-compare.md:55-64`）。
3. **跨维度实体搬运是硬缺口。** 服务器上生物/掉落物/矿车走进传送门不会被送到另一维度（`docs/server-levels.md:99-100`），且不带距离/体积的 `@e` 只读当前维度（`server-levels.md:101-102`）。这会直接打死一批依赖门户/跨维度选择器的机器。
4. **红石能逐 tick 对齐，但只对齐"方块"。** 144 组随机电路 40 tick 完全一致（`docs/parity/redstone-diff.md:33-37`），而对比工具本身只比对方块状态，物品实体、TNT、下落方块不在比对范围（`redstone-diff.md:39-43`）。
5. **存档格式对齐，但维度高度模型不同。** NBT/region/palette/DataFixer 与 vanilla 对齐，1.8→26.2 的存档可升级（`docs/world-data.md:69`）；但 Nether/End 仍按主世界 `-64..320` 的 24 段列宽存储，vanilla 是 16 段（`docs/world-height.md:66-72`）。
6. **最大的"不一样"是模组边界，而不是原版内容。** Java jar 完全不运行（`README.md:88`）；`native-hooks.json` 里 434 个 hook 中，`worldgen`/`structure` 相关 0 个、`goal`/`path`/`brain` 相关 0 个、`redstone` 相关 0 个。世界生成只能走数据包 JSON，不能走代码。

## 2. 对照表

### 2.1 生物

| 领域 | Java 版行为 | Horizon 行为 | 证据 | 置信度 |
|---|---|---|---|---|
| 生物种类覆盖 | 26.3 的全部实体类型 | `Species` 枚举 93 项，含 26.3 新增的 `CopperGolem`、`Creaking`、`HappyGhast`、`Bogged`、`Parched`、`CamelHusk`、`Nautilus`、`ZombieNautilus`、`SulfurCube`、`Mannequin`；末影龙不在 `Species` 中，单独走 `game/dragon.rs` | `crates/horizon-client/src/mobs/species.rs:7-98`；`game/dragon.rs` | 源码实证 |
| 生物 AI（goal 选择器） | `GoalSelector` 的优先级、MOVE/LOOK/JUMP/TARGET 控制位、可中断语义 | 同语义移植：`MOVE/LOOK/JUMP/TARGET` 常量与 `Goal` trait 的 `can_use/can_continue/interruptable/start/stop/tick` 一一对应；`mob_ai` harness 92 个场景通过（README 自述） | `crates/horizon-client/src/mobs/goals.rs:1-56`；`README.md:161` | 源码实证（结构）+ 官方文档（通过率） |
| 已知 AI 失败项 | — | `docs/architecture.md` 记录 `mob_ai` 在 main 上有 `drowned_*` 已知失败（issue #290） | `docs/architecture.md:43` | 官方文档（2026-10-23 审计，之后是否修复未证实） |
| AI 主循环 | `Mob.aiStep`/`serverAiStep`、brain（村民/猪灵/监守者） | `mobs/ai.rs` 6,220 行 + `brain.rs` 262 行 + `villager_brain.rs` 4,607 行 + `warden_brain.rs` 1,543 行 | 同左 | 源码实证（规模） |
| 寻路 | `PathNavigation`、`Path`、A* 与游泳/飞行/地面三类导航 | `mobs/path.rs` 1,618 行 + `nav.rs` 868 行 + `NavKind`；harness `mob_ai`、`mob_rider_navigation` | `mobs/path.rs`、`mobs/nav.rs` | 源码实证（存在）/ 未证实（逐节点等价） |
| 自然生成 | `NaturalSpawner`：spawn potential 电荷、全局 mob cap、`LocalMobCapCalculator`、结构生成覆盖 | 同模型：spawn 电荷、全局/本地 cap、结构覆盖都有；`natural_spawn` harness 15,500 例，覆盖主世界/下界/末地、洞穴、水/岩浆、方块光/天空光、昼夜雷雨、peaceful→hard、结构覆盖（要塞/沼泽小屋/海底神殿/前哨站/试炼厅） | `crates/horizon-client/src/mobs/spawn_selection.rs:863,970-973`；`tools/test_natural_spawn_parity.py:1-25`；`README.md:161` | 源码实证 + 官方文档 |
| 生成规则 | `SpawnPlacements`、`MobSpawnSettings`、光照/方块/高度谓词 | `mobs/spawn_rules.rs` 752 行，`Reason` 枚举、`CustomSpawnRules::isValidPosition` | `crates/horizon-client/src/mobs/spawn_rules.rs` | 源码实证 |
| 刷怪笼 | `BaseSpawner`/`SpawnerBlockEntity`：延迟、玩家距离、`SpawnData`、`custom_spawn_rules`、装备、火焰音效 | 同状态机，客户端自旋与服务器状态分离；`mobs/spawner.rs` 846 行 | `crates/horizon-client/src/mobs/spawner.rs:1-25` | 源码实证 |
| 试炼刷怪笼 | `TrialSpawner`：波次、奖励、`vault` | `mobs/trial_spawner.rs` 1,256 行；harness `trial_spawner` | 同左 | 源码实证 |
| 掉落 | `EntityType` 战利品表、`LivingEntity.dropAllDeathLoot` | `mobs/drops.rs` + `loot` 模块；harness `entity_death_loot` | `crates/horizon-client/src/mobs/drops.rs` | 源码实证 |
| 村民交易 | `MerchantOffer`：价格/需求/库存、声望与英雄折扣、交易 XP、升级解锁 | `merchant.rs` 实现 `MerchantOffer.updateDemand`、`take`、`update_special_prices`（声望/英雄）、`getRecipeFor`；`villager.rs` 在换职业时把 `offers` 置空重掷 | `crates/horizon-client/src/merchant.rs:107,147-231,285-296`；`mobs/villager.rs:335-341,1405-1439` | 源码实证 |
| 村民行为 | 日程/工作站点/繁殖/农田/ gossip | `villager_brain.rs` 4,607 行；`gossip.rs` 394 行；harness `villager_farming`、`villager_witness`、`trading`、`merchant_gate`、`merchant_crafted` | 同左 | 源码实证 |
| Boss：末影龙 | `EnderDragon`：阶段、水晶治疗、 perch、龙息、末地 podium | `game/dragon.rs` 5,844 行；harness `server_dragon`、`dragon_contacts`、`dragon_death_roar`、`end_podium`、`forced_end` | 同左；`README.md:161` | 源码实证 + 官方文档 |
| Boss：凋灵 | `WitherBoss`：11 秒无敌充能、三头骷髅、半血以下破方块、免疫箭 | `mobs/wither.rs` 839 行 + `game/wither.rs` 349 行；**只有 `wither_wind_charge` 这一个专门 harness，没有整场对比** | 同左 | 源码实证（实现）/ 未证实（无整场 parity） |
| 袭击 | `Raid`：波次、村民英雄、袭击者庆祝 | `raid.rs` 1,741 行；harness `raid`、`raid_village`、`raider_celebration`，README 记 1,900 例 | `README.md:161` | 源码实证 + 官方文档 |
| 跨维度实体传送 | 生物/掉落物/矿车过传送门会被 `TeleportTransition` 送到另一维度，并建 portal ticket | **未处理**：只有玩家走 `server_travel.rs`，实体与 `PLACE_PORTAL_TICKET` 没有 | `docs/server-levels.md:97-100` | 官方文档 |
| `@e` 目标选择器 | 不带距离/体积时读取所有维度 | 只读命令源所在维度 | `docs/server-levels.md:101-102` | 官方文档 |

### 2.2 世界

| 领域 | Java 版行为 | Horizon 行为 | 证据 | 置信度 |
|---|---|---|---|---|
| 版本目标 | — | 固定 26.3（protocol 777、DataVersion 5023、资源包格式 97.1、数据包 121.0） | `crates/horizon-core/src/version.rs:1-20` | 源码实证 |
| 地形生成 | noise/density/aquifer/surface/carver/feature 全阶段 | 逐阶段移植，顺序与 vanilla 一致；`generator*.rs`、`router.rs`、`terrain.rs`、`aquifer/`、`material_*`、`carver/` | `docs/world-generation.md:1-7` | 官方文档 |
| 整区块一致性 | — | 2,352 个整区块 / 225 个结构站点 / 三维度一致；seed 12345 上 372 区块中 4 个有差异（3 方块 + 1 方块实体） | `README.md:159`；`docs/world-generation.md:62-63` | 官方文档 |
| 残留差异 | — | 结构件附近少量单方块（废弃营地、沉船、村庄）仍需逐 feature 追踪；树只经 `test_tree_feature_parity`（8,898 fixtures）验证 | `docs/world-generation.md:69-70` | 官方文档 |
| 装饰顺序 | 单 `worldgen` executor，按 chunk scheduler 的 tick 顺序装饰，跨区块写邻居 | `worldgen/decoration_order.rs` 420 行复刻该调度器；21 个站点 / 3,549 区块 0 差异 | `docs/world-generation.md:44-60` | 官方文档 |
| 树/植被密度 | vanilla 两次运行的橡木原木重合 59.7%，树叶 62.7% | 橡木原木 52.7%、树叶 56.0%；深色橡木 52.5% vs vanilla 自比 69.0% —— **低于 vanilla 自比下限** | `docs/parity/world-compare.md:55-64` | 官方文档 |
| 生物群系 | 多噪声源 + 气候点 | 1457/1457 区块群系一致；结构起点 13/13、21/21 | `docs/parity/world-compare.md:44-45` | 官方文档 |
| 数据包新增群系 | 新群系注册后可用（地形、颜色、音效全生效） | **直接丢弃**：日志写 `biome {id} is new: Horizon cannot add biomes yet, so it is left out`，并把它在 tag 与其他群系气候点里的引用一并剔除 | `crates/horizon-world/src/worldgen/overrides.rs:228-241`；`docs/world-generation.md:30-31` | 源码实证 |
| 结构 | 全部结构类型（村庄/要塞/古城/试炼厅/堡垒/末地城/林地府邸/海底神殿/矿井…） | `worldgen/structure/` 23 个模块：`jigsaw`（村庄/古城/试炼厅/堡垒）、`stronghold`、`mineshaft`、`mansion`、`monument`、`fortress`、`end_city`、`ocean_ruin`、`ruined_portal`、`temple`、`nether_fossil`、`legacy`… | `crates/horizon-world/src/worldgen/structure/` | 源码实证 |
| 模组结构地形适配 | vanilla 无此概念（靠 YUNG's API 的 Beardifier mixin） | Horizon 原生支持 `horizon:enhanced_terrain_adaptation`（YUNG's API / MoogsStructureLib 的 Beardifier 语义） | `crates/horizon-world/src/worldgen/structure/enhanced_terrain.rs:1-6` | 源码实证 |
| 光照 | 方块光 + 天空光、一次向上一段扩散 | 保存的光与重算的光都对齐（slab/stairs 含）；文档承认 Nether/End 的边界扩散是"未做"的原因 | `README.md:158`；`docs/world-height.md:66-72` | 官方文档 |
| 世界高度 | 每维度由 dimension type 决定（`min_y`/`height`/`logical_height`），上限 2032 | 同样从 dimension type 读，数据包可把主世界拉到 2096 高（131 段）；**但 Nether/End 仍按 `-64..320` 的 24 段列宽存**（vanilla 16 段） | `docs/world-height.md:1-8,66-72` | 官方文档 |
| 红石 | 逐 tick：形状更新 vs 邻居通知、计划 tick vs 方块事件、活塞顺序 | `level/redstone.rs` 1,578 行 + `level/redstone/`；48 台机器逐 tick 对比，修掉"`/setblock` 先通知邻居后做形状更新"后 144 组随机电路 40 tick 完全一致 | `docs/parity/redstone-diff.md:31-37` | 官方文档 |
| 红石对比的盲区 | — | 只比对方块状态；物品实体、TNT、下落方块没有服务端实体视图，无法纳入对比 | `docs/parity/redstone-diff.md:39-43` | 官方文档 |
| 流体 | 水/岩浆流动、流体 tick、流体形状、方块含水 | `level/fluids.rs` 867 行 + `fluid_flow.rs`/`fluid_shape.rs`/`fluid_occupancy.rs`；harness `fluid`、`fluid_flow`、`fluid_shape`、`fluid_occupancy`、`fluid_box` | 同左 | 源码实证 |
| 方块更新/计划 tick | `LevelChunk.setBlockState` 的 flags、邻居更新、`BlockEvent` | `level/update.rs`、`level/tick.rs` 2,013 行；harness `block_update`、`random_tick`、`random_tick_sections` | 同左 | 源码实证 |
| 随机 tick | 每 section 用精确计数挑随机位置 | 用 section 的调色板做"候选状态掩码"再挑；文档自述"调色板里还留着已无人使用的可 tick 状态时，会比 vanilla 多 tick" | `docs/parity/blocks.md:164-166`；`game/block_ticks.rs:243-271` | 官方文档 |
| 天气 | `ServerLevel.tickPrecipitation`：降雨/降雪/结冰/炼药锅积水、`isRainingAt` | `level/weather.rs` 134 行，用群系温度 + 高度修正 + 冻结噪声；harness `biome_weather`、`weather_render` | `docs/parity/blocks.md:90-95` | 官方文档 |
| 闪电/雷暴 | `tickThunder`、`LightningBolt`：点燃、伤害、避雷针、引雷 | 已实现：`game/lightning.rs` 有 `tick_thunder`、`LightningBolt.tick`、雷声与渲染；但**没有专门的老虎机式 parity harness**（只有 `natural_spawn` 的 thunder 用例覆盖生成侧） | `crates/horizon-client/src/game/lightning.rs:1-2,72,356-365` | 源码实证（实现）/ 未证实（一致性） |
| 生物群系生成 hook | — | `native-hooks.json` 中 `worldgen`/`structure` 关键词命中 **0** 个，`biome` 只命中 `biome_colors` | `native-hooks.json`（hooks 434 条） | 源码实证 |

### 2.3 存档与多人

| 领域 | Java 版行为 | Horizon 行为 | 证据 | 置信度 |
|---|---|---|---|---|
| 存档格式 | Anvil region（gzip/zlib/未压缩/lz4）、palette、block/fluid tick 列表 | 同四类 codec（含 lz4-java 28-bit xxHash），region 头/长度/扇区重叠/外部 `.mcc` 都校验；负数坐标 floor 除法 | `docs/world-data.md:46-49` | 官方文档 |
| 存档往返 | 逐字节可被 vanilla 打开 | "saves round-trip with vanilla"（266 场景 palette 一致） | `README.md:155-160` | 官方文档 |
| 旧存档升级 | DataFixer 逐文件在读取时升级 | 打开时一次性升级所有文件（level.dat、区块、实体、POI、玩家、saved data、进度、统计） | `docs/world-data.md:69` | 官方文档 |
| DataFixer 覆盖 | 服务器 + 客户端文件 | **服务器侧全部移植（含 1.8 无 DataVersion 的存档）；客户端文件（options、debug profiles）的 fix 没有** | `docs/world-data.md:69` | 官方文档 |
| 存档事务 | 写 region 的基本原子性 | 导出用"临时 region + 硬链接发布"，崩溃恢复/目录 fsync/原地事务**未实现** | `docs/world-data.md:51-56` | 官方文档 |
| 维度高度模型 | Nether/End 各 16 段 | 仍按主世界 24 段列宽存（含空气段） | `docs/world-height.md:66-72` | 官方文档 |
| 单人/局域网/专用服 | 单人内置服务器线程；LAN 广播 | 同一份 `Game` 跑 `Client`/`IntegratedServer`/`DedicatedServer` 三种角色；单人也走服务器线程 | `docs/server-levels.md:38-50` | 官方文档 |
| 专用服务器配置 | `server.properties`、`eula.txt`、白名单/OP/封禁 4 个 JSON | 逐字节按 vanilla 的 `Properties.store` 回写；四个列表按 vanilla 顺序与格式加载 | `docs/server.md:19-24` | 官方文档 |
| 服务器命令 | 控制台全部命令 | 常用命令逐一实现，其余交给游戏命令调度器（权限 4）；额外有 `tempban` | `docs/server.md:32-35` | 官方文档 |
| 服务器规模 | 100 人靠 watchdog 兜底 | 50 bot 稳 20 TPS，100 bot 掉到 9–11 TPS；25–50 人挤在主城时 vanilla tick 更短 | `docs/server.md:44-47` | 官方文档 |
| LAN 发现 | 组播广播，在线/离线均可 | 462 个用例通过，**仅离线模式** | `README.md:154` | 官方文档 |
| 代理/传输 | `accepts-transfers`、Velocity forwarding | 自带 transfer 模块（默认关），必须开 Velocity forwarding，否则拒绝启动 | `docs/server.md:90-110` | 官方文档 |

### 2.4 接口与模组边界（决定"能不能搬"）

| 领域 | Java 版行为 | Horizon 行为 | 证据 | 置信度 |
|---|---|---|---|---|
| Java 模组 | Fabric/NeoForge/Forge jar 可加载，Mixin/ASM 任意注入 | **jar 不运行**；启动器只把 jar 里的 data/assets 搬过来 | `README.md:84-91` | 官方文档 |
| 无模组时的行为 | — | 模组默认关闭，干净安装 = vanilla 26.3（这是"parity 成立"的前提） | `README.md:91` | 官方文档 |
| 内容模组能力 | — | `.hmod` 仅数据：方块（必须从 vanilla 模板派生）、物品、配方、战利品、模型、贴图、音效；**方块实体排到 0.4、实体类型 0.5、自定义渲染 0.5** | `docs/modpacks.md:163-190`（方块实体 `:175`、实体 `:182`） | 官方文档 |
| 自定义 mob effect | `MobEffect` 可重写 `applyEffectTick` | 注册表（类别/颜色/图标/名字）有，**没有 tick 行为**，要等 native hook 点 | `docs/modpacks.md:168` | 官方文档 |
| 原生模组 hook 面 | Mixin 任意点 | 434 个具名 hook：`block_changed`/`tick_block`/`block_signal`/`entity_tick_pre` 与 `post`/`potential_spawns`/`mob_spawned`/`loot_drops`/`player_trade`…；**按名称统计，`worldgen`/`structure`/`goal`/`path`/`brain`/`redstone` 关键词 0 命中**（名称统计只证明"没有这个 hook"，不涉及可变性；见 §0） | `native-hooks.json`（`hooks` 434、`helpers` 177） | 源码实证 |
| 原生模组可注册 AI | — | `register_goals`（模组侧 API），但不是"拦截 vanilla AI 决策"的 hook | `docs/modpacks.md:182`；`native-hooks.json` 无 goal/path/brain | 官方文档 + 源码实证 |
| 服务器端 hook | 插件/模组可拦任意事件 | 有 server 侧 hook 计划与部分实现，容器实体（矿车、箱子船）尚未接通 | `docs/native-mods.md:3829` | 官方文档 |
| 爆炸的实体伤害/击退 | `ExplosionEvent.Detonate` 可改受影响实体集合，伤害与击退可逐实体调 | `native_explosion_detonate(dimension, center, source, blocks: &mut Vec)` **只给方块坐标**，"Entities are hurt as before"；击退可改：`native_explosion_knockback(dimension, center, blocks, entity, knockback_velocity: &mut [f64; 3])` 在 `ServerExplosion.hurtEntities` 算出速度后、加到实体前替换，玩家客户端收到同一份替换值。注意 `entity` **为 `None` 时表示"被炸的是玩家"**，其名字要从 `native_acting_player` 取，生物才是 `Some(u32)`；风弹也算，龙与末影水晶除外（末影水晶被直接移除，没有速度可改） | `crates/horizon-client/src/game/native_hooks.rs:8506-8520`（detonate，文档 `:3680` 的参数表漏了 `source`，以签名为准）、`:8528-8546`（knockback）；`docs/native-mods.md:3680-3686` | 源码实证 |
| 超出 vanilla 的能力 | — | 远地形 1,024 chunks、`horizon:lod` 通道、反作弊模块、YUNG/Moogs 结构地形适配 | `README.md:32`；`docs/graphics.md:101`；`enhanced_terrain.rs:1-6` | 官方文档 + 源码实证 |

## 3. 对"把 Java mod 移植到 Horizon"的影响

按"会让行为失真"的严重程度排：

1. **依赖 Mixin 注入 AI / 寻路 / 世界生成的 mod 无法移植。** `native-hooks.json` 里 `goal`/`path`/`brain`/`worldgen`/`structure` 全部 0 命中，`mobs/ai.rs`、`path.rs` 都是封闭实现。想要"改僵尸 AI""加自定义结构生成器"，只能等新 hook（每个 hook 要对所有模组开放，见 `docs/modpacks.md:185` 的"New hooks into vanilla behaviour"）。
2. **自带生物群系的数据包/modpack 会静默降级。** `overrides.rs:239` 的日志是 `cannot add biomes yet, so it is left out`，且被剔除群系的 tag 与气候点会一起消失 —— Terralith 这类"纯数据包群系"包，地形会退化成相邻群系。这是本次调研里**唯一一条"原版内容会被丢"级别的差异**。
3. **跨维度农场会失真。** 生物/掉落物/矿车不进传送门（`server-levels.md:99-100`），末地/下界之间的物品运输、跨维度刷怪塔、跨维度漏斗系统行为与 vanilla 不同；`@e` 不限范围时只读单维度（`server-levels.md:101-102`），让"跨维度选择器"类命令系统行为不同。
4. **机器 mod（方块实体）暂时无处落脚。** 方块实体 API 排在 0.4（`docs/modpacks.md:175`），在此之前任何"有库存、会 tick"的机器只能靠原生 Rust 模组硬写。
5. **自定义药水效果只有壳。** 注册表能进，但 `applyEffectTick` 没有（`modpacks.md:168`），一秒一跳的持续效果会变成"只有属性修正，没有周期行为"。
6. **依赖精确随机序列的 mod 可能漂移。** 方块行为触发的 feature 放置用的是"关卡随机的副本，放完再写回"（`crates/horizon-world/src/level/growth.rs:267-285`）：主序列被正确推进，但放置期间邻居更新里的 `next_world_*` 抽取落在副本上（`docs/parity/blocks.md:160-163`）。作物/骨粉/树苗类 mod 若依赖"放完树后下一次抽取是什么"，会与 vanilla 不同。
7. **红石与实体的交互是盲区。** 对比工具只覆盖方块（`redstone-diff.md:39-43`），所以"发射器射箭命中实体""TNT 矿车链式引爆""漏斗吸矿车"这类 mod 机器，即使行为一致也没有 harness 兜底 —— 移植时不能拿"parity 通过"当保证。
8. **存档能互通，但不要期望字节相同。** DataFixer 与 region codec 对齐（`world-data.md:69`），主世界区块可以来回打开；Nether/End 的段列宽不同（`world-height.md:66-72`），依赖"Nether 区块恰好 16 段"的第三方工具会读到额外空气段。
9. **服务器插件生态不存在。** 没有 Bukkit/Paper/Spigot 的插件接口，`horizon-server` 只有自己的 CLI + 控制 API（`server.md:2-40`）。任何"装个插件"的部署方式都要重写。
10. **爆炸类 mod 只能"整场取消 + 逐实体补"，不能原地改。** `native_explosion_detonate(dimension, center, source, blocks)` 只收到方块坐标，实体伤害原样执行（`native_hooks.rs:8506-8520`；`docs/native-mods.md:3680-3681`）；击退则可以原地替换，`knockback_velocity: &mut [f64; 3]`（`native_hooks.rs:8534-8546`），玩家客户端拿到的也是替换后的值。手雷/火箭筒这类 mod 要改"炸到谁"只能取消整次爆炸再用 `native_explode` 重建、或逐个 `native_hurt_entity` + `native_living_knockback` 补，行为不可能与 Java 侧"改 `Detonate` 的实体集合"一一对应。

## 4. 未证实清单

| # | 说法 | 为什么没定 | 怎么验证 |
|---|---|---|---|
| 1 | `mob_ai` 的 `drowned_*` 仍在失败（#290） | 只有 `architecture.md:43` 一行，日期 2026-10-23；本机没有 `.local/parity-runner` 状态 | 跑 `python3 tools/parity.py mob_ai`（需准备资源与 JDK） |
| 2 | 爆炸的视线遮挡"只用全碰撞方块" | 结构已核对：采样网格、`x_offset`/`z_offset`、`CollisionContext::for_entity` 都与 `ServerExplosion.getSeenPercent` 对应（`explosion.rs:246-300`，已与 10 号文档交叉核对）；只剩 `clip_world` 的 `RayBlockMode::Collider` 是否与 Java `ClipContext.Block.COLLIDER` 逐位等价未定 | 读 `game/clip_ray.rs` 与 `CollisionContext` 实现，或实测非全碰撞形状（栅栏/台阶）后的击退 |
| 3 | 随机 tick 因调色板残留而多 tick | 只有 `blocks.md:164-166` 自述；`block_ticks.rs:243-271` 的掩码+revision 缓存是否已消除该差异，无法静态判断 | 跑 `test_random_tick_sections_parity` |
| 4 | 树密度差距"可能只是装饰顺序" | 作者原话就是"may be the order"（`world-compare.md:60-64`），没有定论 | 按固定顺序在平坦区块生成后逐块比对 |
| 5 | 闪电与 vanilla 完全一致 | 有实现（`lightning.rs`），但没有专门 harness | 自建雷暴场景对比点燃/伤害/避雷针 |
| 6 | 凋灵整场行为一致 | 只有 `wither_wind_charge` harness，没有整场对比 | 自建召唤-充能-三头射击场景 |
| 7 | 刷怪上限的具体数值 | 只确认了 `LocalMobCapCalculator` 语义存在（`spawn_selection.rs:863,970-973`），没逐类别抄数 | 对照 `natural_spawn` 用例的 cap 分支 |
| 8 | 社区说法："活塞推实体还没做完"（newsminecraft.com） | **与源码矛盾**：`game/block_ticks.rs:318-321` 有 `push_piston_entities`、`game/entity.rs:240-289` 有 `get_piston_push_reaction`/`move_by_piston` | 已按源码否证，仅作"社区信息不可靠"的例子 |
| 9 | 社区说法："着色器包支持被移除、正在重写"（gameversify） | 本地 `docs/shaders.md:1-12` 显示 Iris/OptiFine 格式有独立 loader，另有 Horizon 自有 WGSL 格式（API 0.1，实验性） | 以本地文档为准，疑为旧闻 |
| 10 | "470 个未关闭 issue"（portedgames.com，2026-11-04） | 第三方统计，未在本地核对 | 查 GitHub issues |
| 11 | README 的"833 个玩家可见缺口，0 未关闭" | 项目自述，且其定义是"harness 覆盖到的范围内 0 缺口"（`README.md:142-148`），不等于"与 vanilla 无差异" | — |
| 12 | `native-hooks.json` 其余 432 条 hook 的 `contract`/`cancellable` 是否也有与源码不符的 | 已确认至少三处与源码对不上（`explosion_knockback` 标 collect、`item_damaged` 的 `out` 漏 `amount`、`native_explosion_detonate` 的文档参数表漏 `source`），说明索引字段不可信；其余条目未逐条比对 | 用 `native_hooks.rs` 里每个 `dispatch_*` 的形参表（`&mut` 与否、是否 `&mut bool`）批量对比 JSON —— 建议做成上游 `tools/` 下的一条检查/`cargo test`，让 JSON 再漂移时直接失败，而不是靠人工抽查 |

## 5. 参考来源

**本地（Horizon 仓库，`third_party/horizon/`）**

- `README.md:20`（目标版本）、`:30-36`（现状）、`:88-91`（Java mod 不运行、模组默认关）、`:142-165`（缺口计数与 14 个子系统评分表）
- `docs/rust-parity.md:1-28`（parity 的判定方式：harness 才是 spec）
- `docs/world-generation.md`（生成阶段、数据包、装饰顺序、整区块一致性数字）
- `docs/parity/world-compare.md`（同种子双世界对比、树密度、对比工具的盲区）
- `docs/parity/redstone-diff.md`（逐 tick 红石对比、只比方块）
- `docs/parity/blocks.md`（方块行为清单、**其 Known gaps 章节已有多处过时**）
- `docs/world-data.md`（NBT/region/palette/DataFixer/存档事务）
- `docs/world-height.md`（维度高度模型、Nether/End 段列宽遗留）
- `docs/server.md:1-140`（专用服务器启动、配置、命令、规模、transfer 模块）
- `docs/server-levels.md:97-102`（跨维度实体、`@e` 限制）
- `docs/architecture.md:15-52`（40 个模块 → 文件 → harness 对照；`:43` 的 `drowned_*` 已知失败）
- `docs/modpacks.md:160-200`（内容模组能力矩阵与排期）
- `docs/native-mods.md`（hook 语义；`:3829` 容器实体未接通）
- `docs/shaders.md:1-20`（两种着色器格式的状态）
- `native-hooks.json`（434 hooks / 177 helpers，关键词统计见 §2.4）
- 源码：`crates/horizon-core/src/version.rs`、`crates/horizon-client/src/mobs/{species,goals,spawn_selection,spawner,villager}.rs`、`crates/horizon-client/src/merchant.rs`、`crates/horizon-client/src/game/{dragon,wither,lightning,explosion,dispenser}.rs`、`crates/horizon-world/src/worldgen/overrides.rs`、`crates/horizon-world/src/level/{redstone,fluids,weather,growth}.rs`
- 姊妹文档：`docs/10-horizon-vs-java-combat.md`（战斗与物品；爆炸曝光与红石/实体 harness 盲区两处与本文交叉核对）

**官方站点**

- <https://playhorizon.dev/>（首页：26.3、MIT、differential harnesses 的定位、"players still find differences"）
- <https://playhorizon.dev/docs/>（文档入口，本地 `docs/` 的同源版本）
- <https://github.com/horizon-rust/horizon>（仓库；README 与 issues 的原始出处）

**社区/第三方（未证实，仅旁证）**

- <https://portedgames.com/minecraft-rust-edition>（2026-11-04 的快照：Java mod 不可用、470 open issues、"100% 需谨慎解读"）
- <https://gameversify.com/horizon-the-minecraft-rust-edition>（同上，另称着色器包在重写）
- <https://newsminecraft.com/minecraft-horizon-rust-rewrite>（称"活塞推实体尚未完成"，与源码矛盾）
- <https://awesomerea.org/zh/resources/horizon-minecraft-rust-rewrite-case>（中文转述，含 research-lock/工具链细节）
