#!/usr/bin/env python3
"""S1 确定性分诊器 (classify-java-decompiled v0.1.0)。

仅依赖 Python 标准库。读 artifact-index + forge profile + 符号规则，
输出 delta（补丁），不覆写整份 manifest。零模型参与。

用法:
  python tools/classify.py --index <artifact-index.json> \
      --profile <profile.json> --rules <rules.json> --out <delta.json>
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SKILL_ID = "classify-java-decompiled"
SKILL_VERSION = "0.1.0"


class ClassificationError(Exception):
    pass


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def norm_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_input_hash(index: Any, profile: Any, rules: Any) -> str:
    payload = norm_json(index) + norm_json(profile) + norm_json(rules)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_field(unit: Dict[str, Any], dotted: str) -> Any:
    cur: Any = unit
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def expand(profile: Dict[str, Any], group: str, name: str) -> List[str]:
    symbols = profile.get("symbols", {})
    if group not in symbols or name not in symbols[group]:
        raise ClassificationError(
            "profile %r 缺符号 (%s, %s)：版本档必须显式提供，禁止静默失配"
            % (profile.get("profile_id"), group, name)
        )
    values = symbols[group][name]
    if not isinstance(values, list) or not values:
        raise ClassificationError("符号 (%s, %s) 的展开值不能为空" % (group, name))
    return [str(v) for v in values]


def expand_many(profile: Dict[str, Any], group: str, names: List[str]) -> List[str]:
    out: List[str] = []
    for name in names:
        out.extend(expand(profile, group, name))
    return out


def collect_symbol_refs(node: Any, refs: set) -> None:
    if isinstance(node, list):
        for item in node:
            collect_symbol_refs(item, refs)
        return
    if not isinstance(node, dict):
        return
    ctype = node.get("type")
    if ctype in ("symbol_in", "symbol_contains_any", "symbol_glob_any"):
        if "group" in node and "name" in node:
            refs.add((node["group"], node["name"]))
    elif ctype == "symbol_prefix_in":
        for name in node.get("names", []):
            refs.add((node.get("group"), name))
    elif ctype == "not":
        collect_symbol_refs(node.get("condition", {}), refs)
    for key in ("all", "any"):
        if key in node:
            collect_symbol_refs(node[key], refs)
    for item in node.values():
        if isinstance(item, (dict, list)):
            collect_symbol_refs(item, refs)


def verify_profile_symbols(profile: Dict[str, Any], rules: Dict[str, Any]) -> None:
    refs: set = set()
    collect_symbol_refs(rules.get("rules", []), refs)
    for group, name in sorted(refs, key=lambda x: (str(x[0]), str(x[1]))):
        expand(profile, group, name)


def eval_condition(cond: Dict[str, Any], unit: Dict[str, Any],
                   profile: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    ctype = cond.get("type")

    if ctype == "always":
        return True, None

    if ctype == "flag_is":
        ok = get_field(unit, cond["field"]) == cond["value"]
        return ok, "%s=%s" % (cond["field"], cond["value"]) if ok else None

    if ctype == "kind_in":
        return (unit.get("kind") in cond["values"]), None

    if ctype == "count_gte":
        value = get_field(unit, cond["field"])
        n = len(as_list(value)) if not isinstance(value, (int, float)) else value
        ok = isinstance(n, (int, float)) and n >= cond["value"]
        return ok, "%s=%s" % (cond["field"], n) if ok else None

    if ctype == "count_lte":
        value = get_field(unit, cond["field"])
        n = len(as_list(value)) if not isinstance(value, (int, float)) else value
        ok = isinstance(n, (int, float)) and n <= cond["value"]
        return ok, "%s=%s" % (cond["field"], n) if ok else None

    if ctype == "not":
        inner_ok, _ = eval_condition(cond["condition"], unit, profile)
        return (not inner_ok), None

    literals = expand(profile, cond["group"], cond["name"]) if ctype in (
        "symbol_in", "symbol_contains_any", "symbol_glob_any") else None

    if ctype == "symbol_prefix_in":
        literals = expand_many(profile, cond["group"], cond["names"])
        values = as_list(get_field(unit, cond["field"]))
        for value in values:
            for literal in literals:
                if value.startswith(literal):
                    return True, value
        return False, None

    values = as_list(get_field(unit, cond["field"]))

    if ctype == "symbol_glob_any":
        for value in values:
            for pattern in literals or []:
                if fnmatch.fnmatch(value, pattern):
                    return True, value
        return False, None

    if ctype == "symbol_in":
        for value in values:
            for literal in literals or []:
                if value == literal:
                    return True, value
        return False, None

    if ctype == "symbol_contains_any":
        for value in values:
            for literal in literals or []:
                if literal in value:
                    return True, value
        return False, None

    raise ClassificationError("未知条件类型: %r" % ctype)


def eval_when(when: Dict[str, Any], unit: Dict[str, Any],
              profile: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    if "all" in when:
        matched: Optional[str] = None
        for child in when["all"]:
            ok, child_matched = eval_when(child, unit, profile)
            if not ok:
                return False, None
            if matched is None:
                matched = child_matched
        return True, matched
    if "any" in when:
        for child in when["any"]:
            ok, child_matched = eval_when(child, unit, profile)
            if ok:
                return True, child_matched
        return False, None
    return eval_condition(when, unit, profile)


EVIDENCE_SOURCE = {
    "annotation": "bytecode", "import_prefix": "bytecode", "superclass": "bytecode",
    "method_signature": "bytecode", "package_glob": "path", "constant_string": "bytecode",
    "call_graph": "derived", "flag": "bytecode", "kind": "path", "path": "path",
    "fallback": "derived",
}


def classify(index: Dict[str, Any], profile: Dict[str, Any],
             rules: Dict[str, Any]) -> Dict[str, Any]:
    verify_profile_symbols(profile, rules)
    input_hash = compute_input_hash(index, profile, rules)
    threshold = float(rules.get("low_confidence_threshold", 0.70))
    carrier_by_kind = rules.get("carrier_by_kind", {})
    ordered = sorted(rules["rules"], key=lambda r: r["priority"])

    patches: List[Dict[str, Any]] = []
    warnings: List[str] = []
    by_disposition: Dict[str, int] = {}
    by_semantic: Dict[str, int] = {}
    low_confidence: List[str] = []
    c6_count = 0

    for unit in index["units"]:
        unit_id = unit["unit_id"]
        hits: List[Tuple[Dict[str, Any], Optional[str]]] = []
        for rule in ordered:
            ok, matched = eval_when(rule["when"], unit, profile)
            if ok:
                hits.append((rule, matched))
        if not hits:
            raise ClassificationError("unit %s 未命中任何规则（兜底规则缺失）" % unit_id)

        non_fallback = [h for h in hits if h[0]["then"]["evidence_kind"] != "fallback"]
        recorded = non_fallback if non_fallback else hits
        primary_rule, _ = hits[0]
        then = dict(primary_rule["then"])
        by_kind = then.get("by_kind", {}).get(unit.get("kind"))
        if by_kind:
            then.update(by_kind)

        evidence = [
            {
                "rule_id": rule["id"],
                "kind": then_kind,
                "matched": matched_value,
                "source": EVIDENCE_SOURCE.get(then_kind, "derived"),
            }
            for rule, matched in recorded
            for then_kind in [rule["then"]["evidence_kind"]]
            for matched_value in [matched if matched is not None
                                  else (unit.get("kind") if then_kind == "kind" else None)]
        ]

        confidence = float(then["confidence"])
        disposition = then["disposition"]
        requires_drilldown = len(non_fallback) >= 2
        carrier = then.get("carrier_override") or carrier_by_kind.get(unit.get("kind"), "source")
        delta = then.get("behavior_delta")
        behavior_delta = None
        if delta:
            behavior_delta = {
                "delta_target": None,
                "delta_semantics": None,
                "hook_candidate": delta.get("hook_candidate"),
            }

        patch_set = {
            "carrier": carrier,
            "semantic": then["semantic"],
            "semantic_subtype": then.get("semantic_subtype"),
            "disposition": disposition,
            "evidence": evidence,
            "confidence": confidence,
            "review_state": "unreviewed",
            "requires_drilldown": requires_drilldown,
            "behavior_delta": behavior_delta,
            "provenance": {
                "skill_id": SKILL_ID,
                "skill_version": SKILL_VERSION,
                "input_hash": input_hash,
            },
        }
        patches.append({"unit_id": unit_id, "set": patch_set})

        by_disposition[disposition] = by_disposition.get(disposition, 0) + 1
        by_semantic[then["semantic"]] = by_semantic.get(then["semantic"], 0) + 1
        if confidence < threshold:
            low_confidence.append(unit_id)
            warnings.append("low_confidence:%s:%s" % (unit_id, confidence))
        if disposition == "C6":
            c6_count += 1
            warnings.append("review_required:%s" % unit_id)
        if requires_drilldown:
            warnings.append("drilldown:%s" % unit_id)

    total = len(index["units"])
    return {
        "delta_id": "dlt-" + input_hash[7:23],
        "skill_id": SKILL_ID,
        "skill_version": SKILL_VERSION,
        "input_hash": input_hash,
        "created_at": None,
        "summary": {
            "total_units": total,
            "by_disposition": dict(sorted(by_disposition.items())),
            "by_semantic": dict(sorted(by_semantic.items())),
            "low_confidence_units": low_confidence,
            "c6_ratio": round(c6_count / total, 4) if total else 0.0,
        },
        "unit_patches": patches,
        "contracts_add": [],
        "gaps_add": [],
        "warnings": warnings,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="S1 确定性五维分诊器")
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        delta = classify(load_json(args.index), load_json(args.profile), load_json(args.rules))
    except ClassificationError as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(delta, f, ensure_ascii=False, indent=2)
        f.write("\n")

    s = delta["summary"]
    print("OK  units=%d  dispositions=%s  C6_ratio=%s  warnings=%d"
          % (s["total_units"], s["by_disposition"], s["c6_ratio"], len(delta["warnings"])))
    print("    input_hash=%s" % delta["input_hash"])
    print("    out=%s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
