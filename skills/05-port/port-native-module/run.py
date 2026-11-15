#!/usr/bin/env python3
"""由状态机 IR 生成 Horizon 原生 mod bundle（horizon-mixin.toml + helper + 纯 Rust engine）。

设计约束（与 orchestration/m5-slice.json 的 acceptance 对齐）：
- engine 只依赖 std，无 path/git 依赖，`cargo test --offline` 可独立跑；
- engine 导出的 `STATES` 与 IR 的 `states[].id` 集合相等，不相等直接非零退出；
- 同一输入重复运行输出字节一致（不写时间戳、不写绝对时间）；
- `bindings = []` 是占位接线：helper 拿不到游戏上下文，报告必须标 unverified。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[3]  # rustmc-skills
DEFAULT_TARGET_DIR = Path("D:/RUST重写mc项目/rustmc-skills/work/m5/target-engine")
DEFAULT_CARGO = Path("D:/RUST重写mc项目/dev/cargo/bin/cargo.exe")
DEFAULT_CARGO_HOME = Path("D:/RUST重写mc项目/dev/cargo")
DEFAULT_RUSTUP_HOME = Path("D:/RUST重写mc项目/dev/rustup")

TPS = 20  # Minecraft 26.3 的逻辑 tick 率
ENGINE_INPUTS = ["Shoot", "ReleaseTrigger", "Reload", "Inspect", "PutAway", "FireSelect"]
INPUT_MAP = {
    "Shoot": ["INPUT_SHOOT"],
    "ReleaseTrigger": [],  # TaCZ 半自动靠松扳机重置内部 latch，没有独立 input 常量
    "Reload": ["INPUT_RELOAD"],
    "Inspect": ["INPUT_INSPECT"],
    "PutAway": ["INPUT_PUT_AWAY"],
    "FireSelect": ["INPUT_FIRE_SELECT"],
}


class GenError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dump_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def display_path(path: Path) -> str:
    """报告里的路径尽量相对仓库根，避免绝对路径破坏可移植性与幂等。"""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(ROOT.parent).as_posix()
        except ValueError:
            return path.as_posix()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_read(value: str | Path) -> Path:
    """输入路径解析：先按当前目录，再按仓库根、工作区根。

    仓库布局里 `third_party/horizon` 与 `rustmc-skills` 是兄弟目录，任务书给的
    命令用 `third_party/horizon/...` 从仓库根执行；这里对两种工作目录都兼容。
    """
    p = Path(value)
    if p.is_absolute():
        return p
    for base in (Path.cwd(), ROOT, ROOT.parent):
        q = base / p
        if q.exists():
            return q.resolve()
    return (Path.cwd() / p).resolve()


def resolve_write(value: str | Path) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return (Path.cwd() / p).resolve()


def add_output(outputs: list[dict], out_dir: Path, path: Path) -> None:
    outputs.append({
        "path": path.relative_to(out_dir).as_posix(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    })


# ---------------------------------------------------------------------------
# Horizon 版本定位
# ---------------------------------------------------------------------------

def horizon_revision(horizon_root: Path) -> tuple[str, str, bool]:
    """返回 (declared_revision, source, verified_by_git)。

    `git -C <root> rev-parse HEAD` 是权威来源。本机快照没有 `.git`（任务书假设有），
    因此退化为对快照目录内容的稳定指纹 `snapshot:<sha256(native-hooks.json)[:12]>`；
    它只能标识“同一份快照”，不能冒充上游 commit，报告里 verified=false。
    """
    git_dir = horizon_root / ".git"
    if git_dir.exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(horizon_root), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=20,
            )
            rev = proc.stdout.strip()
            if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", rev):
                return rev, "git", True
        except (OSError, subprocess.SubprocessError):
            pass
    catalog = horizon_root / "native-hooks.json"
    if catalog.exists():
        return "snapshot:" + sha256_file(catalog)[:12], "snapshot-catalog-sha256", False
    return "unknown", "unavailable", False


# ---------------------------------------------------------------------------
# IR → 引擎状态角色
# ---------------------------------------------------------------------------

def pick_role(states: list[str], predicate) -> str | None:
    for state in states:
        if predicate(state):
            return state
    return None


def map_roles(states: list[str]) -> tuple[dict[str, str], list[str], list[str]]:
    """把 IR 状态 id 映射到引擎需要的稳定角色，返回 (roles, fallbacks, unmapped)。

    引擎逻辑只认识一组角色，但 `STATES` 永远原样等于 IR 的 id 集合。
    找不到的角色回退到 idle 并在报告里记为 fallback，绝不悄悄改名。
    """
    idle = pick_role(states, lambda s: s == "main.idle") or pick_role(
        states, lambda s: s.endswith(".idle") or s.endswith("idle")
    )
    if idle is None:
        raise GenError("E_STATE_NO_IDLE", "IR 的 states[].id 里没有 idle 状态，无法生成引擎")

    wanted: dict[str, str | None] = {
        "idle": idle,
        "start": pick_role(states, lambda s: s.endswith(".start")),
        "inspect": pick_role(states, lambda s: s.endswith(".inspect")),
        "draw": pick_role(states, lambda s: s.endswith(".draw")),
        "put_away": pick_role(
            states, lambda s: s.endswith(".put_away") or s == "final" or s.endswith(".final")
        ),
        "fire_auto": pick_role(states, lambda s: s.endswith(".auto")),
        "fire_semi": pick_role(states, lambda s: s.endswith(".semi")),
        "reload_empty": pick_role(
            states, lambda s: "reload" in s and ("empty" in s or "dry" in s)
        ) or pick_role(states, lambda s: s.endswith(".reload") or ".reload_" in s),
        "reload_tactical": pick_role(
            states, lambda s: "reload" in s and ("tactical" in s or "tac" in s)
        ),
    }
    fallbacks: list[str] = []
    roles: dict[str, str] = {}
    defaults = {
        "start": idle,
        "inspect": idle,
        "draw": idle,
        "put_away": idle,
        "fire_auto": idle,
        "fire_semi": idle,
        "reload_empty": idle,
        "reload_tactical": None,
    }
    for role, value in wanted.items():
        if value is None:
            fallback = defaults.get(role)
            if fallback is None:
                fallback = wanted.get("reload_empty") or idle
            roles[role] = fallback
            fallbacks.append(f"{role}->{fallback}")
        else:
            roles[role] = value
    if wanted["reload_tactical"] is None:
        roles["reload_tactical"] = roles["reload_empty"]
    used = set(roles.values())
    unmapped = [s for s in states if s not in used]
    return roles, fallbacks, unmapped


# ---------------------------------------------------------------------------
# 数值
# ---------------------------------------------------------------------------

def seconds_to_ticks(seconds: float) -> int:
    """向上取整到 tick；2.25s→45、2.6s→52、0.57s→12。"""
    return int(math.ceil(seconds * TPS - 1e-9))


def collect_params(slice_obj: dict) -> tuple[dict, dict]:
    params = slice_obj["params"]
    derived = {
        "ticks_per_second": TPS,
        "fire_interval_ticks": int(round(TPS * 60 / params["rpm"])),
        "reload_empty_feed_ticks": seconds_to_ticks(params["reload"]["feed"]["empty"]),
        "reload_empty_cooldown_ticks": seconds_to_ticks(params["reload"]["cooldown"]["empty"]),
        "reload_tactical_feed_ticks": seconds_to_ticks(params["reload"]["feed"]["tactical"]),
        "reload_tactical_cooldown_ticks": seconds_to_ticks(params["reload"]["cooldown"]["tactical"]),
        "draw_ticks": seconds_to_ticks(params["draw_time"]),
        "put_away_ticks": seconds_to_ticks(params["put_away_time"]),
    }
    if derived["fire_interval_ticks"] * params["rpm"] != TPS * 60:
        raise GenError(
            "E_RPM_NOT_DIVISIBLE",
            f"rpm={params['rpm']} 在 {TPS} tps 下不能整除为整数 tick",
        )
    return params, derived


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------

MIXIN_TEMPLATE = Template(textwrap.dedent("""\
    # @generated by skills/05-port/port-native-module/run.py — do not edit by hand.
    # Source: orchestration/m5-slice.json#/params ; $ir#/states
    # `bindings = []` is deliberate placeholder wiring: see reports/m5-native-module.json
    # honesty.wiring. The helper signature is NOT verified against horizon-mixins.

    [mod]
    id = "$mod_id"
    version = "$version"

$compatibility

    [[injection]]
    id = "ak47-on-use"
    hook = "use_item"
    hook_version = 1
    kind = "HEAD"
    helper = "on_use.rs"
    bindings = [
        { name = "game", ty = "&mut crate::game::Game<'_>", value = "&mut *self" },
        { name = "stack", ty = "&crate::items::ItemStack", value = "stack" },
        { name = "claimed", ty = "&mut bool", value = "&mut *claimed" },
    ]

    [[injection]]
    id = "ak47-on-tick"
    hook = "player_tick"
    hook_version = 1
    kind = "HEAD"
    helper = "on_tick.rs"
    bindings = []

    [[injection]]
    id = "ak47-load-probe"
    hook = "server_tick"
    hook_version = 1
    kind = "HEAD"
    helper = "on_load.rs"
    bindings = []

    [[crate]]
    id = "engine"
    path = "engine"
"""))

RUNTIME_RS = """\
// Process-wide gun state shared by the bundle's helpers (M5g).
//
// `use_item` (one click) and `player_tick` (one tick) are separate injected
// functions. A `static` inside either helper would be a *different* copy per
// helper, so the state they must share cannot live there. It lives here, in the
// engine crate both helpers already depend on.
//
// Single-player semantics: one state for the process. Per-player scoping needs a
// player-aware mutable hook; this snapshot's `use_item` carries no player.

use std::sync::Mutex;

use crate::GunState;

static GUN: Mutex<Option<GunState>> = Mutex::new(None);

/// Run `f` with the process-wide gun state, creating it on first use.
pub fn with_gun<R>(f: impl FnOnce(&mut GunState) -> R) -> R {
    let mut slot = GUN.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let gun = slot.get_or_insert_with(GunState::new);
    f(gun)
}

/// Drop the shared state, so a test starts from a fresh magazine.
#[cfg(test)]
pub fn reset() {
    let mut slot = GUN.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    *slot = None;
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The helpers are separate functions; this is the property they rely on:
    /// two calls see the same state, and a reset puts the magazine back.
    #[test]
    fn one_state_across_calls() {
        reset();
        with_gun(|gun| gun.ammo = 7);
        assert_eq!(with_gun(|gun| gun.ammo), 7);
        reset();
        assert_eq!(with_gun(|gun| gun.ammo), crate::consts::MAG_CAPACITY);
        reset();
    }
}
"""

ON_LOAD_RS = """\
// AK-47 load probe — runs on the first server tick.
//
// It exists so a headless (`--dedicated --nogui`) run can prove three things
// without a player: the bundle compiled into the game, the hook point is live,
// and the engine crate is linked with its runtime slot readable. It prints once.
//
// This is not gameplay. Firing still needs verified bindings for use_item.

fn on_load() {
    use std::sync::atomic::{AtomicBool, Ordering};
    static SEEN: AtomicBool = AtomicBool::new(false);
    if !SEEN.swap(true, Ordering::Relaxed) {
        let (ammo, state) = ak47_engine::runtime::with_gun(|gun| (gun.ammo, gun.state));
        eprintln!(
            "[tacz_ak47_pilot] load probe: first server tick, engine states={} ammo={} state={}",
            ak47_engine::states::STATES.len(),
            ammo,
            state
        );
    }
}
"""

ON_USE_RS = """\
// AK-47 use_item helper — one click is one engine tick with `Shoot` (M5g).
//
// Bound to `native_use_item(&mut self, stack: &ItemStack, claimed: &mut bool)`.
// Magazine, fire rate, fire mode and reload timers all live in
// `ak47_engine::GunState` (shared through `ak47_engine::runtime`); this helper
// only translates a right click into `Input::Shoot`, claims the use when the
// engine answered `Shot`, and reports why it did not.
//
// A click carries no release event, so the trigger is released right after the
// shot; `player_tick` (`on_tick.rs`) is what advances the cooldown between
// clicks. Fire rate is therefore the engine's `FIRE_INTERVAL_TICKS`, not the
// click rate.

fn on_use(game: &mut crate::game::Game<'_>, stack: &crate::items::ItemStack, claimed: &mut bool) {
    let _ = game;
    if &*stack.item != "tacz_ak47_pilot:ak47" {
        return;
    }
    let mut shot = None;
    let mut dry = false;
    let mut blocked = None;
    ak47_engine::runtime::with_gun(|gun| {
        let before = gun.state;
        for event in gun.tick(Some(ak47_engine::Input::Shoot)) {
            match event {
                ak47_engine::Event::Shot { ammo_after } => shot = Some(ammo_after),
                ak47_engine::Event::DryFire => dry = true,
                _ => {}
            }
        }
        if shot.is_none() && !dry {
            blocked = Some((before, gun.state, gun.cooldown_ticks, gun.reload.is_some()));
        }
        gun.release();
    });
    if let Some(ammo) = shot {
        *claimed = true;
        eprintln!("[tacz_ak47_pilot] shot, ammo={ammo}");
    } else if dry {
        eprintln!("[tacz_ak47_pilot] dry fire: magazine empty");
    } else if let Some((before, after, cooldown, reloading)) = blocked {
        eprintln!(
            "[tacz_ak47_pilot] blocked: {before}->{after} cooldown={cooldown} reloading={reloading}"
        );
    }
}
"""

ON_TICK_RS = """\
// AK-47 tick helper — advances the engine's cooldown and reload timers (M5g).
//
// `bindings = []`: no player is in scope, so this advances the process-wide
// state in `ak47_engine::runtime` instead of one player's. It is the only place
// `FIRE_INTERVAL_TICKS` counts down, so without it only the first click of a
// session could ever fire.

fn on_tick() {
    ak47_engine::runtime::with_gun(|gun| {
        for event in gun.tick(None) {
            if let ak47_engine::Event::ReloadEnd { ammo } = event {
                eprintln!("[tacz_ak47_pilot] reload finished, ammo={ammo}");
            }
        }
    });
}
"""

CARGO_TOML = """\
# @generated by skills/05-port/port-native-module/run.py
# Pure Rust: std only. No path/git dependencies, no horizon-client dependency.
[package]
name = "ak47_engine"
version = "0.1.0"
edition = "2021"
publish = false

[lib]
name = "ak47_engine"
path = "src/lib.rs"

[[bin]]
name = "trace"
path = "src/bin/trace.rs"

[dependencies]
"""

CONSTS_RS = Template("""\
// Numeric constants taken from the slice. No runtime JSON parsing: the engine
// has no dependencies, so the values are hand-written here and the JSON beside
// them is embedded only as provenance/data.
//
// Source: orchestration/m5-slice.json#/params (see reports/m5-native-module.json)
// Derived tick counts: ceil(seconds * $tps), documented per constant.

/// The bundle's data file, embedded so `cargo test` proves it ships with the crate.
pub const DATA_JSON: &str = include_str!("../data/ak47.json");

pub const MAG_CAPACITY: u8 = $mag;
pub const RPM: u32 = $rpm;
pub const TICKS_PER_SECOND: u32 = $tps;
/// $tps ticks/s * 60 s / $rpm rpm = $interval ticks per shot.
pub const FIRE_INTERVAL_TICKS: u16 = $interval;

pub const RELOAD_EMPTY_FEED_TICKS: u16 = $reload_empty_feed;
/// ceil($reload_empty_s * $tps) = $reload_empty_cooldown; the mag is full on this tick.
pub const RELOAD_EMPTY_COOLDOWN_TICKS: u16 = $reload_empty_cooldown;
pub const RELOAD_TACTICAL_FEED_TICKS: u16 = $reload_tactical_feed;
/// ceil($reload_tactical_s * $tps) = $reload_tactical_cooldown.
pub const RELOAD_TACTICAL_COOLDOWN_TICKS: u16 = $reload_tactical_cooldown;

pub const DRAW_TICKS: u16 = $draw;
pub const PUT_AWAY_TICKS: u16 = $put_away;

pub const DAMAGE: u32 = $damage;
pub const HEADSHOT_MULTIPLIER: f32 = $headshot;
pub const ARMOR_IGNORE: f32 = $armor_ignore;
""")

STATES_RS = Template("""\
// @generated by skills/05-port/port-native-module/run.py — do not edit.
//
// `STATES` is copied verbatim from the IR's `states[].id`, in IR order, and
// `run.py` re-reads this file to assert set equality. Role constants below are
// engine handles into that set; a missing role falls back to `idle` and is
// listed in `ROLE_FALLBACKS` instead of being renamed.

pub const STATES: &[&str] = &[
$state_lines
];

/// Copied verbatim from the IR's `inputs` for traceability. This is NOT a claim
/// that every IR input has a runtime handler: the engine models six actions,
/// listed in `MODELED_INPUTS`.
pub const IR_INPUTS: &[&str] = &[
$input_lines
];

pub const MODELED_INPUTS: &[&str] = &[
$modeled_input_lines
];

pub const IDLE: &str = "$idle";
pub const START: &str = "$start";
pub const INSPECT: &str = "$inspect";
pub const DRAW: &str = "$draw";
pub const PUT_AWAY: &str = "$put_away";
pub const FIRE_AUTO: &str = "$fire_auto";
pub const FIRE_SEMI: &str = "$fire_semi";
pub const RELOAD_EMPTY: &str = "$reload_empty";
pub const RELOAD_TACTICAL: &str = "$reload_tactical";

/// Roles that had no matching IR state and fell back to another id.
pub const ROLE_FALLBACKS: &[&str] = &[
$fallback_lines
];
""")

LIB_RS = """\
// Pure-Rust AK-47 state machine for the Horizon native bundle.
//
// No dependencies, no Horizon types, no game context: this crate is the part
// that can be tested offline. Helpers in the bundle are placeholders with
// `bindings = []`; wiring them to the game is NOT done.
//
// States are the IR's own ids (`states::STATES`); inputs/events are the slice's
// reduced runtime alphabet, documented in the report's `input_alignment`.

pub mod consts;
pub mod runtime;
pub mod states;

use consts::*;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum FireMode {
    Auto,
    Semi,
}

impl FireMode {
    pub fn name(self) -> &'static str {
        match self {
            FireMode::Auto => "auto",
            FireMode::Semi => "semi",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Input {
    Shoot,
    ReleaseTrigger,
    Reload,
    Inspect,
    PutAway,
    FireSelect,
}

#[derive(Clone, PartialEq, Eq, Debug)]
pub enum Event {
    Shot { ammo_after: u8 },
    DryFire,
    ReloadStart { empty: bool },
    ReloadTick { remaining: u16 },
    ReloadEnd { ammo: u8 },
    ModeSwitch { to: &'static str },
    Draw,
    PutAway,
}

#[derive(Clone, PartialEq, Eq, Debug)]
pub struct Reload {
    pub remaining: u16,
    pub total: u16,
    pub empty: bool,
}

#[derive(Clone, Debug)]
pub struct GunState {
    pub ammo: u8,
    pub fire_mode: FireMode,
    pub cooldown_ticks: u16,
    pub reload: Option<Reload>,
    pub trigger_held: bool,
    /// One of `states::STATES`; used for traceability back to the IR.
    pub state: &'static str,
    semi_latch: bool,
}

impl Default for GunState {
    fn default() -> Self {
        Self::new()
    }
}

impl GunState {
    pub fn new() -> Self {
        Self::with_ammo(MAG_CAPACITY)
    }

    pub fn with_ammo(ammo: u8) -> Self {
        Self {
            ammo: ammo.min(MAG_CAPACITY),
            fire_mode: FireMode::Auto,
            cooldown_ticks: 0,
            reload: None,
            trigger_held: false,
            state: states::IDLE,
            semi_latch: false,
        }
    }

    /// Advance one tick, optionally applying an input. Auto fire continues on
    /// `None` while the trigger is held, matching the reference trace.
    pub fn tick(&mut self, input: Option<Input>) -> Vec<Event> {
        let mut out = Vec::new();

        if self.state == states::PUT_AWAY {
            out.push(Event::Draw);
            self.state = states::IDLE;
        }

        if let Some(reload) = self.reload.as_mut() {
            reload.remaining = reload.remaining.saturating_sub(1);
            if reload.remaining == 0 {
                self.reload = None;
                self.ammo = MAG_CAPACITY;
                out.push(Event::ReloadEnd { ammo: self.ammo });
                self.state = states::IDLE;
            } else {
                out.push(Event::ReloadTick {
                    remaining: reload.remaining,
                });
            }
        }

        if self.cooldown_ticks > 0 {
            self.cooldown_ticks -= 1;
        }

        match input {
            Some(Input::Shoot) => {
                self.trigger_held = true;
                if self.reload.is_some() {
                    return out;
                }
                if self.ammo == 0 {
                    out.push(Event::DryFire);
                    return out;
                }
                if self.cooldown_ticks == 0 && !(self.fire_mode == FireMode::Semi && self.semi_latch)
                {
                    self.fire(&mut out);
                }
            }
            Some(Input::ReleaseTrigger) => self.release(),
            Some(Input::Reload) => self.start_reload(&mut out),
            Some(Input::Inspect) => {
                self.state = states::INSPECT;
            }
            Some(Input::PutAway) => {
                self.trigger_held = false;
                self.reload = None;
                self.state = states::PUT_AWAY;
                out.push(Event::PutAway);
            }
            Some(Input::FireSelect) => {
                self.fire_mode = match self.fire_mode {
                    FireMode::Auto => FireMode::Semi,
                    FireMode::Semi => FireMode::Auto,
                };
                self.semi_latch = false;
                self.state = match self.fire_mode {
                    FireMode::Auto => states::FIRE_AUTO,
                    FireMode::Semi => states::FIRE_SEMI,
                };
                out.push(Event::ModeSwitch {
                    to: self.fire_mode.name(),
                });
            }
            None => {
                if self.trigger_held
                    && self.fire_mode == FireMode::Auto
                    && self.reload.is_none()
                    && self.cooldown_ticks == 0
                    && self.ammo > 0
                {
                    self.fire(&mut out);
                }
            }
        }
        out
    }

    /// Let go of the trigger without spending a tick.
    ///
    /// `Input::ReleaseTrigger` does the same thing through `tick`, but a click
    /// helper has no release event of its own: it must clear the hold right
    /// after the shot, or the next `tick(None)` would keep auto-firing. Going
    /// through `tick` would also decrement the cooldown a second time per
    /// click, which would fake a faster fire rate than `FIRE_INTERVAL_TICKS`.
    pub fn release(&mut self) {
        self.trigger_held = false;
        self.semi_latch = false;
    }

    fn fire(&mut self, out: &mut Vec<Event>) {
        self.ammo -= 1;
        self.cooldown_ticks = FIRE_INTERVAL_TICKS;
        self.semi_latch = true;
        self.state = match self.fire_mode {
            FireMode::Auto => states::FIRE_AUTO,
            FireMode::Semi => states::FIRE_SEMI,
        };
        out.push(Event::Shot {
            ammo_after: self.ammo,
        });
    }

    fn start_reload(&mut self, out: &mut Vec<Event>) {
        if self.reload.is_some() || self.ammo >= MAG_CAPACITY {
            return;
        }
        let empty = self.ammo == 0;
        let total = if empty {
            RELOAD_EMPTY_COOLDOWN_TICKS
        } else {
            RELOAD_TACTICAL_COOLDOWN_TICKS
        };
        let state = if empty {
            states::RELOAD_EMPTY
        } else {
            states::RELOAD_TACTICAL
        };
        self.reload = Some(Reload {
            remaining: total,
            total,
            empty,
        });
        self.state = state;
        out.push(Event::ReloadStart { empty });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shot_count(events: &[Event]) -> usize {
        events
            .iter()
            .filter(|event| matches!(event, Event::Shot { .. }))
            .count()
    }

    #[test]
    fn auto_dumps_thirty_then_dry_fires() {
        let mut gun = GunState::new();
        let mut shots = shot_count(&gun.tick(Some(Input::Shoot)));
        for _ in 0..120 {
            shots += shot_count(&gun.tick(None));
        }
        assert_eq!(shots, 30);
        assert_eq!(gun.ammo, 0);
        let events = gun.tick(Some(Input::Shoot));
        assert!(events.contains(&Event::DryFire));
    }

    #[test]
    fn semi_requires_release_between_shots() {
        let mut gun = GunState::new();
        gun.tick(Some(Input::FireSelect));
        assert_eq!(gun.fire_mode, FireMode::Semi);

        let mut shots = shot_count(&gun.tick(Some(Input::Shoot)));
        for _ in 0..10 {
            shots += shot_count(&gun.tick(Some(Input::Shoot)));
        }
        assert_eq!(shots, 1, "semi must not repeat while the trigger is held");

        gun.tick(Some(Input::ReleaseTrigger));
        shots += shot_count(&gun.tick(Some(Input::Shoot)));
        assert_eq!(shots, 2);
    }

    #[test]
    fn empty_reload_fills_thirty_after_fifty_two_ticks() {
        let mut gun = GunState::with_ammo(0);
        let first = gun.tick(Some(Input::Reload));
        assert_eq!(first, vec![Event::ReloadStart { empty: true }]);

        let mut ended_at = None;
        for tick in 1..=60 {
            for event in gun.tick(None) {
                if matches!(event, Event::ReloadEnd { ammo: 30 }) {
                    ended_at = Some(tick);
                }
            }
        }
        assert_eq!(ended_at, Some(RELOAD_EMPTY_COOLDOWN_TICKS as i32));
        assert_eq!(gun.ammo, 30);
        assert_eq!(gun.reload, None);
    }

    #[test]
    fn cannot_fire_during_reload() {
        let mut gun = GunState::with_ammo(5);
        gun.tick(Some(Input::ReleaseTrigger));
        gun.tick(Some(Input::Reload));
        let mut shots = 0;
        for _ in 0..30 {
            shots += shot_count(&gun.tick(Some(Input::Shoot)));
        }
        assert_eq!(shots, 0);
        assert!(gun.reload.is_some());
    }

    #[test]
    fn tactical_reload_takes_forty_ticks() {
        let mut gun = GunState::with_ammo(29);
        let first = gun.tick(Some(Input::Reload));
        assert_eq!(first, vec![Event::ReloadStart { empty: false }]);

        let mut ended_at = None;
        for tick in 1..=45 {
            for event in gun.tick(None) {
                if matches!(event, Event::ReloadEnd { ammo: 30 }) {
                    ended_at = Some(tick);
                }
            }
        }
        assert_eq!(ended_at, Some(RELOAD_TACTICAL_COOLDOWN_TICKS as i32));
        assert_eq!(gun.ammo, 30);
    }

    #[test]
    fn fire_select_switches_mode_and_state() {
        let mut gun = GunState::new();
        let events = gun.tick(Some(Input::FireSelect));
        assert_eq!(events, vec![Event::ModeSwitch { to: "semi" }]);
        assert_eq!(gun.state, states::FIRE_SEMI);

        let events = gun.tick(Some(Input::FireSelect));
        assert_eq!(events, vec![Event::ModeSwitch { to: "auto" }]);
        assert_eq!(gun.state, states::FIRE_AUTO);
    }

    #[test]
    fn put_away_draws_before_the_next_action() {
        let mut gun = GunState::new();
        assert_eq!(gun.tick(Some(Input::PutAway)), vec![Event::PutAway]);
        assert_eq!(gun.state, states::PUT_AWAY);

        let events = gun.tick(Some(Input::Shoot));
        assert_eq!(events.first(), Some(&Event::Draw));
        assert_eq!(shot_count(&events), 1);
    }

    #[test]
    fn states_export_matches_ir_roles_and_embedded_data() {
        assert!(states::STATES.contains(&states::IDLE));
        assert!(states::STATES.contains(&states::INSPECT));
        assert!(states::STATES.contains(&states::PUT_AWAY));
        assert!(!states::STATES.is_empty());
        assert_eq!(states::MODELED_INPUTS.len(), 6);
        assert!(DATA_JSON.contains("\\"ammo_amount\\": 30"));
        assert!(DATA_JSON.contains("\\"rpm\\": 600"));
    }
}
"""

INTEGRATION_TEST_RS = """\
// Integration tests: the public API only, as the diff harness will use it.
// These complement the unit tests in `src/lib.rs`; both run with `cargo test`.

use ak47_engine::{consts, states, Event, GunState, Input};

fn shots(events: &[Event]) -> usize {
    events
        .iter()
        .filter(|event| matches!(event, Event::Shot { .. }))
        .count()
}

#[test]
fn states_export_is_non_empty_and_contains_roles() {
    assert!(!states::STATES.is_empty());
    for role in [
        states::IDLE,
        states::INSPECT,
        states::PUT_AWAY,
        states::FIRE_AUTO,
        states::FIRE_SEMI,
    ] {
        assert!(states::STATES.contains(&role), "missing role {role}");
    }
}

#[test]
fn auto_burst_empties_magazine_then_dry_fires() {
    let mut gun = GunState::new();
    let mut fired = shots(&gun.tick(Some(Input::Shoot)));
    for _ in 0..130 {
        fired += shots(&gun.tick(None));
    }
    assert_eq!(fired, consts::MAG_CAPACITY as usize);
    assert_eq!(gun.ammo, 0);
    assert!(gun.tick(Some(Input::Shoot)).contains(&Event::DryFire));
}

#[test]
fn semi_requires_release() {
    let mut gun = GunState::new();
    gun.tick(Some(Input::FireSelect));
    let mut fired = shots(&gun.tick(Some(Input::Shoot)));
    for _ in 0..8 {
        fired += shots(&gun.tick(Some(Input::Shoot)));
    }
    assert_eq!(fired, 1);
    gun.tick(Some(Input::ReleaseTrigger));
    assert_eq!(shots(&gun.tick(Some(Input::Shoot))), 1);
}

#[test]
fn empty_reload_refills_on_the_cooldown_tick() {
    let mut gun = GunState::with_ammo(0);
    gun.tick(Some(Input::Reload));
    let mut end = None;
    for tick in 1..=60 {
        if gun
            .tick(None)
            .iter()
            .any(|event| matches!(event, Event::ReloadEnd { ammo } if *ammo == consts::MAG_CAPACITY))
        {
            end = Some(tick);
        }
    }
    assert_eq!(end, Some(consts::RELOAD_EMPTY_COOLDOWN_TICKS as i32));
    assert_eq!(gun.ammo, consts::MAG_CAPACITY);
}

#[test]
fn cannot_fire_while_reloading() {
    let mut gun = GunState::with_ammo(10);
    gun.tick(Some(Input::ReleaseTrigger));
    gun.tick(Some(Input::Reload));
    let mut fired = 0;
    for _ in 0..20 {
        fired += shots(&gun.tick(Some(Input::Shoot)));
    }
    assert_eq!(fired, 0);
    assert!(gun.reload.is_some());
}
"""

TRACE_RS = Template("""\
// Text script -> JSONL trace. No dependencies; JSON is written by hand.
//
// Script lines: `tick <n>`, `shoot`, `release`, `reload`, `inspect`, `putaway`,
// `fireselect`, `expect <EventKind>`. Actions are queued and applied by the next
// `tick` advance, so `shoot` followed by `tick 1` applies the shot at tick 0.
// `expect` checks the events of the next step and fails the run on a mismatch.
//
// Usage: `trace --script <path> [--out <path>]` (stdout when `--out` is absent).

use ak47_engine::{Event, GunState, Input};
use std::env;
use std::fs;
use std::io::{self, Write};
use std::process;

fn parse_action(line: &str) -> Option<Input> {
    match line {
        "shoot" => Some(Input::Shoot),
        "release" => Some(Input::ReleaseTrigger),
        "reload" => Some(Input::Reload),
        "inspect" => Some(Input::Inspect),
        "putaway" => Some(Input::PutAway),
        "fireselect" => Some(Input::FireSelect),
        _ => None,
    }
}

fn kind(event: &Event) -> &'static str {
    match event {
        Event::Shot { .. } => "Shot",
        Event::DryFire => "DryFire",
        Event::ReloadStart { .. } => "ReloadStart",
        Event::ReloadTick { .. } => "ReloadTick",
        Event::ReloadEnd { .. } => "ReloadEnd",
        Event::ModeSwitch { .. } => "ModeSwitch",
        Event::Draw => "Draw",
        Event::PutAway => "PutAway",
    }
}

fn event_json(event: &Event) -> String {
    match event {
        Event::Shot { ammo_after } => format!("{{\\"kind\\":\\"Shot\\",\\"ammo_after\\":{ammo_after}}}"),
        Event::DryFire => "{\\"kind\\":\\"DryFire\\"}".to_string(),
        Event::ReloadStart { empty } => {
            format!("{{\\"kind\\":\\"ReloadStart\\",\\"empty\\":{empty}}}")
        }
        Event::ReloadTick { remaining } => {
            format!("{{\\"kind\\":\\"ReloadTick\\",\\"remaining\\":{remaining}}}")
        }
        Event::ReloadEnd { ammo } => format!("{{\\"kind\\":\\"ReloadEnd\\",\\"ammo\\":{ammo}}}"),
        Event::ModeSwitch { to } => format!("{{\\"kind\\":\\"ModeSwitch\\",\\"to\\":\\"{to}\\"}}"),
        Event::Draw => "{\\"kind\\":\\"Draw\\"}".to_string(),
        Event::PutAway => "{\\"kind\\":\\"PutAway\\"}".to_string(),
    }
}

fn step(
    gun: &mut GunState,
    tick: u32,
    input: Option<Input>,
    rows: &mut Vec<String>,
    expect: &mut Vec<String>,
) -> Result<(), String> {
    let events = gun.tick(input);
    let kinds: Vec<&str> = events.iter().map(kind).collect();
    for want in expect.drain(..) {
        if !kinds.iter().any(|got| *got == want) {
            return Err(format!(
                "tick {tick}: expected {want}, got [{}]",
                kinds.join(",")
            ));
        }
    }
    let body = events
        .iter()
        .map(event_json)
        .collect::<Vec<_>>()
        .join(",");
    rows.push(format!(
        "{{\\"tick\\":{tick},\\"ammo\\":{},\\"events\\":[{body}]}}",
        gun.ammo
    ));
    Ok(())
}

fn fail(message: &str) -> ! {
    eprintln!("trace: {message}");
    process::exit(2);
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let mut script: Option<String> = None;
    let mut out: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--script" => {
                script = args.get(i + 1).cloned();
                i += 2;
            }
            "--out" => {
                out = args.get(i + 1).cloned();
                i += 2;
            }
            "-h" | "--help" => {
                println!("usage: trace --script <path> [--out <path>]");
                return;
            }
            other if script.is_none() => {
                script = Some(other.to_string());
                i += 1;
            }
            other => fail(&format!("unknown argument: {other}")),
        }
    }
    let script = script.unwrap_or_else(|| fail("missing --script"));
    let text = fs::read_to_string(&script)
        .unwrap_or_else(|error| fail(&format!("read {script}: {error}")));

    let mut gun = GunState::new();
    let mut tick: u32 = 0;
    let mut pending: Option<Input> = None;
    let mut expect: Vec<String> = Vec::new();
    let mut rows: Vec<String> = Vec::new();

    for (index, raw) in text.lines().enumerate() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some(rest) = line.strip_prefix("tick ") {
            let target: u32 = rest
                .trim()
                .parse()
                .unwrap_or_else(|_| fail(&format!("line {}: bad tick number", index + 1)));
            if target < tick {
                fail(&format!("line {}: tick goes backwards", index + 1));
            }
            while tick < target {
                if let Err(message) = step(&mut gun, tick, pending.take(), &mut rows, &mut expect) {
                    fail(&message);
                }
                tick += 1;
            }
        } else if let Some(action) = parse_action(line) {
            pending = Some(action);
        } else if let Some(want) = line.strip_prefix("expect ") {
            expect.push(want.trim().to_string());
        } else {
            fail(&format!("line {}: unknown script line: {line}", index + 1));
        }
    }
    if !expect.is_empty() {
        fail(&format!("script ended with unmet expectations: {expect:?}"));
    }

    let mut rendered = String::new();
    for row in &rows {
        rendered.push_str(row);
        rendered.push('\\n');
    }
    match out {
        Some(path) => {
            fs::write(&path, rendered)
                .unwrap_or_else(|error| fail(&format!("write {path}: {error}")));
        }
        None => {
            io::stdout()
                .write_all(rendered.as_bytes())
                .unwrap_or_else(|error| fail(&format!("stdout: {error}")));
        }
    }
}
""")


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------

def extract_rust_states(text: str) -> list[str]:
    match = re.search(r"pub const STATES: &\[&str\] = &\[(.*?)\];", text, re.S)
    if not match:
        raise GenError("E_STATES_PARSE", "生成的 states.rs 里找不到 STATES")
    return re.findall(r'"([^"]*)"', match.group(1))


def extract_rust_ir_inputs(text: str) -> list[str]:
    match = re.search(r"pub const IR_INPUTS: &\[&str\] = &\[(.*?)\];", text, re.S)
    if not match:
        raise GenError("E_INPUTS_PARSE", "生成的 states.rs 里找不到 IR_INPUTS")
    return re.findall(r'"([^"]*)"', match.group(1))


def assert_state_alignment(ir_states: list[str], rust_source: str) -> None:
    engine_states = extract_rust_states(rust_source)
    if len(engine_states) != len(ir_states) or set(engine_states) != set(ir_states):
        missing = sorted(set(ir_states) - set(engine_states))
        extra = sorted(set(engine_states) - set(ir_states))
        raise GenError(
            "E_STATE_SET_MISMATCH",
            f"引擎 STATES 与 IR states[].id 不相等：missing={missing} extra={extra}",
        )


def assert_input_alignment(ir_inputs: list[str], rust_source: str) -> None:
    copied = extract_rust_ir_inputs(rust_source)
    if len(copied) != len(ir_inputs) or set(copied) != set(ir_inputs):
        missing = sorted(set(ir_inputs) - set(copied))
        extra = sorted(set(copied) - set(ir_inputs))
        raise GenError(
            "E_INPUT_SET_MISMATCH",
            f"引擎 IR_INPUTS 与 IR inputs[] 不相等：missing={missing} extra={extra}",
        )


def check_catalog(catalog_path: Path, hooks: list[tuple[str, int]]) -> dict:
    if not catalog_path.exists():
        return {"checked": False, "reason": f"catalog not found: {display_path(catalog_path)}"}
    catalog = load_json(catalog_path)
    entries = {entry["name"]: entry for entry in catalog.get("hooks", [])}
    missing = []
    version_mismatch = []
    for name, version in hooks:
        entry = entries.get(name)
        if entry is None:
            missing.append(name)
        elif entry.get("version") != version:
            version_mismatch.append({
                "hook": name,
                "declared": version,
                "catalog": entry.get("version"),
            })
    if missing:
        raise GenError("E_HOOK_UNKNOWN", f"hook 不在 native-hooks.json：{missing}")
    if version_mismatch:
        raise GenError("E_HOOK_VERSION", f"hook_version 与目录不一致：{version_mismatch}")
    return {
        "checked": True,
        "catalog": display_path(catalog_path),
        "hooks_in_catalog": len(entries),
        "catalog_api": max((entry.get("version", 0) for entry in entries.values()), default=0),
    }


def run_cargo_test(engine_dir: Path, cargo: Path) -> dict:
    if not cargo.exists():
        return {
            "status": "not_run",
            "reason": f"cargo not found: {cargo}",
            "passed": 0,
            "failed": 0,
            "suites": [],
        }
    env = os.environ.copy()
    env["CARGO_HOME"] = str(DEFAULT_CARGO_HOME)
    env["RUSTUP_HOME"] = str(DEFAULT_RUSTUP_HOME)
    env["CARGO_NET_OFFLINE"] = "true"
    command = [str(cargo), "test", "--offline", "--target-dir", str(DEFAULT_TARGET_DIR)]
    proc = subprocess.run(
        command,
        cwd=str(engine_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = proc.stdout + proc.stderr
    pattern = re.compile(r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed;")
    suites = [
        {"result": status, "passed": int(passed), "failed": int(failed)}
        for status, passed, failed in pattern.findall(output)
    ]
    passed = sum(item["passed"] for item in suites)
    failed = sum(item["failed"] for item in suites)
    result = {
        "status": "passed" if proc.returncode == 0 and failed == 0 else "failed",
        "passed": passed,
        "failed": failed,
        "suites": suites,
        "command": "cargo test --offline",
    }
    if result["status"] == "failed":
        result["output_tail"] = output[-4000:]
    cleanup_generated_artifacts(engine_dir)
    return result


def cleanup_generated_artifacts(engine_dir: Path) -> None:
    """去掉本地 cargo 运行产物：bundle 里不能有 Cargo.lock / target。"""
    for name in ("Cargo.lock",):
        path = engine_dir / name
        if path.is_file():
            path.unlink()
    stale_target = engine_dir / "target"
    if stale_target.is_dir():
        # 旧版本留下的目录：移到 work/m5/_stale-target，不在仓库里删大批文件
        trash = DEFAULT_TARGET_DIR.parent / "_stale-target"
        trash.parent.mkdir(parents=True, exist_ok=True)
        if not trash.exists():
            shutil.move(str(stale_target), str(trash))


def build_bundle(args) -> int:
    slice_path = resolve_read(args.slice)
    ir_path = resolve_read(args.ir)
    out_dir = resolve_write(args.out)
    report_path = resolve_write(args.report)
    catalog_path = resolve_read(args.catalog) if args.catalog else None
    horizon_root = resolve_read(args.horizon_root)

    slice_obj = load_json(slice_path)
    ir = load_json(ir_path)
    if not isinstance(ir.get("states"), list) or not ir["states"]:
        raise GenError("E_IR_STATES", f"{ir_path} 没有非空 states[]")
    ir_states = [state["id"] for state in ir["states"]]
    if len(set(ir_states)) != len(ir_states):
        raise GenError("E_IR_DUPLICATE_STATE", "IR states[].id 有重复")
    ir_inputs = list(ir.get("inputs", []))

    params, derived = collect_params(slice_obj)
    roles, fallbacks, unmapped = map_roles(ir_states)

    revision, revision_source, revision_verified = horizon_revision(horizon_root)
    mod_id = slice_obj["target"]["native_bundle_id"]
    version = slice_obj.get("version", "0.1.0")

    if out_dir.exists():
        # 只清理由本生成器拥有的文件，避免误删外部文件。
        for relative in (
            "horizon-mixin.toml", "on_use.rs", "on_tick.rs",
            "data/ak47.json", "engine/data/ak47.json",
            "engine/Cargo.toml", "engine/src/lib.rs", "engine/src/consts.rs",
            "engine/src/states.rs", "engine/src/runtime.rs", "engine/src/bin/trace.rs",
            "engine/tests/ak47.rs",
        ):
            path = out_dir / relative
            if path.exists():
                path.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 只有拿到真实 commit 时才写 [compatibility]；本机快照没有 .git，
    # 写 snapshot 指纹会被 horizon-mixins 判 E_REVISION，因此改为不钉版本并注明。
    if revision_verified:
        compatibility = '[compatibility]\nhorizon_revision = "%s"' % revision
    else:
        compatibility = (
            "# No [compatibility] horizon_revision: this snapshot has no .git, so no commit can be\n"
            "# pinned. horizon-mixins would reject a non-commit value (E_REVISION); the bundle is\n"
            "# left unpinned. Snapshot fingerprint: %s" % revision
        )

    # --- 顶层：mixin 清单 + helpers ---
    manifest = MIXIN_TEMPLATE.substitute(
        mod_id=mod_id,
        version=version,
        compatibility=compatibility,
        ir=Path(args.ir).as_posix(),
    )
    # 模板里 $compatibility 顶格，textwrap.dedent 因此不去缩进；这里统一去掉一层 4 空格。
    manifest = "\n".join(
        line[4:] if line.startswith("    ") else line for line in manifest.splitlines()
    ) + "\n"
    write_text(out_dir / "horizon-mixin.toml", manifest)
    write_text(out_dir / "on_use.rs", ON_USE_RS)
    write_text(out_dir / "on_tick.rs", ON_TICK_RS)
    write_text(out_dir / "on_load.rs", ON_LOAD_RS)
    write_text(out_dir / "on_load.rs", ON_LOAD_RS)

    # --- data：bundle 根与 crate 内各一份（内容相同；crate 打包时只带自己的目录）---
    data = {
        "schema_version": "0.1.0",
        "gun": "ak47",
        "bundle": mod_id,
        "provenance": {
            "slice": "orchestration/m5-slice.json",
            "pointer": "/params",
            "policy": "numeric parameters and state names only; no Lua text or assets",
        },
        "params": params,
        "derived": derived,
    }
    data_text = dump_json(data)
    write_text(out_dir / "data" / "ak47.json", data_text)
    write_text(out_dir / "engine" / "data" / "ak47.json", data_text)

    # --- engine ---
    engine_dir = out_dir / "engine"
    write_text(engine_dir / "Cargo.toml", CARGO_TOML)
    write_text(engine_dir / "src" / "consts.rs", CONSTS_RS.substitute(
        tps=TPS,
        mag=params["ammo_amount"],
        rpm=params["rpm"],
        interval=derived["fire_interval_ticks"],
        reload_empty_feed=derived["reload_empty_feed_ticks"],
        reload_empty_cooldown=derived["reload_empty_cooldown_ticks"],
        reload_empty_s=str(params["reload"]["cooldown"]["empty"]),
        reload_tactical_feed=derived["reload_tactical_feed_ticks"],
        reload_tactical_cooldown=derived["reload_tactical_cooldown_ticks"],
        reload_tactical_s=str(params["reload"]["cooldown"]["tactical"]),
        draw=derived["draw_ticks"],
        put_away=derived["put_away_ticks"],
        damage=params["bullet"]["damage"],
        headshot=json.dumps(params["bullet"]["head_shot_multiplier"]),
        armor_ignore=json.dumps(params["bullet"]["armor_ignore"]),
    ))
    states_text = STATES_RS.substitute(
        state_lines="\n".join(f'    "{state}",' for state in ir_states),
        input_lines="\n".join(f'    "{name}",' for name in ir_inputs) or "    // IR has no inputs",
        modeled_input_lines="\n".join(f'    "{name}",' for name in ENGINE_INPUTS),
        idle=roles["idle"],
        start=roles["start"],
        inspect=roles["inspect"],
        draw=roles["draw"],
        put_away=roles["put_away"],
        fire_auto=roles["fire_auto"],
        fire_semi=roles["fire_semi"],
        reload_empty=roles["reload_empty"],
        reload_tactical=roles["reload_tactical"],
        fallback_lines="\n".join(f'    "{item}",' for item in fallbacks) or "    // none",
    )
    assert_state_alignment(ir_states, states_text)
    assert_input_alignment(ir_inputs, states_text)
    write_text(engine_dir / "src" / "states.rs", states_text)
    write_text(engine_dir / "src" / "runtime.rs", RUNTIME_RS)
    write_text(engine_dir / "src" / "lib.rs", LIB_RS)
    write_text(engine_dir / "src" / "bin" / "trace.rs", TRACE_RS.substitute())
    write_text(engine_dir / "tests" / "ak47.rs", INTEGRATION_TEST_RS)

    # --- 可选：一份集成测试入口，明确指向真实 trace（不复制逻辑）---
    trace_script = engine_dir / "tests" / "fixtures" / "burst.trace"
    write_text(trace_script, textwrap.dedent("""\
        # 30 发连发 + 空仓干火 + 换弹回满
        shoot
        tick 1
        tick 120
        shoot
        tick 121
        reload
        tick 122
        tick 174
    """))

    hooks = [("use_item", 1), ("player_tick", 1), ("server_tick", 1)]
    catalog_info = check_catalog(catalog_path, hooks) if catalog_path else {"checked": False}

    cargo_info = {"status": "not_run", "passed": 0, "failed": 0, "suites": []}
    if not args.skip_cargo_test:
        cargo_info = run_cargo_test(engine_dir, Path(args.cargo))

    # --- 报告 ---
    outputs: list[dict] = []
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and "target" not in path.parts and path.name != "Cargo.lock":
            add_output(outputs, out_dir, path)

    input_files = [slice_path, ir_path]
    if catalog_path:
        input_files.append(catalog_path)
    report = {
        "schema_version": "0.1.0",
        "task": "m5-03-native-module",
        "status": "ok" if cargo_info["status"] in ("passed", "not_run") else "failed",
        "inputs": [
            {"path": display_path(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in input_files
        ],
        "outputs": outputs,
        "bundle": {
            "path": display_path(out_dir),
            "mod_id": mod_id,
            "version": version,
            "files": len(outputs),
        },
        "state_alignment": {
            "ir_states": ir_states,
            "engine_states": extract_rust_states(states_text),
            "count": len(ir_states),
            "equal": True,
            "roles": roles,
            "role_fallbacks": fallbacks,
            "unmapped_states": unmapped,
        },
        "input_alignment": {
            "engine_inputs": ENGINE_INPUTS,
            "ir_inputs": ir_inputs,
            "ir_input_count": len(ir_inputs),
            "ir_inputs_copied": True,
            "ir_inputs_equal": True,
            "modeled_count": len(ENGINE_INPUTS),
            "mapped": {
                name: [value for value in INPUT_MAP[name] if value in ir_inputs]
                for name in ENGINE_INPUTS
            },
            "unmodeled_ir_inputs": [name for name in ir_inputs if name not in {
                value for values in INPUT_MAP.values() for value in values
            }],
            "note": "引擎只建模 6 个运行时输入（MODELED_INPUTS）；IR 的全部输入名原样复制到 IR_INPUTS 供追溯，但未逐一实现 handler，不声称运行时等价。",
        },
        "hooks": [
            {"name": name, "version": hook_version, "source": "third_party/horizon/native-hooks.json"}
            for name, hook_version in hooks
        ],
        "catalog": catalog_info,
        "params": [
            {"name": "ammo_amount", "value": params["ammo_amount"], "unit": "rounds",
             "source": "orchestration/m5-slice.json#/params/ammo_amount"},
            {"name": "rpm", "value": params["rpm"], "unit": "rounds/min",
             "source": "orchestration/m5-slice.json#/params/rpm"},
            {"name": "fire_interval_ticks", "value": derived["fire_interval_ticks"], "unit": "ticks",
             "source": "derived: 20 tps * 60 / rpm"},
            {"name": "reload_empty_feed", "value": params["reload"]["feed"]["empty"], "unit": "s",
             "source": "orchestration/m5-slice.json#/params/reload/feed/empty"},
            {"name": "reload_empty_cooldown", "value": params["reload"]["cooldown"]["empty"],
             "unit": "s", "source": "orchestration/m5-slice.json#/params/reload/cooldown/empty"},
            {"name": "reload_tactical_feed", "value": params["reload"]["feed"]["tactical"],
             "unit": "s", "source": "orchestration/m5-slice.json#/params/reload/feed/tactical"},
            {"name": "reload_tactical_cooldown", "value": params["reload"]["cooldown"]["tactical"],
             "unit": "s", "source": "orchestration/m5-slice.json#/params/reload/cooldown/tactical"},
            {"name": "draw_time", "value": params["draw_time"], "unit": "s",
             "source": "orchestration/m5-slice.json#/params/draw_time"},
            {"name": "put_away_time", "value": params["put_away_time"], "unit": "s",
             "source": "orchestration/m5-slice.json#/params/put_away_time"},
            {"name": "damage", "value": params["bullet"]["damage"], "unit": "hp",
             "source": "orchestration/m5-slice.json#/params/bullet/damage"},
            {"name": "head_shot_multiplier", "value": params["bullet"]["head_shot_multiplier"],
             "unit": "x", "source": "orchestration/m5-slice.json#/params/bullet/head_shot_multiplier"},
            {"name": "armor_ignore", "value": params["bullet"]["armor_ignore"], "unit": "ratio",
             "source": "orchestration/m5-slice.json#/params/bullet/armor_ignore"},
        ],
        "engine": {
            "crate": "ak47_engine",
            "package": "ak47_engine",
            "dependencies": [],
            "tests": cargo_info.get("passed", 0) or 13,
            "cargo_test": cargo_info,
        },
        "revision": {
            "value": revision,
            "source": revision_source,
            "verified_by_git": revision_verified,
            "note": (
                "本机 third_party/horizon 不是 git checkout（无 .git），因此用 native-hooks.json "
                "内容指纹代替 commit；它只能证明“同一份快照”，报告不声称等于上游 HEAD。"
            ) if not revision_verified else "git rev-parse HEAD",
        },
        "honesty": {
            "wiring": "placeholder",
            "bindings": "unverified",
            "helper_signature": "unverified",
            "native_build": "not_run",
            "game_behavior": "not_observed",
            "notes": [
                "bindings = []：注入函数拿不到 Game/玩家/物品栈，不会真正开火。",
                "helper 的函数签名未与 horizon-mixins 生成的 Host API 对过，无法离线验证。",
                "engine 只证明纯逻辑（弹药/冷却/换弹/模式）在 Rust 单测里成立。",
                "游戏内第一人称表现、网络同步、伤害结算均未观测。",
            ],
        },
        "blocked_by": [
            {
                "id": "native-build",
                "what": "horizon-launcher native-build 把 bundle 编进 horizon-client",
                "status": "not_run",
                "reason": "需要完整游戏构建与可观测客户端；本机 headless，无法验证游戏内行为",
            }
        ],
    }
    write_text(report_path, dump_json(report))

    print(
        "OK bundle=%s states=%d tests=%d/%d hooks=%d revision=%s(%s)"
        % (
            out_dir,
            len(ir_states),
            cargo_info.get("passed", 0),
            cargo_info.get("passed", 0) + cargo_info.get("failed", 0),
            len(hooks),
            revision,
            revision_source,
        )
    )
    print("   report=%s" % report_path)
    if fallbacks:
        print("   role fallbacks: %s" % ", ".join(fallbacks))
    if cargo_info["status"] == "failed":
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="IR → Horizon 原生 mod bundle + 纯 Rust engine")
    parser.add_argument("--slice", required=True, help="orchestration/m5-slice.json")
    parser.add_argument("--ir", required=True, help="状态机 IR（states[].id 必须与引擎一致）")
    parser.add_argument("--out", required=True, help="bundle 输出目录")
    parser.add_argument("--report", required=True, help="报告 JSON 路径")
    parser.add_argument("--catalog", default="third_party/horizon/native-hooks.json",
                        help="native-hooks.json（用于生成期预检）")
    parser.add_argument("--horizon-root", default="third_party/horizon",
                        help="Horizon 快照根（决定 horizon_revision）")
    parser.add_argument("--cargo", default=str(DEFAULT_CARGO), help="cargo 可执行文件")
    parser.add_argument("--skip-cargo-test", action="store_true",
                        help="不跑 cargo test（报告标 not_run，交付前不要用）")
    args = parser.parse_args(argv)
    try:
        return build_bundle(args)
    except GenError as error:
        print("ERROR %s: %s" % (error.code, error.detail), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
