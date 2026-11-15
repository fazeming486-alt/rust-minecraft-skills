# 05 · M2 规划：美术资产链与 `animation_driver` 缺口

> 状态：v0.5 规划完成（2026-11-15）。执行顺序见 `orchestration/task-templates/m2.json` 与 `work/dispatch/index.json`。
> 本轮由**主 agent 规划 + 2 个调研子 agent 并行复核**产出；分工机制见 ADR 0007。

## 0. 一句话结论

M2 的难点不是「资产多」，而是**目标侧根本不接受 TaCZ 的核心资产格式**：Bedrock geometry、`*.animation.json`、`display/`、`index/`、`*.lua`、`.bbmodel` 都不是 Horizon 26.3 的 vanilla 资产类型，`.hmod` 不直接消费。叠加唯一 unbound 能力 `animation_driver`，M2 的主体工作是**格式等价转换 + 跨层契约对齐 + 临时渲染路径设计**，不是机械搬运。

> v0.6 更新：ADR 0008 修正合规边界后，M2 **可以真实读取资产数据文件并执行格式等价转换**（本地、非商用、不发布改编版），不再只做路径级规格差异分析。
>
> **v0.7 更新：M2 已执行完毕**。17 个任务包 / 4 wave 全部闭合（verdict = COMPLETE），5 个转换器 roundtrip 全闭合，10 个跨层切片已构建，三路 Horizon Rust 源码探针已落地。**执行结果、修正过的目标侧结论与未决风险一律以 `docs/06-m2-execution.md` 和 `docs/adr/0009` 为准**；本文保留为 v0.5 的规划记录，其中「只能做规格级差异分析」等表述已被 ADR 0008 / 0009 取代。

## 1. 合规前置（不可绕过）

`mods.toml` 是 `GPL3 / CC BY-NC-ND 4.0`：**代码 GPL-3.0、资产 CC BY-NC-ND 4.0**，两者分开判定。按 ADR 0008 的三维度模型，`policy-gate` 实测输出：

| scope | inspection | transformation | distribution |
|---|---|---|---|
| code | `full-inspection` | `port`（Rust 重写） | `local-only` |
| assets | **`full-inspection`** | **`technical-only`** | **`local-only`** |

**修正说明（v0.6）**：本文件 v0.5 版曾把资产判为 `oracle-only`、只许列路径，这是把「ND 禁止**分享**改编版」误当成「不能读、不能转」。CC 官方 deed 的措辞是「若你重混、轉換本素材…**則你不得散佈改作後的素材**」，CC 官方 QA 明确 *"Format-shifting alone is not an adaptation"*；Horizon `modpacks.md:131` local by default、`:141-142` 对 ND/NC 只是本地 port 给警告且从不发布、`:143-149` 禁止读的是 mod code 并允许 *"its own data files"*、`:153` 自述非法律意见。

因此 **M2 可以真实执行转换**：读取 `geo_models/*.json`、`*.animation.json`、`display/*.json`、`index/*.json`、PNG、OGG，做**语义不变的格式等价转换**（Bedrock geometry → 目标侧等价结构、动画时间轴 → 目标侧时间轴、贴图/音效必要的技术性重编码），产物只留 `work/`。

硬边界仍由任务包传导并受 `collect-results` 检查：`distribution: local-only`（不发布/不上传/不进发布链）、非商业、禁止 `creative_adaptation`（重绘、改模型造型、改写动画表现）。「是否属于技术性修改」不确定时 `review_required`。若要发布，须先取得权利人授权或换成自有资产。工程政策判断，非法律意见。

## 2. 真实输入规模（只读条目名统计）

| 项 | 数量 |
|---|---|
| jar 总文件 | 5567 |
| assets 总文件 | **4436** |
| 内置枪包 `assets/tacz/custom/tacz_default_gun/` | **4194（94.5%）** |
| 其中 `.ogg` / `.json` / `.png` / `.lua` | 1704 / 1454 / 969 / 66 |
| 枪包内 `assets/` 与 `data/` | 3389 / 803 |

按资产族（两个调研子 agent 独立统计，主 agent 复核）：

| 族 | 规模 | 目标侧可否原样迁移 |
|---|---:|---|
| 几何模型 `geo_models/**.json` + `models/bedrock/*.json` | 327 + 5 = **332** | ✗ Bedrock geometry 非 vanilla 类型 |
| 动画 `*.animation.json` | 71 + 2 = **73** | ✗ 非 vanilla 类型 |
| 贴图 `**/textures/**/*.png` | 969 + 110 = **1079** | ✓ png 可原样（16–512x、`.mcmeta`） |
| 音效 `.ogg` + `sounds.json` | 1704 + 8 = **1712** | ✓ `sounds.json` + `sounds/` |
| `display/**` | **236** | ✗ 客户端表现层，需转译 |
| `data/tacz/index/**` | **232** | ✗ 内容注册层，需命名空间转换 |
| 数据/配方/标签等 `data/**` | ~790 JSON | 部分 ✓（26.3 data-pack 格式） |
| `lang` / `shaders` / `lua` / `gui` | 42 / 13 / 66 / 7 | lang ✓；core shader 多数未跑；lua ✗ |
| `.bbmodel`（源码 `reserve repository`） | 6 个，121KB–9.7MB | ✗ 仅设计源文件 |

**Horizon `.hmod` 硬限制**（`docs/resource-packs.md`、`docs/mods.md`）：≤65536 文件 / 单文件 ≤16MiB / 总 ≤512MiB；`horizon-mod.toml` 未知键拒收；两个启用 mod 不得同 namespace；加注册项需重启。CEM 明确「no animations yet」「no per-bone textures」，资源包仅支持 2D 帧动画。

## 3. 目标侧能力：硬缺口与可用组合

**一处由子 agent 复核纠正的推断**：先前把 `roadmap/roadmap.json:712` 的 "set aside in favour of compatibility through the browser" 理解为「0.5 动画也搁置」。实际该条只针对 **whole-modpacks 总目标**；`docs/modpacks.md:183` 明确 0.5 是 **Planned / 今日状态「—」（未实现）**，shape 为「data models (Bedrock geometry + animations) + budgeted draw-list」。全库无 `bone` / `skeleton` / `geometry` / `armature` 项。**结论不变（未实现），但理由必须改**——已同步修正 ADR 0005、README、roadmap 与绑定表。

| 类别 | 可用 |
|---|---|
| helpers | `item_model`、`texture_sprites`、`draw_quad/cube/block/item`、`camera`、`play_local_sound`、`flame_particle`、`raycast` |
| 手部 hooks | `render_hand`（**cancel**, cancellable=true）、`render_hand_pose`（listen）、`hand_drawn`（listen）、`use_animation` |
| 相机/帧 | `camera_pose`、`compute_fov`、`compute_fov_modifier`、`camera_distance`、`camera_shake`、`frame`、`world_drawn`、`gui_render_post` |
| 模型 hooks | `standalone_models`（**collect**，登记静态模型）、`item_model_property`（**listen**，per-stack 布尔条件属性） |

`item_model_property` 只能回答 `minecraft:condition` 的布尔分支，**不能返回连续 float、插值或骨骼**；`standalone_models` 只登记/烘焙静态模型，不返回逐帧姿态。

### 硬缺口 = `animation_driver`

缺失的是**数据与驱动层**：骨骼/蒙皮/权重、动画状态机与插值混合、Bedrock geometry / GeckoLib 等价能力、budgeted draw-list（0.5 才有）。现有 hooks/helpers 无法等价构造，必须记为 capability gap，不得用 workaround 冒充已解决。

### 不依赖 0.5 的两阶段路径

**阶段 A · 逻辑闭环优先（可立即做）**
自维护 phase/tick 状态 → `item_model_property` 布尔分支 + `minecraft:condition` 离散切换静态模型 → `standalone_models` 注册 → `play_local_sound` / `flame_particle` 触发反馈。
限制：仅布尔分支、无插值/混合、模型 baked、状态需自行同步。

**阶段 B · 补表现（在 A 之上）**
`render_hand`(cancel) 屏蔽原手 → `render_hand_pose` 取 PoseStack → `frame` / `hand_drawn` 逐帧调 `draw_*`（push/pop/translate/rotate/scale）做分块姿态近似；`camera_pose` / `compute_fov*` 做 ADS；`gui_render_post` 画准星。
限制：无骨骼/蒙皮/权重，需逐块矩阵近似与每帧手算 easing；姿态/FOV hook 全是 listen 且无 out，只改事件字段，无动画输出通道。

## 4. 分工方案（主 agent 规划，子 agent 执行）

确定性评估 `tools/estimate_complexity.py` 对真实输入算出 **score = 0.4255 → band M → 2 workers → human_gate = true**，硬门槛 2 条（`capability_gap_count = 1`、`distribution == local-only`）。主要信号：`asset_count` 0.150、`unit_count` 0.080、`format_diversity` 0.056、`capability_gap_count` 0.050、`policy_strictness` 0.000。

> 合规修正前为 0.5255 / L / 4 workers（当时 `policy_strictness = 0.100` 来自资产 `oracle-only`）。**收紧解除后复杂度下降 0.1，说明虚增的合规成本本来就不该计入工作量**；`human_gate` 仍因能力缺口与不可发布而保持开启。

以下是 **v0.5 当时**的派发结构（12 个任务包 / 4 个 wave）；v0.7 已扩展为 17 个任务包，首波改为三路目标侧源码研读，见 `docs/06-m2-execution.md`：

| wave | 任务 | 并行 |
|---|---|---|
| 1 | `m2-01-inventory`、`m2-09-animation-gap`、`m2-11-policy-compliance` | 3 |
| 2 | `m2-02-geometry`、`03-animation`、`04-texture`、`05-audio`、`06-display-index`、`07-data-registry`、`08-loc-shader` | 7（轮询 4 worker） |
| 3 | `m2-10-contract-alignment`（主 agent） | 1 |
| 4 | `m2-12-verification`（主 agent） | 1 |

角色定义见 `orchestration/roles.json`；`can_parallel: false` 的合规监督、契约对齐、汇总验收固定交主 agent。任务包含 `policy_mode` / `allowed_actions` / `forbidden_actions` / `input_hash` / `acceptance`；子 agent 之间禁止通信，结果只写约定路径，由 `collect-results` 统一校验。

**复杂度不由子 agent 自评**：模型自评不可复现，会破坏「确定性归机器」地基。人工可覆盖但需记录理由。

## 5. 本轮两个调研子 agent 的实际产出

| 子 agent | 产出 | 价值 |
|---|---|---|
| 资产清单 | 7 个天然可并行分组、332 几何 / 73 动画 / 1079 贴图 / 1712 音效 / 236 display / 232 index、`.hmod` 格式清单与硬限制 | 把「美术资源整理」变成可派发的具名任务 |
| 动画缺口 | 完整 hook/helper 组合与 contract、0.5 状态纠偏、两阶段路径、硬缺口判定、collect/listen 语义边界 | 纠正了主 agent 对 roadmap 的过度推断，并给出可执行 workaround |

这两个 result 已作为 `work/dispatch/results/` 下的两篇调研报告归档（本地，不入库），并在 `reports/m2-collection.json` 中标记；其余 10 个任务为下一轮派发对象。

## 6. 交付物与验收

| 交付 | 验收 |
|---|---|
| 各族格式差异报告 + 格式等价转换产物（7 份，仅 `work/`） | 计数闭合、语义不变、明确可原样迁移/需转译、`local-only` 不发布 |
| `animation_driver` 缺口与两阶段方案 | 区分硬缺口与 workaround，每条附 Horizon 路径/行号 |
| 跨层契约 `shared_states` 用例 | 逻辑状态机 ↔ 动画状态机双向可查，不一致即失败 |
| 合规审查报告 | 所有 result 为 `local-only`，无发布/商用/创造性改编字段 |
| M2 验收清单 | 12 个任务各有 result 或明确阻塞原因 |

## 7. 风险与未决

- **最大风险**：0.5 未实现且不赌排期；阶段 B 的逐块矩阵近似只是 workaround，不能写成「已支持动画」。
- **发布风险**：ADR 0008 之后本地技术性转换可以做，但产物受 `local-only` 约束，只能本地验证，不能进入发布链或商用；若要发布须取得权利人授权或换成自有资产。这是当前最大的非技术约束。
- **未决**：`*.lua` 在目标侧无运行时（Horizon 脚本层 Later），66 个脚本的处置需单独决策；core shader 多数未跑（#13218）。
- **待 M3**：视觉快照与 `horizon-ctl` 自动验收需要可运行实例，M2 只设计用例不执行。
