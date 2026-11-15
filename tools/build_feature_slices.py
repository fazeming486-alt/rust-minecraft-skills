#!/usr/bin/env python3
"""跨层特性切片构建器（确定性、零模型参与）。

问题：按文件分工时，资产子 agent 与代码子 agent 各干各的，没人负责把
"换弹"这类横跨 动画资产 + Java 状态机 + 目标侧 hook + 同步契约 的特性缝起来。
本脚本以锚点为键，把四层事实绑成单一可判定迁移单元。

只输出统计、状态名、符号名与 unit_id；不输出任何资产数值、像素或音频内容。
"""
from __future__ import annotations

import argparse
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set

import lib_conversion as C


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def animation_facts(jar_path: Path) -> Dict[str, Any]:
    """读 jar 内的动画资产，只提取状态名 / 骨骼名 / 文件名，不保留变换数值。"""
    states: Set[str] = set()
    bones: Set[str] = set()
    state_files: Dict[str, Set[str]] = defaultdict(set)
    gun_ids: Dict[str, Set[str]] = defaultdict(set)
    files: List[str] = []
    with zipfile.ZipFile(jar_path) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".animation.json"):
                continue
            files.append(name)
            gun_id = name.rsplit("/", 1)[-1].split(".")[0]
            try:
                doc = json.loads(zf.read(name))
            except (ValueError, KeyError):
                continue
            for state, body in (doc.get("animations") or {}).items():
                states.add(state)
                state_files[state].add(name)
                gun_ids[state].add(gun_id)
                if isinstance(body, dict):
                    bones.update((body.get("bones") or {}).keys())
        all_names = [n for n in zf.namelist() if not n.endswith("/")]
    return {"states": states, "bones": bones, "files": files,
            "state_files": state_files, "gun_ids": gun_ids, "names": all_names}


def match_anchor(state: str, anchors: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    low = state.lower()
    for anchor in anchors:
        for prefix in anchor["state_prefixes"]:
            if low == prefix.lower() or low.startswith(prefix.lower()):
                return anchor
    return None


def code_units(index: Dict[str, Any], delta: Dict[str, Any],
               tokens: List[str]) -> Tuple[List[str], Counter, List[str]]:
    disp = {p["unit_id"]: p["set"].get("disposition", "?")
            for p in delta.get("unit_patches", [])}
    low_tokens = [t.lower() for t in tokens]
    hits: List[str] = []
    by_disp: Counter = Counter()
    machines: List[str] = []
    for unit in index["units"]:
        uid = unit["unit_id"]
        cls = uid.rsplit("/", 1)[-1].lower()
        if any(t in cls for t in low_tokens):
            hits.append(uid)
            by_disp[disp.get(uid, "?")] += 1
        if any(k in cls for k in ("statemachine", "animationstate", "animationcontroller",
                                  "animationrunner", "animationplan")):
            machines.append(uid)
    return sorted(hits), by_disp, sorted(set(machines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="构建跨层特性切片")
    ap.add_argument("--jar", required=True, type=Path)
    ap.add_argument("--index", required=True, type=Path)
    ap.add_argument("--delta", required=True, type=Path)
    ap.add_argument("--anchors", required=True, type=Path)
    ap.add_argument("--horizon-hooks", required=True, type=Path)
    ap.add_argument("--capabilities", required=True, type=Path)
    ap.add_argument("--policy-decision", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--summary", type=Path, default=None,
                    help="脱敏归档，默认 reports/m2-feature-slices.json（可入库、可回归）")
    args = ap.parse_args(argv)

    anchor_doc = load(args.anchors)
    anchors = anchor_doc["anchors"]
    rules = anchor_doc["state_parameter_rules"]
    workarounds = anchor_doc.get("workaround_catalog", {})
    facts = animation_facts(args.jar)
    index = load(args.index)
    delta = load(args.delta)
    hooks_doc = load(args.horizon_hooks)
    caps = load(args.capabilities)
    policy = load(args.policy_decision)

    hook_names: Set[str] = {h["name"] for h in hooks_doc["hooks"]}
    helper_names: Set[str] = {h["name"] for h in hooks_doc["helpers"]}
    bindings = caps.get("capabilities", caps.get("bindings", {}))
    unbound = sorted(k for k, v in bindings.items()
                     if isinstance(v, dict) and v.get("status") != "implemented")

    assigned: Dict[str, List[str]] = defaultdict(list)
    unmatched: List[str] = []
    for state in sorted(facts["states"]):
        a = match_anchor(state, anchors)
        (assigned[a["id"]].append(state) if a else unmatched.append(state))

    unknown_hooks: Set[str] = set()
    unknown_helpers: Set[str] = set()
    slices: List[Dict[str, Any]] = []
    canon_total = 0
    raw_total = len(facts["states"])

    for anchor in anchors:
        states = assigned.get(anchor["id"], [])
        canon_map: Dict[str, List[str]] = defaultdict(list)
        params: Set[str] = set()
        for s in states:
            c, p = C.canonicalize(s, rules)
            canon_map[c].append(s)
            params |= p
        expanded = [s for group in canon_map.values() for s in group]
        roundtrip = (sorted(expanded) == sorted(states)
                     and len(expanded) == len(set(expanded)))
        canon_total += len(canon_map)

        units, by_disp, machines = code_units(index, delta, anchor["code_tokens"])
        ids: Set[str] = set()
        for s in states:
            ids |= facts["gun_ids"].get(s, set())
        asset_files = set()
        for s in states:
            asset_files |= facts["state_files"].get(s, set())

        hooks = anchor["target_hooks"]
        helpers = anchor["target_helpers"]
        unknown_hooks |= set(hooks) - hook_names
        unknown_helpers |= set(helpers) - helper_names

        presentation = anchor["presentation"]
        needs_driver = "skeletal_animation" in presentation
        gap = [c for c in unbound if needs_driver and "animation" in c]
        if not states:
            verdict = "blocked"
        elif not units or not hooks:
            verdict = "blocked"
        elif gap:
            verdict = "needs_workaround"
        else:
            verdict = "portable"

        gaps = list(gap)
        if not states:
            gaps.append("no_animation_states_matched")
        if not units:
            gaps.append("no_java_units_matched")
        if not roundtrip:
            gaps.append("state_roundtrip_not_closed")

        slices.append({
            "slice_id": anchor["id"],
            "anchor": anchor["id"],
            "summary": anchor["summary"],
            "shared_states": sorted(states),
            "state_parameters": {
                "raw_count": len(states),
                "canonical_count": len(canon_map),
                "parameters": sorted(params),
                "roundtrip_closed": roundtrip,
            },
            "layers": {
                "assets": {
                    "animation_files": len(asset_files),
                    "animation_states": sorted(states),
                    "bone_names": sorted(facts["bones"])[:40],
                    "geometry_files": len([n for n in facts["names"]
                                           if "/geo_models/" in n and n.endswith(".json")
                                           and any(("/" + i + ".json") in n for i in ids)]),
                    "display_files": len([n for n in facts["names"]
                                          if "/display/" in n and n.endswith(".json")
                                          and any(("/" + i + "_") in n for i in ids)]),
                    "index_files": len([n for n in facts["names"]
                                        if "/index/" in n and n.endswith(".json")
                                        and any(("/" + i + ".json") in n for i in ids)]),
                    "sound_events": sorted({e for e in ("draw", "reload", "shoot", "bolt", "inspect")
                                            if any(e in s for s in states)}),
                },
                "code": {
                    "unit_count": len(units),
                    "units": units[:60],
                    "by_disposition": dict(sorted(by_disp.items())),
                    "state_machine_units": machines[:20],
                },
                "target": {
                    "hooks": hooks,
                    "helpers": helpers,
                    "capability_ids": sorted({c for c in bindings if "animation" in c}),
                    "api_tier": anchor["api_tier"],
                    "capability_gap": gap,
                    **({"workaround": workarounds["skeletal_animation"]}
                       if needs_driver and "skeletal_animation" in workarounds else {}),
                },
                "contract": {
                    "authority": anchor["authority"],
                    "sync_boundary": anchor["sync_boundary"],
                    "presentation": presentation,
                    "requires_animation_driver": needs_driver,
                },
            },
            "verdict": verdict,
            "gaps": gaps,
            "evidence": [
                "jar:%d 个 .animation.json" % len(facts["files"]),
                "锚点规则:orchestration/slice-anchors.json#%s" % anchor["id"],
                "index:%s (unit_id 类名匹配)" % args.index.as_posix(),
                "delta:%s (disposition)" % args.delta.as_posix(),
                "horizon:native-hooks.json (hook/helper 名称校验)",
                "target/horizon.capabilities.json (unbound: %s)" % ", ".join(unbound),
            ],
        })

    asset_policy = policy.get("scope_decisions", {}).get("assets", {})
    doc = {
        "schema_version": "0.1.0",
        "generated_by": "build-feature-slices@0.1.0",
        "source_artifact": args.jar.name,
        "policy": {
            "inspection": asset_policy.get("mode", "unknown"),
            "transformation": asset_policy.get("transformation", "none"),
            "distribution": asset_policy.get("distribution", "local-only"),
        },
        "summary": {
            "slice_count": len(slices),
            "raw_state_count": raw_total,
            "canonical_state_count": canon_total,
            "parameter_compression_ratio": round(1 - canon_total / raw_total, 4) if raw_total else 0.0,
            "bone_name_count": len(facts["bones"]),
            "animation_file_count": len(facts["files"]),
            "code_unit_count": sum(s["layers"]["code"]["unit_count"] for s in slices),
            "verdicts": dict(sorted(Counter(s["verdict"] for s in slices).items())),
        },
        "slices": slices,
        "unmatched_states": sorted(unmatched),
        "validation": {
            "target_symbols_resolved": not unknown_hooks and not unknown_helpers,
            "unknown_hooks": sorted(unknown_hooks),
            "unknown_helpers": sorted(unknown_helpers),
            "closed": (len(unmatched) == 0
                       and all(s["state_parameters"]["roundtrip_closed"] for s in slices)),
        },
    }
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload, encoding="utf-8")
    # 切片只含状态名/符号名/unit_id/计数，不含任何资产数值，可安全入库供跨机器回归
    summary = args.summary or (Path(__file__).resolve().parent.parent
                               / "reports" / "m2-feature-slices.json")
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(payload, encoding="utf-8")

    print("OK slices=%d raw_states=%d canonical=%d compression=%.4f bones=%d "
          "unmatched=%d unknown_hooks=%d unknown_helpers=%d out=%s"
          % (len(slices), raw_total, canon_total,
             doc["summary"]["parameter_compression_ratio"], len(facts["bones"]),
             len(unmatched), len(unknown_hooks), len(unknown_helpers), args.out))
    for s in slices:
        print("   %-14s states=%3d canon=%3d units=%3d verdict=%s gaps=%s"
              % (s["slice_id"], s["state_parameters"]["raw_count"],
                 s["state_parameters"]["canonical_count"],
                 s["layers"]["code"]["unit_count"], s["verdict"], ",".join(s["gaps"]) or "-"))
    return 0 if doc["validation"]["target_symbols_resolved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
