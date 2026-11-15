# 10 · Horizon 与原版 Java（26.3）在战斗与物品上的差异

> 范围：战斗（攻速/冷却、伤害管线、暴击、击退、盾牌、弹射物、爆炸、死亡与掉落）、物品（右键语义、冷却、堆叠与组件、耐久、附魔、容器写入）、交互（优先级、实体交互、副手、事件顺序），以及**这些差异对枪械类 mod（TaCZ 移植）意味着什么**。
> 对象：`third_party/horizon`（本地检出；目标 **Minecraft Java 26.3**，`README.md:20`；许可证 MIT，`Cargo.toml:59`）。
> 结论只覆盖"能读到证据的部分"。凡是没有 `路径:行号` 或 URL 的，一律进 §5 未证实清单。

## 0. 怎么读这份文档

置信度三级，与 `09-horizon-vs-java-world.md` 一致：

| 等级 | 含义 |
|---|---|
| **源码实证** | 我读过 Horizon 的 Rust 源码，能给出 `路径:行号`，签名/字段逐字核对 |
| **官方文档** | Horizon 仓库内的 `docs/`、`README`、`ROADMAP` 或 playhorizon.dev 的自述，未逐行回源码 |
| **社区说法** | 第三方站点/论坛，未证实，只作旁证 |

**一个必须先说清的证据边界**：本机 `minecraft-26.3/` 只有 `server.jar`、`assets/`、`libraries/`、`versions/`，**没有 Java 源码**。所以"Java 版行为"一列不是从 Java 源码抄的，而是：

1. Java 通识（1.9+ 攻速、护甲公式、`blocks_attacks`、`ProjectileImpactEvent`…）；以及
2. Horizon 源码注释里**逐字点名了对应的 Java 方法/常量**（例如 `LivingEntity.getDamageAfterArmorAbsorb`、`getAttackStrengthScale(0.5)`、`ItemStack.hurtAndBreak`、`AbstractArrow.onHitEntity`）。这些注释是可引证据：它说明 Horizon 是照着那个 Java 方法移植的，而不是自创规则。

因此 Java 一列标 **"Java 通识（+ Horizon 注释同源）"**，置信度高；Horizon 一列只标源码实证/官方文档。

另外两个贯穿全文的事实：

- **Java mod 的 jar 完全不运行**（`ROADMAP.md:377`："Java code itself does not run"）。Horizon 的扩展面只有两种：**内容 mod**（`.hmod`，纯数据/资源）和**原生 mod**（`.hnmod`，Rust 代码，必须把游戏重编一遍，`docs/mods.md:24-27`）。
- 本文所有 hook 名都来自 `native-hooks.json`（**434 个 hook + 177 个 helper**），签名以 `crates/horizon-client/src/game/native_hooks.rs` 为准（JSON 里只有名字/边/是否可取消）。

## 1. 一页结论

按"对枪械移植的影响"从大到小排序：

1. **枪械能做出来，但做不成 Java 那套做法。** Horizon 没有"生成自定义弹射物"的 API，也没有服务端射线检测 helper。两条路都得 mod 自己搭：`native_summon` 生成一个**雪球模板**的弹体（`docs/mods.md:390-399`），或自己写 DDA 逐格读 `native_block(pos)`（`native_hooks.rs:11410`）。前者没有速度控制/穿透/衰减，后者绕过整个实体系统。
2. **"开火"和"扣弹"天然差一个 tick。** `native_use_item` / `native_use_item_on` 拿到的是 `&ItemStack`，而且上游是 `self.held().cloned()`（`use_hand.rs:208`）——**连可变引用都不是**，hook 里只能设 `claimed: &mut bool`（`native_hooks.rs:8197`）。唯一细粒度写回入口是 `native_inventory_tick` 里的 `native_carried_stack(slot) -> Option<&mut ItemStack>`（`native_hooks.rs:10668`，每 tick 对每个携带栈跑一次，`:11952`）。
3. **扳机/换弹键必须走客户端上行。** 服务端**没有**"玩家在空气里挥左键"的事件：`player_arm_swing` 只对 LAN 访客的 `Punch` 包触发（`lan_actions.rs:2487`）；`interaction_key` 只在有渲染窗口的进程里触发（`docs/native-mods.md:1230`）。专用服务器上读输入只能靠客户端 `mouse_button_pre`/`input_key`（`:1160`、`:1176`）→ `native_net_from_client`（`native_hooks.rs:8577`）上行。
4. **命中结算可以自己接管。** `native_projectile_impact` 可取消原版命中（`native_hooks.rs:9690`，需先 opt-in `native_hears_projectile_impacts`，`:9667`），再调 `native_hurt_entity(dimension, target, amount, damage_type, attacker)` 用**自定义伤害类型**走完整的护甲/无敌帧/击退/死亡/死亡消息（`docs/native-mods.md:3419`）。注意：取消后弹体**继续飞、不消失**，要自己 `native_remove_entity`。
5. **原版战斗本身是高保真的**——攻速（`attack_strength.rs:69,107`）、护甲+韧性+保护（`health.rs:520-570`）、附魔伤害全套（`game/enchant_effects.rs:1-10`）、盾（`horizon-world/src/blocking_rules.rs:65`）、图腾、击退、横扫都有真实实现。所以"战斗手感"不是障碍，**缺的是给 mod 的扩展面**。
6. **部署形态是硬约束。** 原生 mod 必须编进客户端二进制；服务器要玩同一套枪，必须用**同样带这个 mod 的 Horizon 构建**。这跟 Java 的"客户端装 jar、服务器装插件/jar"完全不是一回事。

## 2. 对照表

### 2.1 战斗

| 领域 | Java 版行为 | Horizon 行为 | 证据 | 置信度 |
|---|---|---|---|---|
| 攻击冷却 / 攻速 | 1.9+：`ATTACK_SPEED` 属性，`delay = 20/攻速` tick，伤害乘 `0.2 + s²·0.8`，换到不同物品重置 | 完整移植：`delay()`、`scale()`（`(ticker+a)/delay`，clamp 0..1）、`swap_scale()`、`main_hand_changed()`；伤害倍率 `0.2 + strength²·0.8` 逐字存在；主手攻速 = 属性 + 物品修正 +  haste/挖掘疲劳，clamp 0..1024 | `crates/horizon-client/src/attack_strength.rs:69,107`；`game/hand.rs:742` | 源码实证 |
| 属性/攻速来源 | 物品 `attribute_modifiers`（剑 1.6、斧 0.8-1.0…） | 由 `Items::attribute_modifiers` 与物品表驱动 | `crates/horizon-items/src/items.rs:1303` | 源码实证 |
| 伤害管线 | 无敌帧 → 护甲 → 韧性 → 附魔保护 → 抗性 → 吸收 → 实际扣血 → 图腾 → 死亡 | `ServerPlayerCombat::hurt` 是同一个状态机；`Environment` 带 `blocking / blocked / fully_blocked / knocked / totem / canceled`；护甲与韧性读**命中后**的属性缓存，与 `bypasses_armor` 的短路顺序一致 | `crates/horizon-client/src/health.rs:520-570`、`:622-680` | 源码实证 |
| 附魔伤害 | 锋利/亡灵杀手/节肢杀手/力量/击退/火焰附加/无限/荆棘/经验修补/保护系 | 数据驱动，按 `minecraft:damage` 等 effect 组件结算，不只硬编码原版名单 | `crates/horizon-client/src/game/enchant_effects.rs:1-10`；`:195`（额外击退） | 源码实证 |
| 暴击 | 下落 + 非疾跑等条件，×1.5 | `native_critical_hit(target_kind, vanilla_critical, &mut critical, &mut damage_multiplier)`——**暴击与否和倍率都能改** | `native_hooks.rs:8418-8432` | 源码实证 |
| 击退 | `LivingEntity.knockBack`，击退抗性削减，冲刺/击退附魔叠加 | `native_living_knockback` 在抗性之前、原始强度上可改可取消（`Knock`）；`dealDefaultKnockback` 后发 `indicateDamage` | `health.rs:94-146`；`native_hooks.rs`（API 125） | 源码实证（机制）/ 部分缺口（见下） |
| 击退**残留缺口** | 生物 `attack_knockback` 属性、host 上的击中击退来源、锤子 smash | 路线图明写仍是待办（"the mobs' `attack_knockback` attribute, mace smash logic, the hit knockback source on the host"） | `ROADMAP.md:593-600` | 官方文档 |
| 盾牌 | `blocks_attacks` 组件：伤害类型集合、角度、减免、`bypassed_by`、斧破盾 5 秒 | 组件解析（`BlocksAttacks`）+ `BlockingRules` 匹配 + 角度 + 穿透箭判定；`player_shield_disable` 在冷却设置前可听 | `crates/horizon-items/src/items.rs:190,246-283`；`horizon-world/src/blocking_rules.rs:65`；`docs/native-mods.md:1549` | 源码实证 |
| 横扫 | 剑横扫 + `sweeping_damage_ratio` 属性 | 有 `sweeping_damage_ratio` 属性与 sweep 结算（`enchant_effects.rs:217`）；1.8 规则下关闭（`pvp.md:141`） | `game/chat.rs:891`；`game/enchant_effects.rs:217`；`docs/pvp.md:139-145` | 源码实证（属性/调用）+ 官方文档 |
| 箭的飞行 | `AbstractArrow`：重力 0.05、空气阻力、暴击、穿透、拾取 | 同一套：`ProjectileKind::Arrow{base_damage, critical, effect}`，重力 0.05 | `crates/horizon-client/src/projectiles.rs:1-6,84-95`；`:207` | 源码实证 |
| 投掷物 | 雪球/蛋/珍珠/药水：重力 0.03，雪球对烈焰人 3 点 | 同一类 `ThrowableProjectile` 物理，`ProjectileKind::{Snowball,Egg,EnderPearl,Potion,…}` | `projectiles.rs:1-6,120-135` | 源码实证 |
| 箭命中结算 | `AbstractArrow.onHitEntity`：伤害 = 速度 × 基础伤害，命中后插在身上、无敌帧、拾取 | `player_hit(..., "minecraft:arrow", direct, amount)`；`Stuck::add_arrow` 复刻 `onHitEntity` 的"不穿透则插上" | `game/creatures.rs:5572-5708`；`game/combat.rs:47-53` | 源码实证 |
| 弹射物命中 hook | `ProjectileImpactEvent`：可取消，可改 | `native_projectile_impact(dimension, projectile, kind, owner, entity, entity_kind, block, face, at, &mut canceled)`；取消后"无伤害、无击退、无音效、箭不插上、珍珠不传送"，弹体继续飞 | `native_hooks.rs:9690-9715`；`docs/native-mods.md:1226` | 源码实证 |
| 爆炸 | `Level.explode`：方块破坏 + 实体伤害（距离/遮挡）+ 击退 + 火焰 | 有 `native_explode(dimension, center, radius, fire, blast)` 完整复刻（含掉落衰减、火焰 1/3）。`native_explosion_detonate(dimension, center, source: Option<(u32,&str)>, blocks: &mut Vec<[i32;3]>)` 在 `ServerExplosion.explode` 的 `toBlow` 上给**可删可留的方块集合** + 起爆来源实体；**实体照旧受伤**，改不了 | `native_hooks.rs:8506-8520`；`docs/native-mods.md:4086-4094`、`:3680-3681` | 源码实证（文档 `:3680` 的参数表漏了 `source`，见 §3.2 #10） |
| 爆炸曝光（视线遮挡） | `ServerExplosion.getSeenPercent`：对实体 AABB 采样，逐点向中心射线，`ClipContext.Block.COLLIDER` | 同名函数 `seen_percent`，采样步长/偏移逐字复刻，射线用 `RayBlockMode::Collider` + `CollisionContext::for_entity` | `crates/horizon-client/src/game/explosion.rs:246-300` | 源码实证（结构）/ 未证实（与 vanilla 是否逐位等价，见 §4 #11） |
| 爆炸击退 | `ExplosionKnockbackEvent` 可读可改 | **可替换**：`native_explosion_knockback(dimension, center, blocks, entity, &mut [f64;3])`，在 `ServerExplosion.hurtEntities` 算出速度之后、加到实体速度之前；玩家的客户端收到同一份替换值；风弹也算（龙/末影水晶除外） | `native_hooks.rs:8528-8546`；`docs/native-mods.md:3682-3685`（API 374） | 源码实证（注意：`native-hooks.json` 把它标成 `contract: "collect"`，与实际签名不符，见 §3.2 #10） |
| 死亡 | `LivingDeathEvent` 可取消；死亡消息、击杀归属 | `living_death` 可取消；`CombatTracker` 复刻（伤害记录、攻击者、掉落高度、死亡消息）；`kill_credit`/`killing_blow` | `native-hooks.json`（`living_death`）；`game/combat.rs:1-6,177-215` | 源码实证 |
| 死亡掉落 | `LivingDropsEvent`/`BlockDropsEvent`，`keepInventory` | `loot_drops` **collect**（可取走栈 → 等于保住背包），API 405 明确"a mod that takes every stack out of `drops` keeps the inventory"，`keep_inventory` 时不来 | `docs/native-mods.md:1813` | 官方文档 |
| 1.8 战斗规则（可选） | —（Java 只能靠 mod/服务端插件） | `combatRules` 选项：无冷却、1.8 武器伤害表、力量/虚弱/锋利公式、1.8 击退；**只在自己当服务器的世界生效** | `docs/pvp.md:130-160`；`crates/horizon-client/src/legacy_combat.rs` | 官方文档 |

### 2.2 物品

| 领域 | Java 版行为 | Horizon 行为 | 证据 | 置信度 |
|---|---|---|---|---|
| 右键：`useOn` | 先方块自身 use → `ItemStack.useOn` → `Item.use` | 同序：`right_click_block` → 方块自身 → `use_item_on` → `use_item`；**每只手一次**，主手先、副手后 | `game/use_hand.rs:20-45,226-236`；`game/item_actions.rs:55-66`；`docs/native-mods.md:218-226` | 源码实证 |
| `use_item` 的上下文 | `Item.use(level, player, hand)` 可改玩家/手/栈 | `native_use_item(&mut self, stack: &ItemStack, claimed: &mut bool)`——**栈不可变，且是 clone** | `native_hooks.rs:8197`；`use_hand.rs:208,234` | 源码实证 |
| `use_item_on` 的上下文 | `ItemStack.useOn(context)` | `native_use_item_on(stack: &ItemStack, pos:[i32;3], face:[i32;3], claimed:&mut bool)`——同样不可变 | `native_hooks.rs:8156-8170` | 源码实证 |
| claimed 语义 | 返回 `InteractionResult`（SUCCESS/CONSUME/PASS） | `claimed=true`：挥手、物品自身 use 与 useOn 都不跑；`use_item` 被 claim 后不再走后续原版逻辑 | `native_hooks.rs:8156-8170,8197-8203`；`use_hand.rs:236-239` | 源码实证 |
| 物品冷却 | `use_cooldown` 组件：`ItemCooldowns`，冷却中不能使用 | 组件被读取并在**进 hook 之前**挡掉（"an item on cooldown is not used (PASS, so the other hand may still act)"） | `use_hand.rs:215-222`；`game/item_use.rs:133` | 源码实证 |
| 设置冷却 | 代码里随意 `player.getCooldowns().addCooldown(item, ticks)` | **只能取消，不能设置**：`native_player_item_cooldown(player,name,item,ticks,&mut cancel)` 只有 cancel；唯一的"设置"是 `native_release_using` 里 `used=true` 触发本物品冷却 | `native_hooks.rs:5151`；`docs/native-mods.md:1521,1216` | 源码实证 |
| 使用中（蓄力） | `getUseDuration`/`getUseAnimation`/`onUseTick`/`releaseUsing` | 全套：`use_duration`、`use_animation`、`can_eat`、`use_item_tick`、`on_use_tick`、`use_item_stop`、`release_using`；**mod 自己的物品**若 `use_duration > 0`，右键即"持续使用"，松手走 release | `docs/native-mods.md:1038,1216`；`native_hooks.rs:8210-8260,8291,8367-8442` | 源码实证 + 官方文档 |
| 使用完成 | `finishUsingItem` 决定手里剩什么 | `native_living_entity_use_item_finish(stack, entity, hand, duration, &mut result: Option<ItemStack>)`——**可以换掉手里那一个栈** | `native_hooks.rs:8291-8305` | 源码实证 |
| 物品结构 | `ItemStack` = 物品 + 数量 + `DataComponents` | `ItemStack { pub item: Arc<str>, pub count: u32, pub damage: u32, pub extra: Option<Box<StackData>> }`——组件在 `extra`，字段全 pub | `crates/horizon-items/src/items.rs:340-346` | 源码实证 |
| 组件读写 | `stack.set(DataComponents.X, v)` / `get` | `data()/data_mut()/set_other(id, Option<Tag>)/other(id)`、`custom_data()`、`container()`、`enchant()`、`set_crafting_enchantments()`；`from_nbt` 直接读 `/give` 那种 SNBT | `crates/horizon-items/src/item_data.rs:142,197,307-330,377,422-430` | 源码实证 |
| 堆叠上限 | `max_stack_size` 组件（1..99，部分物品更小） | 组件可读可改；`native_max_stack_size(item)` helper；数据文件里可写 `"minecraft:max_stack_size": 16`，上限放宽到 `i32::MAX` | `docs/native-mods.md:998-1000,1063` | 官方文档 |
| 耐久 | `ItemStack.hurtAndBreak`，Unbreaking 先算 | `native_item_damaged(player,name,item,&mut amount,&mut cancel)`——在 Unbreaking **之后**、`hurtAndBreak` 之内，可改数值可取消 | `native_hooks.rs:9238-9247`；`docs/native-mods.md:1321` | 源码实证 |
| 物品损坏 | `PlayerDestroyItemEvent`（带原栈与手） | `player_destroy_item(player,name,item,slot)` 只带槽位（`mainhand/offhand/head/...`），不含原栈；`item_damaged` 另给磨损点数的修改/取消权（`&mut amount, &mut cancel`） | `native-hooks.json`（`item_damaged`）；`docs/native-mods.md:315,1629` | 源码实证（签名）/ JSON 的 `contract` 与实际可变性不符，见 §3.2 #10 |
| 附魔写入 | `stack.enchant(...)`、`EnchantmentHelper` | `enchant(id, level)`（"升级到更高等级"，且 `!minecraft:enchantments` 移除补丁存在时 no-op，与 vanilla `updateEnchantments` 一致） | `item_data.rs:377-397` | 源码实证 |
| 附魔事件 | `PrepareAnvilEvent`、附魔台 | `prepare_item_enchant`（replace）、`enchant_item`（听）、`enchant_effect`（自定义 effect kind 的 `post_attack`） | `native-hooks.json`；`docs/native-mods.md:638-646` | 源码实证 |
| 容器 / 背包写入 | `player.getInventory().setItem(...)` 随写随生效 | 分三档：① `native_inventory_tick` 内 `native_carried_stack(slot)` 拿 `&mut`（每 tick 每槽一次，含护甲/副手）；② `native_set_inventory(uuid, kind, slots, selected)` 整包替换（只能在 `native_server_tick` 之类调用）；③ `native_give`/`native_give_stack` 发放 | `native_hooks.rs:9376,10668,11952`；`docs/native-mods.md:2905`；`native_hooks.rs:11738` | 源码实证 + 官方文档 |
| 物品内嵌容器 | `Capabilities.Item.ITEM`（背包/弹匣） | `native_item_container(item, slots)` 把槽存在栈的 `minecraft:container` 组件里；`insert/extract` **不改传入栈**，返回结果由调用方写回 | `docs/native-mods.md:1741` | 官方文档 |
| 物品实体 | `ItemEntity` 可生成/改栈 | `native_item_entities(dimension,min,max)` + `native_set_item_entity(dimension,id,stack)`（空栈=移除） | `docs/native-mods.md:378-382` | 官方文档 |

### 2.3 交互、副手与事件顺序

| 领域 | Java 版行为 | Horizon 行为 | 证据 | 置信度 |
|---|---|---|---|---|
| 方块交互优先级 | 方块 use → 物品 useOn → 物品 use；潜行+双手有物时跳过方块 | 同序，且潜行判定 `sneaking && hands_full` 复刻 | `use_hand.rs:20-45` | 源码实证 |
| 每一手的边界 | 主手失败才轮到副手（`Minecraft.startUseItem`） | `Hand::BOTH` 顺序试，每手完整走一遍 use_hand，所以 hook 也是每手各一次 | `game/item_actions.rs:55-66`；`use_hand.rs:1-9` | 源码实证 |
| 实体交互 | `Player.interactOn` → 实体自身 interact → 物品 `interactLivingEntity`；每手一次 | `native_interact_entity(entity, kind, stack: Option<&ItemStack>, claimed)` + v2 带 `hand`；"A click v1 claimed is not asked here" | `native_hooks.rs:2595-2610,7794-7810` | 源码实证 |
| 左键点方块 | `PlayerInteractEvent.LeftClickBlock`：可取消，保留方块 | `native_left_click_block`（可取消，服务器侧连 crack 一起收回） | `docs/native-mods.md:294-300`；`native-hooks.json` | 源码实证 |
| 左键点实体 | `AttackEntityEvent` 可取消 | `native_attack_entity(entity, kind, pos, &mut canceled)`——"in reach, where `Player.attack` starts" | `native_hooks.rs:8571-8580` | 源码实证 |
| 空挥左键（没打到东西） | `PlayerAnimation` / 客户端 swing 包 | **服务端无对应 hook**；`player_arm_swing` 只对 LAN 访客的 `Punch` 包 | `lan_actions.rs:2487`；`docs/native-mods.md:1681` | 源码实证 |
| 客户端输入 | — | `mouse_button_pre/post`（API 114，可取消）、`input_key`（API 121）、`interaction_key`（API 138，攻击/使用/选取键**即将作用**前，可取消并可选是否挥手） | `docs/native-mods.md:1160,1176,1230`；`native_hooks.rs:2792` | 源码实证 + 官方文档 |
| 服务端输入 | — | `player_input(player,name,flags)`：只来自 guest 的 `PlayerInput` 包（WASD/跳/潜/冲刺位），**不含鼠标键** | `docs/native-mods.md:1687,2600` | 官方文档 |
| 客户端↔服务端 | 自定义 payload | `native_net_from_client(player, channel, data)` / `native_net_from_server(channel, data)`，`channel = mod_id:name` | `native_hooks.rs:8577-8590` | 源码实证 |

### 2.4 扩展面本身（决定"能不能搬"）

| 领域 | Java（NeoForge/Fabric） | Horizon | 证据 | 置信度 |
|---|---|---|---|---|
| 运行 Java 字节码 | 是 | **否** | `ROADMAP.md:377`；`README.md:20`（"rewritten in Rust … no Java"） | 官方文档 |
| 代码 mod 形态 | jar，客户端/服务端各装 | **原生 mod**：源码 + `horizon-mixins`，launcher 重编游戏 | `docs/mods.md:24-27`；`docs/native-mods.md:1838-1860` | 官方文档 |
| 声明式内容 | datapack/资源包 | **内容 mod** `.hmod`：方块、物品、创造标签、mob effect、实体类型、菜单类型、伤害类型、配方、战利品 | `docs/mods.md:109,513,531-540` | 官方文档 |
| 自定义实体类型 | `EntityType.Builder.of(MyEntity::new, …)` | **只能"复制一个模板"**：`minecraft:snowball`（投掷物）、`minecraft:zombie/villager/wandering_trader`（生物）。投掷型的速度/散布/音效/冷却=雪球，`damage` 是**注册时固定**的一个数，命中的是 `thrown` 伤害 | `docs/mods.md:390-404` | 官方文档 |
| 自定义伤害类型 | `DamageType` 注册表 | 数据文件 `data/<ns>/damage_type/<name>.json`（`message_id`/`scaling`/`exhaustion`…），可被 `native_hurt_entity` 直接使用 | `docs/mods.md:531-540`；`docs/native-mods.md:3419` | 官方文档 |
| 射线检测 | `level.clip(...)`、`EntityGetter.getEntity`、`ProjectileUtil.getEntityHitResult` | `native_raycast(distance)` / `native_view_hit()`：**仅客户端、仅沿视线、仅方块**，上限 1024；没有任何"从 A 点到 B 点"的服务端射线，也没有 ray-vs-entity | `crates/horizon-client/src/game/native_claimed_items.rs:136-160`；`docs/native-mods.md:1164` | 源码实证 |
| 读方块（服务端） | `level.getBlockState(pos)` 随处可调 | `native_block(pos) -> String`（物品名，不含状态；未加载给 air）；`native_read_columns` 只给列；`native_set_block` 只写 | `native_hooks.rs:11410`；`docs/native-mods.md:1208` | 源码实证 |
| 生成实体 | `level.addFreshEntity` | `native_summon(dimension, kind, pos, nbt) -> Option<u32>`：完全走 `/summon` 的 NBT 载入（含 `Motion`、`Owner`、`damage`、`crit`、乘客） | `native_entities.rs:215-266`；`entity_nbt.rs:3167,3408-3428` | 源码实证 |
| 生成弹射物（专用 API） | `new Arrow(...)` / 自定义 `Projectile` | **不存在**。最优路径是 `native_summon` 一个 vanilla 弹体或内容 mod 的投掷型；`Projectile::new` 速度为 0，必须靠 NBT `Motion` 给初速 | `projectiles.rs:451-480`；`entity_nbt.rs:3420` | 源码实证 |
| 实体几何（做命中盒判断） | `entity.getBoundingBox()` | `bounding_box()`、`eye_position()`、`view_vector()`、`distance_to_sqr()`、`velocity()` | `docs/native-mods.md:1761`（API 379） | 官方文档 |
| 改玩家位置/朝向（读） | `player.getYRot()` | `NativePlayer { x,y,z,yaw,pitch,dimension }` | `native_hooks.rs:1913-1922` | 源码实证 |
| 音效 | `level.playSound` | `GameLevel::native_play_sound`（注册表内音效；`mymod:` 命名空间的自有音效也支持） | `docs/native-mods.md:273,912` | 官方文档 |
| 粒子 | `addParticle` | `native_flame_particle(at, soul)`（**只有火焰粒子一种 helper**）；其它靠客户端 hook 画 | `native_hooks.rs:10644-10660` | 源码实证 |

## 3. 对枪械（TaCZ）移植的影响

### 3.1 逐步对照：Java 里的一步 → Horizon 现在缺什么

#### ① 定义枪与弹药物品 —— **可以，基本无痛**

内容 mod 用 `data/<ns>/horizon/item/<name>.json` 就能声明物品（模板 + 差异），原生 mod 还能用 `native_items(items)` 在代码里注册（`docs/native-mods.md:1254`）。弹匣/配件用组件表达完全可行：`ItemStack.extra` 是通用的 `StackData`（`items.rs:340-346`），`set_other("tacz:ammo", Tag)` 就能存任意 SNBT，`custom_data()` 读回（`item_data.rs:197,426-430`）。堆叠上限用 `minecraft:max_stack_size` 组件。

#### ② 扣扳机（读输入） —— **服务端缺一半，必须客户端上行**

| Java 做法 | Horizon 对应 | 缺口 |
|---|---|---|
| 客户端按键 → 自己发 `CustomPacketPayload` | 客户端 `mouse_button_pre`（API 114，能拿 GLFW button 0/1 + 修饰键，可取消）/ `input_key`（API 121） | —— |
| 服务端 `ServerPlayNetworking.registerGlobalReceiver` | `native_net_from_client(player, channel, &[u8])`（`native_hooks.rs:8577`） | —— |
| 服务端直接用 `PlayerInteractEvent`/`AttackEntityEvent` 判定左键 | `native_attack_entity` 只在**真的打到实体**时来；`native_interaction_key` 只有在**有渲染窗口**的进程里来（`docs/native-mods.md:1230`） | **专用服务器上没有"空挥左键"信号**；`player_arm_swing` 只覆盖 LAN 访客（`lan_actions.rs:2487`） |

结论：**全自动/半自动射击的"按下/松开"必须走"客户端 hook → 自定义 payload → 服务端"这条路**，并且要求客户端装同一个原生 mod。纯服务端（玩家用别的客户端）根本无法做枪。

#### ③ 射速与冷却 —— **不能用原版冷却系统，只能自己计时**

- 物品可以带 `minecraft:use_cooldown` 组件，但**冷却中 `use_item` 根本不触发**（`use_hand.rs:215-222`），所以冷却=硬门，不能"冷却中还能来一下"。
- 没有任何 helper 能给玩家/槽位**设置**任意冷却：`native_player_item_cooldown` 只能 cancel（`native_hooks.rs:5151`）；`release_using` 的 `used` 只能给"本物品"上冷却（`docs/native-mods.md:1216`）。
- 所以射速只能 mod 自己在 `native_player_tick` / `native_inventory_tick` 里用 tick 计数 + `native_net_from_client` 的输入状态做门控。
- **代价**：没有原版 HUD 的冷却扇形（那是由游戏按 `ItemCooldowns` 画的），要自己画（客户端 `native_item_decorations` / `native_hud`）。

#### ④ 弹道 A：hitscan（射线命中） —— **能，但要自己写整套**

| Java | Horizon |
|---|---|
| `player.pick(reach, 0, false)` 拿方块命中 | **服务端没有**。必须自己 DDA：从 `NativePlayer.eye + view_vector` 出发，逐格 `native_block(pos)`（`native_hooks.rs:11410`），命中非空气/非流体即停 |
| `ProjectileUtil.getEntityHitResult(...)` 拿实体命中 | **没有**。只能自己遍历（`native_mobs_in`/实体列表 + API 379 的 `bounding_box()`）做 ray-AABB |
| 客户端预测的准星目标 | `native_raycast(distance)` 只在客户端、只打方块（`native_claimed_items.rs:136-160`） |

结论：hitscan 枪**可行但不便宜**：每个 tick 的每发子弹要自己走体素；而且服务端逐格读方块有开销（`native_block` 每次查 `world.block` + 注册表，`native_hooks.rs:11410-11414`），做不到 Java `Level.clip` 那种一次调用。

#### ⑤ 弹道 B：实体弹（可见飞行弹丸） —— **只能"雪球"，且伤害写死**

| Java | Horizon |
|---|---|
| 自定义 `EntityType<Bullet>` + 自写 `tick()` | **不可能**。内容 mod 的实体类型只能 `"template": "minecraft:snowball"` 或三种 mob（`docs/mods.md:390-399`） |
| 每发子弹设速度/重力/伤害/穿透 | 投掷型物理=雪球（0.03 重力、固定初速与散布），`damage` 是注册时的**一个常数**，伤害类型固定 `thrown` |
| `level.addFreshEntity(bullet)` | `native_summon(dimension, "tacz:bullet", pos, {Motion:[..], Owner:...})`：能指定位置/速度/归属（`entity_nbt.rs:3408-3428`），但**物理仍是雪球** |

可行替代：**`native_summon` 生成 vanilla 箭**（`minecraft:arrow` 在可召唤表里，`game/chat.rs:733`），NBT 带 `Motion`/`damage`/`crit`/`Owner`（`entity_nbt.rs:3167-3200`）。箭有重力、有速度伤害公式、能插在实体/方块上——比雪球更像"有弹道的子弹"，代价是它是箭（模型、拾取、`minecraft:arrow` 伤害类型）。

#### ⑥ 命中结算与伤害 —— **可以完全接管，这是最强的部分**

1. 先 opt-in：`native_hears_projectile_impacts(hears)`，否则服务器根本不保留飞行弹体的副本（`native_hooks.rs:9662-9669`）。
2. `native_projectile_impact(...)` 里 `canceled = true`：原版的伤害/击退/音效/插箭全部不发生（`native_hooks.rs:9690-9715`）。
3. 自己算伤害 → `native_hurt_entity(dimension, target, amount, "tacz:bullet", attacker)`：走 `/damage ... by <entity>` 的完整路径——护甲、效果、**无敌帧**、击退、死亡和死亡消息，而且**自定义伤害类型**（数据文件注册，`docs/mods.md:531-540`）会进 `damage_type` 标签/谓词，与 Java 自定义伤害类型等价（`docs/native-mods.md:3419`）。
4. 记得 `native_remove_entity(dimension, id)`——取消命中后弹体**不消失**，会继续飞（`docs/native-mods.md:1226`）。
5. 想要"近距离更高伤害/爆头"，在 3 里按命中点与实体 AABB 高度自己算即可（`at` 坐标由 hook 给出）。

**注意**：`native_hurt_entity` 遇到无敌帧会返回 false（同 vanilla `hurt` 语义），连发武器要自己处理（缩短无敌帧不行——那是全局的）。

#### ⑦ 弹药与物品栈写回 —— **只能下一个 tick 写，且只能写"携带中的栈"**

| Java | Horizon |
|---|---|
| `stack.shrink(1)` / `gun.set(AmmoComponent, n)` 当场生效 | hook 里只有 `&ItemStack`（clone），**改不了**（`use_hand.rs:208`；`native_hooks.rs:8197`） |
| `player.getInventory().setItem(slot, stack)` | `native_carried_stack(slot) -> Option<&mut ItemStack>`，**但只在 `native_inventory_tick` 的调用栈里有效**，而且每 tick 对每个非空槽跑一次（`native_hooks.rs:11952-11970`） |
| 任意时机改背包 | `native_set_inventory(uuid, kind, slots, selected)` 整包替换；官方要求从 `native_server_tick` 之类调用（文档明写"never while … a player's state is swapped in"，`docs/native-mods.md:2905`） |
| 给玩家发子弹 | `native_give(item, count)`（当前行动玩家）/ `native_give_stack(uuid, stack)` |

**落地模式**（这也是本地副本里那段 AK-47 探针没做到的）：开火 hook 里只写"待扣 1 发"的 mod 状态 + `claimed = true`；下一 tick `native_inventory_tick` 里用 `native_carried_stack(slot)` 把 `custom_data` 里的弹药减 1、`damage` 加 1。代价是**枪口状态与物品状态差 1 tick（50ms）**，连发时要自己维护"影子弹匣"避免超发。

可参考的现成探针：`native_hooks.rs:8198-8227` 有一段 `AK-47 probe`，用 `use_item` + `claimed` + `static AtomicU32` 模拟 30 发弹匣——它恰好暴露了问题：**弹药存在进程静态变量里，不在物品栈里**，所以退出重进/换枪就丢状态。

#### ⑧ 换弹、检视、开镜 —— **动画自己做，状态可存**

- 换弹键：同 ②，客户端 hook → payload。或者用"右键"语义：`use_item` + `use_duration`/`use_item_tick`（API 90/131）做"按住右键蓄力/装填"，松手 `release_using`。
- 换弹动画：第一人称手部有 `render_hand`（可取消）、`render_hand_pose`、`hand_drawn`（`native-hooks.json`），但**没有"接管整个第一人称模型"的 API**；TaCZ 那种独立枪械模型要靠 `native_draw_*` 自己画（客户端 helper：`native_draw_quad/cube/block/item`），或者用 `native_item_model_property` 换模型。
- 开镜（FOV/灵敏度）：客户端 hook 有，但要自己接。

#### ⑨ 音效、枪口火焰、弹壳

- 音效：`native_play_sound`（注册表内）—— 枪声要作为资源包/内容 mod 的 `sounds.json` 注册（`docs/native-mods.md:913` 提到客户端能听到 mod 定义的声音）。
- 枪口火焰：`native_flame_particle(at, soul)` 只有火焰一种（`native_hooks.rs:10644-10660`）；更花的粒子只能客户端自绘。
- 弹壳：`native_summon(dimension, "minecraft:item", pos, {Item:{id:"tacz:casing",count:1},Motion:[..]})`，或用 `native_set_item_entity` 改已有掉落物。

### 3.2 Horizon 现在做不到的事（本节最重要）

按"卡死程度"排序。每条都写清**缺什么、在哪能看到缺口**。

1. **没有"生成任意自定义弹射物"的能力。**
   缺：能注册实体类型 + 行为（tick/命中/伤害）的 API。
   证据：内容 mod 的实体类型只能复制模板（`docs/mods.md:390-399`）；`ProjectileKind` 是**封闭枚举**（`projectiles.rs:79-126`），mod 加不了新变体；`native_summon` 只按已注册 id 载入（`native_entities.rs:206-215`）。
   影响：枪的"弹丸"只能伪装成雪球/箭/投掷物。

2. **弹射物的伤害不能按发设置。**
   缺：`ThrownType.damage` 是注册时常量（`projectiles.rs:28-32`），`native_summon` 的 NBT 也没有"这一发伤害多少"的字段（箭有 `damage`，但那是箭的基础伤害，且仍是 `minecraft:arrow` 类型）。
   变通：只能取消命中后自己 `native_hurt_entity`（§3.1 ⑥）。

3. **`use_item` / `use_item_on` / `interact_entity` 的物品栈是只读的（而且是 clone）。**
   证据：`native_hooks.rs:8197`、`:8156`、`:2602`；上游 `use_hand.rs:208` 的 `.cloned()`。
   影响：所有"点击即改变手持物"的设计（扣弹、开保险、切射击模式、装消音器）都必须推迟到 `inventory_tick`。

4. **没有"设置物品冷却"的 helper。**
   证据：只有 `native_player_item_cooldown`（cancel）与 `release_using` 的 `used`（`docs/native-mods.md:1521,1216`）。
   影响：射速/TaCZ 式"射击间隔"要完全自管，并自己画 HUD。

5. **专用服务器读不到"空挥左键"。**
   证据：`player_arm_swing` 只在 `lan_actions.rs:2487`（guest 的 `Punch` 包）调用；`interaction_key` 依赖窗口（`docs/native-mods.md:1230`）；`player_input` 的 `flags` 只有移动位（`:1687`）。
   影响：**纯服务端枪械 mod 不成立**，必须客户端+服务端成对部署。

6. **服务端没有射线 API（方块和实体都没有）。**
   证据：`native_raycast` 仅客户端、沿视线、只方块（`native_claimed_items.rs:136-160`）；`native_read_columns` 是列读（`docs/native-mods.md:1208`）；`native_block(pos)` 是单格名（`native_hooks.rs:11410`）。
   影响：hitscan 要自己写体素 DDA + AABB 相交，性能和精度都由 mod 负责。

7. **爆炸的实体伤害不可改（方块与击退可以）。**
   证据：`native_explosion_detonate(dimension, center, source: Option<(u32,&str)>, blocks: &mut Vec<[i32;3]>)`（`native_hooks.rs:8511-8520`，注释 `:8506`）——`blocks` 可删可留（保住方块、不起火），`source` 只告诉你"谁炸的"，**"Entities are hurt as before"**（`docs/native-mods.md:3680-3681`）。击退速度可替换（`native_explosion_knockback` 的 `knockback_velocity: &mut [f64;3]`，`native_hooks.rs:8528-8546`）。不可改的只有**伤害数值与伤害类型**。
   影响：手雷/火箭筒的"自定义爆炸伤害曲线"做不到——要么放弃原版爆炸、用 `native_explode` 重建方块破坏 + `native_hurt_entity` 逐个结算实体，要么让原版爆炸照常结算伤害（只保留方块与击退的微调权）。

8. **不能直接"挥一次手/播一次手臂动画"给某个玩家。**
   `swing_arm` 只作为 claim 的副作用出现（`use_hand.rs:236-239`）；没有"让玩家挥手"的 helper。第三人称的枪械动作（换弹、拉栓）没有专用通道。

9. **物品损坏事件拿不到原栈。**
   `player_destroy_item(player,name,item,slot)` 只有物品 id 与槽位（`docs/native-mods.md:315`），不像 NeoForge 的 `PlayerDestroyItemEvent` 带 `ItemStack`——"枪炸膛时保留 NBT"需要自己在 `item_damaged` 里拦截。

10. **`native-hooks.json` 与 `docs/native-mods.md` 的契约描述都有失真，至少三处。**
    ① `item_damaged`：JSON 写 `"contract": "cancel"`，源码是 `amount: &mut i32, cancel: &mut bool`（`native_hooks.rs:9238-9247`）——`out` 只记了 `cancel`，漏了 `amount`。② `explosion_knockback`：JSON 写 `contract: "collect"`，源码是 `knockback_velocity: &mut [f64;3]`，**可以替换击退速度**（`native_hooks.rs:8528-8546`，API 374，`docs/native-mods.md:3682-3685` 正确）。③ `explosion_detonate`：`docs/native-mods.md:3680` 的参数表写作 `(dimension, center, blocks)`，实际还有 `source: Option<(u32, &str)>`（起爆的 TNT/苦力怕/火球/水晶及其类型），且 `blocks` 是 `&mut Vec`（`native_hooks.rs:8511-8520`）。
    结论：JSON 只是索引（人名与边），**可变性一律以 `native_hooks.rs` 的签名与 `dispatch_*` 形参为准**。我第一版就因为只信 JSON，把"爆炸击退可改"误写成"只能读"，已改正；detonate 的 `source` 参数与 `blocks: &mut Vec` 也是复核后才补上的（感谢 horizon-world-research 交叉核对）。

11. **原生 mod 的部署成本。**
    必须重编游戏（`docs/mods.md:24-27`），launcher 里显示 "Needs rebuild"（`docs/native-mods.md:1851`）；内容 mod 的实体类型在专用服务器"untested so far"（`docs/mods.md:402-403`）。
    影响：TaCZ 这种体量的移植 = 维护一个 Horizon fork，而不是发一个 jar。

## 4. 未证实清单

| # | 说法 | 现状 |
|---|---|---|
| 1 | Java 侧的具体数值（护甲公式系数、斧破盾 5 秒、暴击 ×1.5、箭的 `ceil(velocity*damage)`） | 本机无 Java 源码；这些是通识，且 Horizon 注释点名了对应 Java 方法。若要与 26.3 逐字对齐，需另取官方 mappings/源码核对 |
| 2 | `native_hurt_entity` 是否接受**任意**未注册的 `damage_type` 字符串、以及未知类型的行为 | 只读到文档（`docs/native-mods.md:3419`）说按 `/damage` 走；未读实现细节。建议用已注册的类型（`tacz:bullet` 数据文件） |
| 3 | `native_inventory_tick` 在**专用服务器**上是否对每个在线玩家分别换入状态 | 文档写"for every player of the world (the helpers read the acting one)"（`:366`），实现里只看到 `self.player` 的判断（`native_hooks.rs:11952-11957`）。多玩家下的行为需实测 |
| 4 | `native_carried_stack` 改动在**同一 tick 内**是否立刻同步给客户端 | 注释写"a count of 0 empties the slot at the end of `native_inventory_tick`"，其余改动何时下发未明说（`native_hooks.rs:10663-10668`） |
| 5 | 内容 mod 的投掷型实体在**专用服务器**上的表现 | `docs/mods.md:402-403` 自述 "Dedicated servers share that code, untested so far" |
| 6 | 箭 NBT 的 `damage` 是否能稳定控制每发伤害 | `arrow_from_nbt` 读 `damage`（`entity_nbt.rs:3196-3198`），但最终伤害还乘速度与暴击，未做端到端实测 |
| 7 | 1.8 战斗规则（`combatRules`）与 mod 的交互 | 文档只说"只在自己当服务器的世界生效"（`docs/pvp.md:130-140`），没说与 hook 的先后顺序 |
| 8 | `native_summon` 生成 `minecraft:arrow` 时 `LeftOwner`/`HasBeenShot` 的默认值是否会导致"刚生成就命中自己" | `arrow_from_nbt` 读 `LeftOwner`（`entity_nbt.rs:3199`），默认 false；是否需要 mod 显式置 1 未验证 |
| 9 | 第三方站点对 Horizon 战斗/模组的评价 | 本次未采信任何社区说法；§6 只列官方来源 |
| 10 | `README.md:142-148` 的"0 个玩家可见缺口" | 项目自述，其定义是"harness 覆盖范围内 0 缺口"，不等于"与 vanilla 无差异"（路线图 `:593-600` 仍列着战斗待办） |
| 11 | 爆炸曝光与 vanilla 是否**逐位**等价 | `seen_percent` 的采样网格、偏移、`RayBlockMode::Collider` 与 `CollisionContext::for_entity` 都照 `ServerExplosion.getSeenPercent` 写（`game/explosion.rs:246-300`），但我没有逐行核对 `clip_world` 的 Collider 语义与 Java `ClipContext.Block.COLLIDER` 完全一致；文档也自述 `getEntities` 顺序是近似。做爆炸/击退对比时应实测（感谢 horizon-world-research 指出） |
| 12 | 涉及实体的战斗链路**没有 harness 兜底** | 红石对比工具只比方块状态，物品/实体/TNT/下落方块不在 diff 范围（`docs/parity/redstone-diff.md:39-43`）。所以"发射器射箭命中实体""TNT 矿车链式引爆""爆炸把实体炸飞"只能靠手测或 mod 侧自测，不能引用 harness 结论 |

## 5. 参考来源

**本地源码（`third_party/horizon/`，源码实证）**

- `crates/horizon-client/src/game/native_hooks.rs`：`:1913`（`NativePlayer` 字段含 yaw/pitch）、`:2602`（`native_interact_entity`）、`:2792`（`native_interaction_key`）、`:5151`（`player_item_cooldown`）、`:5948`（`projectile_launch`）、`:7924`（`living_incoming_damage_v3`）、`:8156`（`use_item_on`）、`:8197`（`use_item`，含 `:8198-8227` 的 AK-47 探针）、`:8291`（`use_item_finish`）、`:8367`（`use_item_stop`）、`:8418`（`critical_hit`）、`:8442`（`release_using`）、`:8511`（`explosion_detonate`，含 `source` 与 `blocks: &mut Vec`）、`:8534`（`explosion_knockback`，注释自 `:8528`）、`:8571`（`attack_entity`）、`:8577`（`net_from_client`）、`:9238`（`item_damaged`）、`:9363`（`hurt_enemy`）、`:9376`（`inventory_tick`）、`:9471`（`living_incoming_damage`）、`:9662`（`hears_projectile_impacts`）、`:9690`（`projectile_impact`）、`:10644`（`flame_particle`）、`:10668`（`carried_stack`）、`:11410`（`native_block`）、`:11738`（`native_give`）、`:11952`（`inventory_ticks`）
- `crates/horizon-client/src/game/use_hand.rs:1-45,208-239`（右键全流程、clone、冷却门、claim）
- `crates/horizon-client/src/game/item_actions.rs:55-66`（`Hand::BOTH` 主手→副手）
- `crates/horizon-client/src/game/creatures.rs:5572-5708`（箭命中结算）
- `crates/horizon-client/src/game/explosion.rs:246-300`（`seen_percent` 曝光采样、`RayBlockMode::Collider`）
- `crates/horizon-client/src/game/combat.rs:1-6,47-53,177-215`（CombatTracker、`Stuck::add_arrow`）
- `crates/horizon-client/src/game/enchant_effects.rs:1-10,195,217`（附魔伤害/击退/横扫）
- `crates/horizon-client/src/game/chat.rs:733,891`（可召唤实体表、`sweeping_damage_ratio`）
- `crates/horizon-client/src/game/lan_actions.rs:2487`（`player_arm_swing` 仅 guest）
- `crates/horizon-client/src/game/native_entities.rs:206-266`（`native_summon`/`native_summon_with_uuid`）
- `crates/horizon-client/src/game/native_claimed_items.rs:136-160`（`native_raycast`/`native_view_hit`）
- `crates/horizon-client/src/attack_strength.rs:2,69-75,100-107`（攻速延迟、`0.2+s²·0.8`）
- `crates/horizon-client/src/projectiles.rs:1-6,28-32,74-126,207,451-480`（三种弹道物理、`ThrownType`、`ProjectileKind`、`Projectile::new`）
- `crates/horizon-client/src/entity_nbt.rs:3167-3200,3300-3428`（箭/投掷物的 `Motion`/`damage`/`Owner` 载入）
- `crates/horizon-client/src/health.rs:43-146,520-680`（伤害管线、盾牌阻挡、击退 hook、`HurtRecord`）
- `crates/horizon-client/src/item_data.rs:142,197,307-330,377-430`（`ItemStack` 与组件读写）
- `crates/horizon-items/src/items.rs:190,246-283,340-346,1303`（`blocks_attacks`、`ItemStack` 字段、属性修正）
- `crates/horizon-world/src/blocking_rules.rs:65`（`BlockingRules`）
- `crates/horizon-client/src/legacy_combat.rs`（1.8 战斗公式）

**本地文档（官方文档）**

- `docs/native-mods.md:218-226`（API 13 使用物品）、`:249-255`（API 21 右键方块）、`:294-300`（API 30 左键方块）、`:365-368`（API 39 物品行为）、`:378-382`（API 42 物品实体）、`:998-1000,1063`（堆叠上限）、`:1038,1216`（持续使用/释放）、`:1160,1176,1230`（鼠标/键盘/交互键）、`:1226`（API 136 命中）、`:1254`（`native_items`）、`:1321`（耐久）、`:1521`（物品冷却）、`:1637`（`arrow_loose`）、`:1681`（`player_arm_swing`）、`:1687`（`player_input`）、`:1741`（物品内嵌容器）、`:1761`（API 379 实体几何）、`:1813`（死亡掉落保背包）、`:2905`（`native_set_inventory`）、`:3419`（`native_hurt_entity`）、`:3680-3681`（爆炸只处理方块，且参数表漏 `source`）、`:3682-3685`（爆炸击退可替换，API 374）、`:4086-4094`（`native_explode`）
- `docs/mods.md:24-27`（原生 mod 需重编）、`:109,513`（内容 mod 可加的东西）、`:390-404`（实体类型只能复制模板）、`:531-540`（自定义伤害类型）
- `docs/pvp.md:130-160`（1.8 战斗规则 `combatRules`）
- `docs/parity/redstone-diff.md:39-43`（对比工具只比方块：实体/TNT/下落方块不在 diff 范围）
- `ROADMAP.md:377`（Java 代码不运行）、`:593-600`（战斗待办：`attack_knockback`、锤子 smash、host 击退来源）
- `README.md:20`（26.3、MIT）、`Cargo.toml:59`（`license = "MIT"`）
- `native-hooks.json`（434 hooks / 177 helpers；本文引用的 hook 名与 `cancellable`/`contract` 均出自此文件）

**官方站点**

- <https://playhorizon.dev/>（："The Minecraft: Java Edition 26.3 client and its game logic, rewritten in Rust"；"Horizon's code is MIT"；"players still find differences"）
- <https://github.com/horizon-rust/horizon>（仓库、issue 原始出处）
- <https://playhorizon.dev/hub>（路线图在线版，`ROADMAP.md:5` 指向）

**社区说法**

- 本次未采信任何社区说法。（第 09 篇已记录第三方站点多处与源码矛盾的例子，这里不再复述。）

## 6. 附：单机（LAN 房主）里哪些输入服务端看得见

M5l 想把「按 R 换弹」接进 gun mod，逐条核对后结论是**单机房主没有可用的按键载体**，只能走客户端钩子直接改进程内状态（仅单机成立）或专用服务器 + 模组消息。

| 入口 | 单机房主 | 证据 | 备注 |
|---|---|---|---|
| `key` / `input_key` / `mouse_button_pre` | **不确定** | 由 winit 事件派发（`native_hooks.rs:2729-2749`），无头客户端没有窗口；`horizon-ctl key` 是否走同一条路径未实测 | 窗口客户端可用；这是客户端半边的入口，不是服务端 |
| `player_swap_hands`（F 键） | **听不到** | 注释原文「Not heard: the same swap made in an open inventory … and the host of a LAN world」（`native_hooks.rs:8759-8767`） | 专用服务器的玩家能听到 |
| `player_toggle_sneak` | **听不到** | 「A guest's client changed sneaking」（`native_hooks.rs:4560-4562`） | 只对 guest |
| `native_net_send_to_server` | **报错** | 单机 `remote: None`（`game.rs:2880-2890`），函数返回 `Err("the server carries no mod messages")`（`native_net.rs:230-240`） | 模组消息只在多人成立 |
| `use_item` / `inventory_tick` / `attack_entity` | 可见 | 已有 M5c/M5j 的游戏内实证 | 枪的现有全部行为都建在这三个上 |

**对移植的含义**：扳机、换弹、开镜、切枪这些"一次性按键"在单机下没有服务端事件；`use_item` 之所以能用，是因为它是**游戏行为**而不是**输入**。所以要么接受「客户端钩子 + 进程内状态」（单机成立、多人不成立），要么上专用服务器并把输入通过模组消息上行。

