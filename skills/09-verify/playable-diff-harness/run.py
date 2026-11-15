#!/usr/bin/env python3
"""playable-diff-harness — 用纯逻辑 trace 逐 tick 比对 AK-47 的行为时间线。

只依赖标准库。设计约束：
- 不启动游戏、不读 GPU、不需要 26.3 资源；
- 期望值全部来自 orchestration/m5-slice.json 的真实数值；
- 负例必须失败，否则判定器没有意义。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
TICKS_PER_SECOND = 20
DEFAULT_CARGO = Path("D:/RUST重写mc项目/dev/cargo/bin/cargo.exe")

# 剧本：tick -> 动作
SCENARIO: List[Tuple[int, str]] = [
    (0, "shoot"),
    (20, "release"),
    (22, "reload"),
    (64, "shoot"),
    (74, "release"),
    (76, "fireselect"),
    (78, "shoot"),
    (79, "release"),
    (80, "shoot"),
    (81, "release"),
    (82, "shoot"),
    (83, "release"),
    (100, "reload"),
    (200, "tick"),
]

WATCHED = ("Shot", "ReloadStart", "ReloadEnd", "ModeSwitch")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def ticks_for(seconds: float) -> int:
    return max(1, int(round(seconds * TICKS_PER_SECOND)))


def write_script(path: Path) -> None:
    lines: List[str] = []
    for tick, action in SCENARIO:
        lines.append("tick %d" % tick)
        if action != "tick":
            lines.append(action)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run_trace(cargo: Path, engine: Path, script: Path, out: Path) -> Dict[str, Any]:
    cmd = [
        str(cargo), "run", "--offline", "--quiet",
        "--manifest-path", "Cargo.toml",
        "--bin", "trace", "--",
        "--script", str(script), "--out", str(out),
    ]
    proc = subprocess.run(cmd, cwd=str(engine), capture_output=True, text=True)
    shown = "cargo run --offline --quiet --bin trace -- --script %s --out %s" % (
        script.name, out.name)
    return {
        "command": shown,
        "cargo": cargo.name,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def normalise_event(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        return {"kind": raw}
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind") or raw.get("type") or raw.get("event")
    if not kind:
        return None
    ev: Dict[str, Any] = {"kind": str(kind)}
    for key in ("ammo_after", "ammo", "to", "empty", "remaining"):
        if key in raw:
            ev[key] = raw[key]
    return ev


def parse_trace(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    if not path.is_file():
        return events
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise SystemExit("trace.jsonl 第 %d 行不是 JSON：%s" % (line_no, line[:120]))
        tick = row.get("tick")
        if not isinstance(tick, int):
            raise SystemExit("trace.jsonl 第 %d 行缺 int 型 tick" % line_no)
        for raw in row.get("events") or []:
            ev = normalise_event(raw)
            if ev is None:
                continue
            ev["tick"] = tick
            events.append(ev)
    return events


def expected_events(params: Dict[str, Any], mag: int) -> List[Dict[str, Any]]:
    rpm = int(params["rpm"])
    per_shot = max(1, int(round(TICKS_PER_SECOND * 60.0 / rpm)))
    tactical = ticks_for(float(params["reload"]["cooldown"]["tactical"]))
    out: List[Dict[str, Any]] = []
    ammo = mag

    def shoot(tick: int) -> None:
        nonlocal ammo
        ammo -= 1
        out.append({"tick": tick, "kind": "Shot", "ammo_after": ammo})

    for i in range(10):
        shoot(i * per_shot)
    out.append({"tick": 22, "kind": "ReloadStart", "empty": False})
    out.append({"tick": 22 + tactical, "kind": "ReloadEnd", "ammo": mag})
    ammo = mag
    for i in range(5):
        shoot(64 + i * per_shot)
    out.append({"tick": 76, "kind": "ModeSwitch", "to": "semi"})
    for tick in (78, 80, 82):
        shoot(tick)
    out.append({"tick": 100, "kind": "ReloadStart", "empty": False})
    out.append({"tick": 100 + tactical, "kind": "ReloadEnd", "ammo": mag})
    return out


def compare(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]],
            tolerance: int = 1) -> Dict[str, Any]:
    watched = [e for e in actual if e["kind"] in WATCHED]
    checks: List[Dict[str, Any]] = []
    used = [False] * len(watched)
    first_mismatch: Optional[Dict[str, Any]] = None
    for exp in expected:
        match = None
        for idx, act in enumerate(watched):
            if used[idx] or act["kind"] != exp["kind"]:
                continue
            if abs(int(act["tick"]) - int(exp["tick"])) > tolerance:
                continue
            payload_ok = all(act.get(key) == value for key, value in exp.items()
                             if key not in ("tick", "kind"))
            if not payload_ok:
                continue
            match = idx
            break
        if match is None:
            detail = {"expected": exp,
                      "actual_window": [a for a in watched
                                        if a["kind"] == exp["kind"]
                                        and abs(int(a["tick"]) - int(exp["tick"])) <= tolerance + 2]}
            checks.append({"ok": False, "expected": exp, "detail": detail})
            if first_mismatch is None:
                first_mismatch = {"tick": exp["tick"], "kind": exp["kind"],
                                  "expected": exp, "actual": detail["actual_window"]}
            continue
        used[match] = True
        drift = int(watched[match]["tick"]) - int(exp["tick"])
        checks.append({"ok": True, "expected": exp, "actual": watched[match], "drift": drift})

    unexpected = [a for idx, a in enumerate(watched) if not used[idx]]
    if unexpected and first_mismatch is None:
        first_mismatch = {"tick": unexpected[0]["tick"], "kind": unexpected[0]["kind"],
                          "expected": None, "actual": unexpected[0]}

    passed = sum(1 for c in checks if c["ok"])
    failed = len(checks) - passed + len(unexpected)
    return {
        "ok": failed == 0,
        "counts": {"expected": len(expected), "matched": passed,
                   "failed": len(checks) - passed, "unexpected": len(unexpected)},
        "max_drift": max([abs(c.get("drift", 0)) for c in checks] or [0]),
        "first_mismatch": first_mismatch,
        "checks": checks,
        "unexpected": unexpected,
    }


def engine_states(engine: Path) -> Optional[List[str]]:
    """在 engine 的 src/ 下找 STATES 常量（可能在 lib.rs 或拆到 states.rs）。"""
    src = engine / "src"
    if not src.is_dir():
        return None
    candidates = [src / "lib.rs"] + sorted(src.rglob("*.rs"))
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        match = re.search(r"STATES\s*:\s*(?:&\[&str\]|\[&str;\s*\d+\])\s*=\s*&?\[(.*?)\]", text, re.S)
        if not match:
            continue
        ids = re.findall(r'"([^"]+)"', match.group(1))
        if ids:
            return ids
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="AK-47 单枪竖切差分验收")
    ap.add_argument("--slice", default="orchestration/m5-slice.json")
    ap.add_argument("--ir", default="work/m5/state-ir/ak47.json")
    ap.add_argument("--engine", default="work/m5/native/tacz_ak47_pilot/engine")
    ap.add_argument("--cargo", default=os.environ.get("CARGO") or (
        str(DEFAULT_CARGO) if DEFAULT_CARGO.is_file() else "cargo"))
    ap.add_argument("--report", default="reports/m5-diff.json")
    args = ap.parse_args()

    slice_path = ROOT / args.slice
    ir_path = ROOT / args.ir
    engine = ROOT / args.engine
    report_path = ROOT / args.report

    if not slice_path.is_file():
        raise SystemExit("找不到 slice：%s" % slice_path)
    if not ir_path.is_file():
        raise SystemExit("找不到 IR：%s（先跑 translate-lua-statemachine）" % ir_path)
    if not (engine / "Cargo.toml").is_file():
        raise SystemExit("找不到 engine crate：%s（先跑 port-native-module）" % engine)

    slice_doc = load_json(slice_path)
    ir = load_json(ir_path)
    params = slice_doc["params"]

    script = ROOT / "work/m5/diff/script.txt"
    trace_out = ROOT / "work/m5/diff/trace.jsonl"
    write_script(script)
    if trace_out.exists():
        trace_out.unlink()

    run = run_trace(Path(args.cargo), engine, script, trace_out)
    if run["returncode"] != 0:
        write_json(report_path, {"ok": False, "stage": "trace", "run": run})
        print("trace 运行失败：\n%s" % (run["stderr"] or run["stdout"]))
        return 1

    actual = parse_trace(trace_out)
    mag = int(params["ammo_amount"])
    positive = compare(expected_events(params, mag), actual)
    negative = compare(expected_events(params, mag - 1), actual)

    ir_states = sorted(s["id"] for s in ir["states"])
    eng_states = engine_states(engine)
    states_equal = eng_states is not None and sorted(eng_states) == ir_states
    states_detail = {
        "ir": ir_states,
        "engine": eng_states,
        "only_ir": sorted(set(ir_states) - set(eng_states or [])),
        "only_engine": sorted(set(eng_states or []) - set(ir_states)),
    }

    ok = bool(positive["ok"]) and not bool(negative["ok"]) and states_equal
    official = {
        "mod": slice_doc["target"]["mod_id"],
        "passed": ok,
        "checks": {
            "logic_replay": {
                "passed": positive["counts"]["matched"],
                "failed": positive["counts"]["failed"] + positive["counts"]["unexpected"],
                "examples": [positive["first_mismatch"]] if positive["first_mismatch"] else [],
            },
            "state_set": {
                "passed": 1 if states_equal else 0,
                "failed": 0 if states_equal else 1,
                "examples": [] if states_equal else [states_detail],
            },
            "negative_control": {
                "passed": 1 if not negative["ok"] else 0,
                "failed": 1 if negative["ok"] else 0,
                "examples": [negative["first_mismatch"]] if negative["first_mismatch"] else [],
            },
        },
    }
    write_json(ROOT / "work/m5/harness/result.json", official)

    report = {
        "schema_version": "0.1.0",
        "generated_by": "playable-diff-harness@0.1.0",
        "slice_id": slice_doc["slice_id"],
        "ok": ok,
        "policy": slice_doc["policy"]["assets"],
        "inputs": {
            "slice": {"path": args.slice, "sha256": sha256(slice_path)},
            "ir": {"path": args.ir, "sha256": sha256(ir_path)},
            "script": {"path": str(script.relative_to(ROOT)), "sha256": sha256(script)},
            "trace": {"path": str(trace_out.relative_to(ROOT)), "sha256": sha256(trace_out)},
        },
        "run": run,
        "positive": positive,
        "negative_control": {
            "ok": negative["ok"],
            "expected_to_fail": True,
            "first_mismatch": negative["first_mismatch"],
        },
        "states": {"equal": states_equal, **states_detail},
        "official_result": official,
        "boundary": [
            "只覆盖 C1 逻辑（开火/换弹/切模式/弹药），不覆盖动画、后坐、散布、命中与同步",
            "期望值来自 TaCZ 数据文件的数值，不是真机录制；M3b 仍未做",
            "tick 容差 1 是工程选择，不是等价证明",
        ],
    }
    write_json(report_path, report)

    print("PASS" if ok else "FAIL",
          "| matched=%d failed=%d unexpected=%d" % (
              positive["counts"]["matched"], positive["counts"]["failed"],
              positive["counts"]["unexpected"]),
          "| states_equal=%s negative_failed=%s" % (states_equal, not negative["ok"]))
    if not ok:
        print(json.dumps({"states": states_detail,
                          "first_mismatch": positive["first_mismatch"],
                          "negative_ok": negative["ok"]}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
