#!/usr/bin/env python3
"""从分诊 delta 生成平台无关的 C1/C2 录制契约骨架（确定性、零模型参与）。

骨架的 input_sequence / state_sequence 是待录制占位：真实序列必须由 dev-only
Java oracle 产生，脚本绝不编造观测数据。oracle.status 一律 pending。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lib_conversion as C  # noqa: E402


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def capabilities_for(unit_id: str, subtype: str, mapping: Dict[str, Any]) -> List[str]:
    cls = unit_id.rsplit("/", 1)[-1]
    for rule in mapping["rules"]:
        tokens = rule.get("match_class_tokens")
        if tokens and any(t.lower() in cls.lower() for t in tokens):
            return list(rule["capability_ids"])
        if rule.get("match_subtype") and rule["match_subtype"] == subtype:
            return list(rule["capability_ids"])
    return list(mapping["default"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 C1/C2 录制契约骨架")
    ap.add_argument("--delta", required=True, type=Path)
    ap.add_argument("--slices", required=True, type=Path,
                    help="feature-slices 报告，用于取 shared_states 全集")
    ap.add_argument("--vocabulary", type=Path,
                    default=ROOT / "capabilities/vocabulary.json")
    ap.add_argument("--map", dest="mapping", type=Path,
                    default=ROOT / "orchestration/recording-capability-map.json")
    ap.add_argument("--policy-decision", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0, help="0 = 全部")
    a = ap.parse_args(argv)

    delta = load(a.delta)
    slices_doc = load(a.slices)
    vocab = load(a.vocabulary)
    mapping = load(a.mapping)
    policy = load(a.policy_decision)
    known_caps = {c["id"] for c in vocab["capabilities"]}
    shared_states = sorted({s for sl in slices_doc["slices"] for s in sl["shared_states"]})

    units = [p for p in delta["unit_patches"]
             if p["set"]["disposition"] in ("C1", "C2")]
    if a.limit:
        units = units[:a.limit]

    contracts = []
    from collections import Counter
    by_disp: Counter = Counter()
    used_caps = set()
    for i, p in enumerate(units, 1):
        s = p["set"]
        caps = capabilities_for(p["unit_id"], s.get("semantic_subtype", ""), mapping)
        unknown = [c for c in caps if c not in known_caps]
        if unknown:
            raise SystemExit("capability id 未在 vocabulary 中定义: %s" % unknown)
        used_caps.update(caps)
        by_disp[s["disposition"]] += 1
        contracts.append({
            "contract_id": "rc-%03d" % i,
            "unit_id": p["unit_id"],
            "disposition": s["disposition"],
            "semantic": s["semantic"],
            "capability_ids": caps,
            "input_sequence": [],
            "state_sequence": [],
            "assertions": list(mapping["assertion_templates"]),
            "oracle": {
                "status": "pending",
                "source": "dev-only Java oracle（未录制）",
                "note": "骨架不含观测数据；真实输入/状态序列必须由 Java 侧录制，禁止脚本或模型编造",
            },
        })

    code = policy["scope_decisions"]["code"]
    doc = {
        "schema_version": "0.1.0",
        "generated_by": "build-recording-contract@0.1.0",
        "source_artifact": delta.get("delta_id", "unknown"),
        "policy": {"inspection": code["mode"], "transformation": code["transformation"],
                   "distribution": code["distribution"]},
        "contracts": contracts,
        "summary": {
            "contract_count": len(contracts),
            "by_disposition": dict(sorted(by_disp.items())),
            "capability_ids": sorted(used_caps),
            "oracle_required": True,
            "offline_ready": False,
            "shared_state_universe_size": len(shared_states),
        },
    }
    C.write_json(a.out, doc)
    print("OK contracts=%d C1=%d C2=%d caps=%d shared_states=%d oracle=pending out=%s"
          % (len(contracts), by_disp["C1"], by_disp["C2"], len(used_caps),
             len(shared_states), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
