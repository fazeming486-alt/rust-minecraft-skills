#!/usr/bin/env python3
"""policy-gate 执行层：S0 第一道合规门禁（ADR 0006 方案 C）。

从 jar 元数据或显式 license 串判定 (scope × license) 的 policy_mode，
输出 work/policy-decision.json 供下游解析器 --policy-mode 使用。
任何解析失败一律 default_deny + review_required。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]
RE_TOML_LICENSE = re.compile(r'^\s*license\s*=\s*"([^"]*)"', re.M)


def read_license_from_jar(jar: Path) -> str:
    with zipfile.ZipFile(jar) as zf:
        names = set(zf.namelist())
        if "META-INF/mods.toml" in names:
            text = zf.read("META-INF/mods.toml").decode("utf-8", errors="replace")
            match = RE_TOML_LICENSE.search(text)
            if match:
                return match.group(1).strip()
        if "fabric.mod.json" in names:
            meta = json.loads(zf.read("fabric.mod.json").decode("utf-8", errors="replace"))
            value = meta.get("license")
            if isinstance(value, list):
                return " / ".join(str(v) for v in value)
            if value:
                return str(value)
    return ""


def split_license(raw: str, tokens: List[str]) -> List[str]:
    text = raw
    for token in tokens:
        text = text.replace(token, "|")
    return [part.strip() for part in text.split("|") if part.strip()]


def match_segment(segment: str, profiles: Dict[str, Any]) -> Dict[str, Any]:
    low = segment.lower()
    for pattern in sorted(profiles["license_patterns"], key=lambda p: p["priority"]):
        if not any(keyword in low for keyword in pattern["match_any"]):
            continue
        if any(excluded in low for excluded in pattern.get("exclude_any", [])):
            continue
        return {"pattern_id": pattern["id"], "scope": pattern["scope"],
                "mode": pattern["mode"], "redistribution": pattern["redistribution"],
                "transformation": pattern.get("transformation", profiles["default_transformation"]),
                "distribution": pattern.get("distribution", profiles["default_distribution"]),
                "matched": True, "note": pattern.get("note")}
    return {"pattern_id": None, "scope": None, "mode": profiles["default_mode"],
            "redistribution": profiles["default_redistribution"],
            "transformation": profiles["default_transformation"],
            "distribution": profiles["default_distribution"],
            "matched": False, "note": "未匹配规则，default_deny"}


def decide(license_raw: str, profiles: Dict[str, Any], artifact_id: str,
           override: str | None = None) -> Dict[str, Any]:
    severity = profiles["severity"]
    segments = split_license(license_raw, profiles["split_tokens"]) if license_raw else []
    findings = []
    for segment in segments:
        finding = match_segment(segment, profiles)
        finding["segment"] = segment
        findings.append(finding)

    scope_decisions: Dict[str, Dict[str, Any]] = {}
    t_sev = {"none": 2, "technical-only": 1, "creative": 0, "port": 0}
    d_sev = {"local-only": 1, "redistributable": 0}
    for scope in profiles["scopes"]:
        scoped = [f for f in findings if f["scope"] == scope and f["matched"]]
        if scoped:
            strictest = max(scoped, key=lambda f: severity[f["mode"]])
            scope_decisions[scope] = {
                "mode": strictest["mode"],
                "transformation": max((f["transformation"] for f in scoped), key=lambda t: t_sev[t]),
                "distribution": max((f["distribution"] for f in scoped), key=lambda d: d_sev[d]),
                "redistribution": all(f["redistribution"] for f in scoped),
                "based_on": [f["pattern_id"] for f in scoped],
            }
        else:
            scope_decisions[scope] = {
                "mode": "oracle-only" if scope == "assets" else profiles["default_mode"],
                "transformation": profiles["default_transformation"],
                "distribution": profiles["default_distribution"],
                "redistribution": profiles["default_redistribution"],
                "based_on": [],
            }

    # 单一许可证串跨 scope 广播（v0.8）：只在「单段且恰好一条规则命中」时生效；
    # 完全无匹配仍保持 default_deny，TaCZ 这类明确分段的多段串不受影响。
    broadcast = profiles.get("single_license_broadcast", {})
    matched = [f for f in findings if f["matched"]]
    broadcast_applied = False
    if (broadcast.get("enabled") and len(segments) == 1
            and len(matched) == 1 and not override):
        src = matched[0]
        for scope in profiles["scopes"]:
            if scope_decisions[scope]["based_on"]:
                continue
            scope_decisions[scope] = {
                "mode": src["mode"],
                "transformation": src["transformation"],
                "distribution": src["distribution"],
                "redistribution": src["redistribution"],
                "based_on": [src.get("pattern_id"), broadcast.get("based_on_tag", "single_license_broadcast")],
            }
            broadcast_applied = True

    if override:
        for scope in scope_decisions:
            scope_decisions[scope]["mode"] = override
            scope_decisions[scope]["based_on"] = ["explicit_user_override"]

    modes = [d["mode"] for d in scope_decisions.values()]
    overall = max(modes, key=lambda m: severity[m])
    overall_transform = max((d["transformation"] for d in scope_decisions.values()),
                            key=lambda t: t_sev[t])
    overall_distribution = max((d["distribution"] for d in scope_decisions.values()),
                               key=lambda d: d_sev[d])
    review = ((not license_raw.strip()) or any(not f["matched"] for f in findings)
              or bool(override)
              or (broadcast_applied and broadcast.get("review_required_when_broadcast", True)))

    return {
        "schema_version": "0.2.0",
        "artifact_id": artifact_id,
        "license_raw": license_raw,
        "segments": findings,
        "scope_decisions": scope_decisions,
        "mode": overall,
        "policy_mode": overall,
        "transformation": overall_transform,
        "distribution": overall_distribution,
        "distribution_conditions": profiles["distribution_conditions"].get(overall_distribution, []),
        "redistribution": all(d["redistribution"] for d in scope_decisions.values()),
        "review_required": review,
        "single_license_broadcast": broadcast_applied,
        "decided_by": "policy-gate@0.3.0",
        "ruleset": "policy/license-profiles.json",
        "note": "三维度决策（ADR 0008）：inspection / transformation / distribution。技术性转换可做，改编版不得发布或商用。",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jar", type=Path, help="从 jar 元数据读 license")
    ap.add_argument("--license", help="显式给出 license 原始串（优先于 --jar）")
    ap.add_argument("--artifact-id", default="unknown")
    ap.add_argument("--profiles", type=Path, default=ROOT / "policy/license-profiles.json")
    ap.add_argument("--override", choices=["full-inspection", "metadata-only", "oracle-only"])
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    profiles = json.loads(args.profiles.read_text(encoding="utf-8"))
    raw = args.license
    if raw is None and args.jar:
        try:
            raw = read_license_from_jar(args.jar)
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            print("FAIL reading jar metadata: %s" % exc, file=sys.stderr)
            return 2
    raw = raw or ""

    decision = decide(raw, profiles, args.artifact_id, args.override)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK license=%r mode=%s redistribution=%s review_required=%s out=%s"
          % (raw, decision["policy_mode"], decision["redistribution"],
             decision["review_required"], args.out))
    for scope, value in decision["scope_decisions"].items():
        print("    %-7s %-16s transform=%-15s distribution=%-14s based_on=%s"
              % (scope, value["mode"], value["transformation"], value["distribution"],
                 value["based_on"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
