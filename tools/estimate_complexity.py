#!/usr/bin/env python3
"""确定性复杂度评估器（ADR 0007）。

所有信号由脚本从真实输入计算，**模型不得自评复杂度**。
只读 jar 的条目名，不读取任何资产内容，因此可在 oracle-only 下运行。

用法:
  python tools/estimate_complexity.py --jar work/tacz.jar \
    --index work/index.source.json --policy-decision work/policy-decision.json \
    --bindings target/horizon.capabilities.json --delta work/delta.source.json \
    --out reports/m2-complexity.json
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def scan_assets(jar: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(jar) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    assets = [n for n in names if n.startswith("assets/")]
    exts = Counter(Path(n).suffix.lower() or "(none)" for n in assets)
    content_pack = [n for n in assets if "/custom/" in n]
    return {"total_files": len(names), "assets": assets, "ext_counts": dict(exts),
            "content_pack_count": len(content_pack)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jar", required=True, type=Path)
    ap.add_argument("--index", type=Path)
    ap.add_argument("--policy-decision", type=Path)
    ap.add_argument("--bindings", type=Path)
    ap.add_argument("--delta", type=Path)
    ap.add_argument("--cross-layer-contracts", type=int, default=0)
    ap.add_argument("--model", type=Path,
                    default=Path(__file__).resolve().parent.parent / "orchestration/complexity-model.json")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", default="M2")
    args = ap.parse_args(argv)

    model = load(args.model)
    scan = scan_assets(args.jar)
    assets = scan["assets"]
    n_assets = len(assets) or 1

    unsupported = 0
    for name in assets:
        if any(fnmatch.fnmatch(name, pattern) for pattern in model["unsupported_patterns"]):
            unsupported += 1

    index = load(args.index) if args.index and args.index.is_file() else {"units": []}
    unit_count = len(index.get("units", []))

    policy_raw = load(args.policy_decision) if args.policy_decision and args.policy_decision.is_file() else {}
    policy_mode = policy_raw.get("mode", "full-inspection")
    policy_strict = model["policy_strictness_map"].get(policy_mode, 1.0)

    bindings = load(args.bindings) if args.bindings and args.bindings.is_file() else {"bindings": {}}
    gap_count = sum(1 for b in bindings.get("bindings", {}).values() if b.get("status") == "unbound")

    c6_ratio = 0.0
    if args.delta and args.delta.is_file():
        delta = load(args.delta)
        patches = delta.get("unit_patches", [])
        if patches:
            c6_ratio = sum(1 for p in patches if p["set"]["disposition"] == "C6") / len(patches)

    values = {
        "unit_count": unit_count,
        "asset_count": len(assets),
        "format_diversity": len(scan["ext_counts"]),
        "content_pack_ratio": scan["content_pack_count"] / n_assets,
        "unsupported_format_ratio": unsupported / n_assets,
        "capability_gap_count": gap_count,
        "policy_strictness": policy_strict,
        "c6_ratio": c6_ratio,
        "cross_layer_contracts": args.cross_layer_contracts,
    }

    signals: Dict[str, Dict[str, float]] = {}
    score = 0.0
    for name, spec in model["signals"].items():
        value = float(values[name])
        normalized = min(value / float(spec["scale"]), float(spec["cap"]))
        weighted = normalized * float(spec["weight"])
        score += weighted
        signals[name] = {"value": round(value, 4), "normalized": round(normalized, 4),
                         "weighted": round(weighted, 4), "source": spec["source"]}
    score = min(score, 1.0)

    band = next(b for b in model["bands"] if b["min"] <= score < b["max"])
    hard_gates = []
    if gap_count > 0:
        hard_gates.append("capability_gap_count > 0 (%d)" % gap_count)
    if policy_mode == "oracle-only":
        hard_gates.append("policy_mode == oracle-only")
    if values["unsupported_format_ratio"] > 0.30:
        hard_gates.append("unsupported_format_ratio = %.4f > 0.30" % values["unsupported_format_ratio"])

    report = {
        "schema_version": "0.1.0",
        "label": args.label,
        "model_version": model["version"],
        "inputs": {
            "jar": args.jar.name, "jar_total_files": scan["total_files"],
            "assets_count": len(assets), "content_pack_assets": scan["content_pack_count"],
            "ext_counts": scan["ext_counts"], "unsupported_assets": unsupported,
            "policy_mode": policy_mode, "capability_gaps": gap_count,
        },
        "signals": signals,
        "score": round(score, 4),
        "band": band["id"],
        "recommended_workers": band["workers"],
        "split": band["split"],
        "human_gate": bool(band["human_gate"] or hard_gates),
        "hard_gates": hard_gates,
        "input_hash": "sha256:" + hashlib.sha256(
            json.dumps({"values": values, "score": score}, sort_keys=True).encode()).hexdigest()[:24],
        "note": "确定性评估；模型不得自评复杂度。人工覆盖需记录理由。",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK score=%.4f band=%s workers=%d human_gate=%s hard_gates=%d out=%s"
          % (report["score"], report["band"], report["recommended_workers"],
             report["human_gate"], len(hard_gates), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
