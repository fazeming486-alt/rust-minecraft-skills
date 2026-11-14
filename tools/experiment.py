#!/usr/bin/env python3
"""TaCZ 1.20.1 双轨/三轨分类实验编排器。

source track (原始 .java) / decompiled track (Vineflower 输出) / bytecode track (jar 内 .class)
三条轨各自生成 artifact-index → 跑同一套规则 → 输出脱敏统计报告。

用法:
  python tools/experiment.py --profile profiles/forge/_template.json \
      --rules rules/classification.rules.json --out reports/calibration-before.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify  # noqa: E402
import lib_facts as L  # noqa: E402

WORK = ROOT / "work"


def load(rel: str) -> Any:
    with (ROOT / rel).open("r", encoding="utf-8") as f:
        return json.load(f)


def dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def norm_id(unit_id: str) -> str:
    return unit_id.split("$", 1)[0]


def summarize(delta: Dict[str, Any]) -> Dict[str, Any]:
    patches = delta["unit_patches"]
    disp = Counter(p["set"]["disposition"] for p in patches)
    sem = Counter(p["set"]["semantic"] for p in patches)
    rules = Counter(e["rule_id"] for p in patches for e in p["set"]["evidence"])
    fallback = [p["unit_id"] for p in patches
                if any(e["rule_id"] == "R010" for e in p["set"]["evidence"])]
    c6 = [p["unit_id"] for p in patches if p["set"]["disposition"] == "C6"]
    return {
        "units": len(patches),
        "by_disposition": dict(sorted(disp.items())),
        "by_semantic": dict(sorted(sem.items())),
        "rule_hits": dict(sorted(rules.items())),
        "fallback_units": len(fallback),
        "fallback_samples": fallback[:25],
        "c6_units": len(c6),
        "c6_ratio": round(len(c6) / len(patches), 4) if patches else 0.0,
        "c6_samples": c6[:25],
        "low_confidence_units": len(delta["summary"]["low_confidence_units"]),
        "drilldown_units": sum(1 for p in patches if p["set"]["requires_drilldown"]),
    }


def disposition_map(delta: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in delta["unit_patches"]:
        out.setdefault(norm_id(p["unit_id"]), p["set"]["disposition"])
    return out


def symbol_sets(index: Dict[str, Any], field: str) -> Dict[str, set]:
    out: Dict[str, set] = {}
    for unit in index["units"]:
        key = norm_id(unit["unit_id"])
        out.setdefault(key, set()).update(unit["symbols"].get(field, []))
    return out


def cross_track(source: Dict[str, Any], decompiled: Dict[str, Any],
                bytecode: Dict[str, Any],
                sdelta: Dict[str, Any], ddelta: Dict[str, Any],
                bdelta: Dict[str, Any]) -> Dict[str, Any]:
    s_map, d_map, b_map = (disposition_map(x) for x in (sdelta, ddelta, bdelta))
    common_sb = set(s_map) & set(b_map)
    common_sd = set(s_map) & set(d_map)
    agree_sb = sum(1 for k in common_sb if s_map[k] == b_map[k])
    agree_sd = sum(1 for k in common_sd if s_map[k] == d_map[k])

    sa = symbol_sets(source, "annotations")
    ba = symbol_sets(bytecode, "annotations")
    common_units = set(sa) & set(ba)
    annotation_equal = sum(1 for k in common_units if sa[k] == ba[k])
    ss = symbol_sets(source, "constant_strings")
    bs = symbol_sets(bytecode, "constant_strings")
    bc_only_strings = sum(len(bs.get(k, set()) - ss.get(k, set())) for k in set(bs) & set(ss))

    return {
        "source_vs_decompiled": {
            "common_units": len(common_sd),
            "disposition_agreement": round(agree_sd / len(common_sd), 4) if common_sd else 0.0,
        },
        "source_vs_bytecode": {
            "common_units": len(common_sb),
            "disposition_agreement": round(agree_sb / len(common_sb), 4) if common_sb else 0.0,
            "annotation_sets_equal": annotation_equal,
            "annotation_equal_ratio": round(annotation_equal / len(common_units), 4) if common_units else 0.0,
            "bytecode_only_string_literals": bc_only_strings,
        },
        "bytecode_only_class_units": len(bytecode["units"]) - len(source["units"]),
        "bytecode_only_note": "内部类/lambda/合成类在编译期生成，反编译器会折叠回外层文件；这是源码轨不是 ground truth 的直接证据",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="三轨分类实验")
    ap.add_argument("--profile", default="profiles/forge/_template.json")
    ap.add_argument("--rules", default="rules/classification.rules.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="experiment")
    args = ap.parse_args(argv)

    profile = load(args.profile)
    rules = load(args.rules)

    source = L.index_from_source_tree(WORK / "TACZ-1.20.1")
    decompiled = L.index_from_source_tree(WORK / "decompiled", source_root=".")
    bytecode = L.index_from_jar(WORK / "tacz-forge-1.20.1-1.2.0.jar",
                                "tacz-forge-1.20.1-1.2.0")
    # 反编译目录的根是包根目录，统一修正 loader_profile
    for idx in (source, decompiled, bytecode):
        idx["source"]["loader_profile"] = profile.get("profile_id", args.profile)

    dump(source, WORK / "index.source.json")
    dump(decompiled, WORK / "index.decompiled.json")
    dump(bytecode, WORK / "index.bytecode.json")

    sdelta = classify.classify(source, profile, rules)
    ddelta = classify.classify(decompiled, profile, rules)
    bdelta = classify.classify(bytecode, profile, rules)
    dump(sdelta, WORK / "delta.source.json")
    dump(ddelta, WORK / "delta.decompiled.json")
    dump(bdelta, WORK / "delta.bytecode.json")

    report = {
        "schema_version": "0.1.0",
        "experiment_id": "tacz-1.20.1-forge-1.2.0",
        "label": args.label,
        "profile": args.profile,
        "ruleset": rules.get("ruleset_version"),
        "inputs": {
            "source_java_files": len(source["units"]),
            "decompiled_java_files": len(decompiled["units"]),
            "jar_class_files": len(bytecode["units"]),
            "source_root": "official MCModderAnchor/TACZ 1.20.1 branch",
            "binary": "Modrinth tacz-forge-1.20.1-1.2.0.jar",
            "decompiler": "Vineflower 1.12.0",
            "license_note": "Code GPL-3.0 / Assets CC BY-NC-ND 4.0；本仓库只保留统计与规则，不含任何源码或资产",
        },
        "tracks": {
            "source": summarize(sdelta),
            "decompiled": summarize(ddelta),
            "bytecode": summarize(bdelta),
        },
        "cross_track": cross_track(source, decompiled, bytecode, sdelta, ddelta, bdelta),
    }
    dump(report, ROOT / args.out)

    t = report["tracks"]
    print("LABEL       : %s" % args.label)
    print("UNITS       : source=%d decompiled=%d bytecode=%d"
          % (t["source"]["units"], t["decompiled"]["units"], t["bytecode"]["units"]))
    print("SOURCE  disp: %s  C6=%s  fallback=%d"
          % (t["source"]["by_disposition"], t["source"]["c6_ratio"], t["source"]["fallback_units"]))
    print("BYTECODE disp: %s  C6=%s  fallback=%d"
          % (t["bytecode"]["by_disposition"], t["bytecode"]["c6_ratio"], t["bytecode"]["fallback_units"]))
    print("AGREEMENT   : source/decompiled=%s  source/bytecode=%s"
          % (report["cross_track"]["source_vs_decompiled"]["disposition_agreement"],
             report["cross_track"]["source_vs_bytecode"]["disposition_agreement"]))
    print("REPORT      : %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
