#!/usr/bin/env python3
"""parse-bytecode 执行层：解析 jar 内 class 常量池，生成 artifact-index（ground truth 轨）。

仅用 Python 标准库，不依赖 javap / 反编译器 / 外部 mappings 即可提取注解、
类型引用、字符串常量、声明类型与合成类标记。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import lib_facts as L  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jar", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--loader-profile", default="forge/1.20.1")
    ap.add_argument("--policy-mode", choices=list(L.POLICY_MODES), default=None)
    ap.add_argument("--policy-decision", type=Path, help="policy-gate 输出的 JSON")
    a = ap.parse_args(argv)

    policy = None
    if a.policy_decision:
        policy = json.loads(a.policy_decision.read_text(encoding="utf-8"))
    if a.policy_mode:
        mode = a.policy_mode
    elif policy:
        mode = policy.get("scope_decisions", {}).get("code", {}).get("mode", "full-inspection")
    else:
        mode = "full-inspection"
    if policy:
        gate_mode = policy.get("mode")
        policy = dict(policy)
        policy["gate_overall_mode"] = gate_mode
        policy["effective_mode"] = mode
        policy["mode"] = mode
    index = L.index_from_jar(a.jar, policy_mode=mode, policy=policy)
    index["source"]["loader_profile"] = a.loader_profile
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK bytecode-track units=%d out=%s" % (len(index["units"]), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
