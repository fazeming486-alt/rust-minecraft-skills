#!/usr/bin/env python3
"""M4 泛化验证：同一套规则/profile 跑多个真实 mod，检验 C6=0 是否只属于 TaCZ。

只消费字节码轨（纯标准库 class 常量池解析），不需要反编译、不需要源码。
报告只含统计与包名计数，不含任何第三方实现内容。
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lib_facts as L  # noqa: E402
import classify as C  # noqa: E402

MODES = ("full-inspection", "metadata-only")
C6_THRESHOLD = 0.05
FALLBACK_THRESHOLD = 0.05


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def jar_shape(jar: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(jar) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    return {
        "jar_bytes": jar.stat().st_size,
        "class_files": sum(1 for n in names if n.endswith(".class")),
        "asset_files": sum(1 for n in names if n.startswith("assets/")),
        "data_files": sum(1 for n in names if n.startswith("data/")),
        "top_extensions": dict(Counter(
            (n.rsplit(".", 1)[-1].lower() if "." in n.rsplit("/", 1)[-1] else "(none)")
            for n in names).most_common(6)),
    }


def run_one(jar: Path, artifact: str, mode: str, policy: Dict[str, Any],
            profile: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    index = L.index_from_jar(jar, artifact_id=artifact, policy_mode=mode, policy=policy)
    delta = C.classify(index, profile, rules)
    patches = delta["unit_patches"]
    rule_hits: Counter = Counter()
    fallback: List[str] = []
    for p in patches:
        for e in p["set"].get("evidence", []):
            rid = e.get("rule_id")
            if rid:
                rule_hits[rid] += 1
        if any(e.get("rule_id") == "R010" for e in p["set"].get("evidence", [])):
            fallback.append(p["unit_id"])
    total = len(patches)
    pkgs = Counter(u.rsplit("/", 1)[0] for u in fallback)
    return {
        "policy_mode": mode,
        "total_units": total,
        "by_disposition": delta["summary"]["by_disposition"],
        "by_semantic": delta["summary"]["by_semantic"],
        "c6_ratio": delta["summary"]["c6_ratio"],
        "fallback_units": len(fallback),
        "fallback_ratio": round(len(fallback) / total, 4) if total else 0.0,
        "warnings": len(delta["warnings"]),
        "low_confidence_units": delta["summary"]["low_confidence_units"],
        "rule_hits": dict(sorted(rule_hits.items())),
        "fallback_top_packages": [{"package": k, "count": v}
                                  for k, v in pkgs.most_common(8)],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M4 第二样本泛化验证")
    ap.add_argument("--samples", required=True, type=Path,
                    help="JSON: [{id, jar, policy, baseline?}]")
    ap.add_argument("--profile", type=Path, default=ROOT / "profiles/forge/1.20.1.json")
    ap.add_argument("--rules", type=Path, default=ROOT / "rules/classification.rules.json")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)

    samples = load(a.samples)
    profile = load(a.profile)
    rules = load(a.rules)
    C.verify_profile_symbols(profile, rules)

    results: List[Dict[str, Any]] = []
    for s in samples:
        jar = ROOT / s["jar"] if not Path(s["jar"]).is_absolute() else Path(s["jar"])
        policy = load(ROOT / s["policy"]) if not Path(s["policy"]).is_absolute() else load(Path(s["policy"]))
        code_mode = policy["scope_decisions"]["code"]["mode"]
        entry: Dict[str, Any] = {
            "id": s["id"],
            "artifact": jar.name,
            "baseline": bool(s.get("baseline")),
            "license_raw": policy.get("license_raw"),
            "code_policy_mode": code_mode,
            "single_license_broadcast": policy.get("single_license_broadcast", False),
            "shape": jar_shape(jar),
            "by_mode": {},
        }
        for mode in MODES:
            effective = code_mode if mode == "full-inspection" else (
                "metadata-only" if code_mode == "full-inspection" else code_mode)
            r = run_one(jar, s["id"], effective, policy, profile, rules)
            r["requested_mode"] = mode
            r["effective_mode"] = effective
            entry["by_mode"][mode] = r
        results.append(entry)
        print("  %-22s class=%-5d full C6=%.4f fallback=%-4d meta C6=%.4f"
              % (s["id"], entry["shape"]["class_files"],
                 entry["by_mode"]["full-inspection"]["c6_ratio"],
                 entry["by_mode"]["full-inspection"]["fallback_units"],
                 entry["by_mode"]["metadata-only"]["c6_ratio"]))

    primary = "full-inspection"
    others = [r for r in results if not r["baseline"]]
    failures = []
    for r in others:
        m = r["by_mode"][primary]
        if m["c6_ratio"] > C6_THRESHOLD:
            failures.append("%s: C6=%.4f > %.2f" % (r["id"], m["c6_ratio"], C6_THRESHOLD))
        if m["fallback_ratio"] > FALLBACK_THRESHOLD:
            failures.append("%s: fallback=%.4f > %.2f" % (r["id"], m["fallback_ratio"], FALLBACK_THRESHOLD))

    report = {
        "schema_version": "0.1.0",
        "generated_by": "m4-generalize@0.1.0",
        "profile": a.profile.as_posix().replace(str(ROOT).replace("\\", "/") + "/", ""),
        "rules": a.rules.as_posix().replace(str(ROOT).replace("\\", "/") + "/", ""),
        "primary_mode": primary,
        "criteria": {"c6_ratio_max": C6_THRESHOLD, "fallback_ratio_max": FALLBACK_THRESHOLD,
                     "note": "阈值先于实验写死，不事后调参"},
        "samples": results,
        "comparison": [
            {"id": r["id"],
             "class_files": r["shape"]["class_files"],
             "c6_full": r["by_mode"]["full-inspection"]["c6_ratio"],
             "c6_metadata": r["by_mode"]["metadata-only"]["c6_ratio"],
             "fallback_full": r["by_mode"]["full-inspection"]["fallback_units"],
             "warnings_full": r["by_mode"]["full-inspection"]["warnings"],
             "c1_full": r["by_mode"]["full-inspection"]["by_disposition"].get("C1", 0)}
            for r in results
        ],
        "verdict": "generalizes" if not failures else "needs_new_rules",
        "failures": failures,
        "findings": [],
        "limitations": [
            "所有样本同为 Forge 1.20.1，因此只检验「换 mod」的泛化，不检验跨版本",
            "报告只含统计与包名计数；jar / 反编译产物只留 work/",
            "ARR 样本触发 review_required，其 full-inspection 结果仅用于本地统计比较",
        ],
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK samples=%d verdict=%s failures=%d out=%s"
          % (len(results), report["verdict"], len(failures), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
