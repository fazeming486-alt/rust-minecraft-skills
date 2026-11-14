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
                "matched": True, "note": pattern.get("note")}
    return {"pattern_id": None, "scope": None, "mode": profiles["default_mode"],
            "redistribution": profiles["default_redistribution"],
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
    for scope in profiles["scopes"]:
        scoped = [f for f in findings if f["scope"] == scope and f["matched"]]
        if scoped:
            strictest = max(scoped, key=lambda f: severity[f["mode"]])
            scope_decisions[scope] = {
                "mode": strictest["mode"],
                "redistribution": all(f["redistribution"] for f in scoped),
                "based_on": [f["pattern_id"] for f in scoped],
            }
        else:
            scope_decisions[scope] = {
                "mode": "oracle-only" if scope == "assets" else profiles["default_mode"],
                "redistribution": profiles["default_redistribution"],
                "based_on": [],
            }

    if override:
        for scope in scope_decisions:
            scope_decisions[scope]["mode"] = override
            scope_decisions[scope]["based_on"] = ["explicit_user_override"]

    modes = [d["mode"] for d in scope_decisions.values()]
    overall = max(modes, key=lambda m: severity[m])
    review = (not license_raw.strip()) or any(not f["matched"] for f in findings) or bool(override)

    return {
        "schema_version": "0.1.0",
        "artifact_id": artifact_id,
        "license_raw": license_raw,
        "segments": findings,
        "scope_decisions": scope_decisions,
        "mode": overall,
        "policy_mode": overall,
        "redistribution": all(d["redistribution"] for d in scope_decisions.values()),
        "review_required": review,
        "decided_by": "policy-gate@0.1.0",
        "ruleset": "policy/license-profiles.json",
        "note": "下游解析器必须按 policy_mode 降级；review_required 时必须人工签署后再继续",
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
        print("    %-7s %-16s based_on=%s" % (scope, value["mode"], value["based_on"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
