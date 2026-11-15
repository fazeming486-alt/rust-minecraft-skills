#!/usr/bin/env python3
"""构建跨层特性切片：把资产、代码、目标能力与状态契约缝成单一迁移单元。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import build_feature_slices as B  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="构建跨层特性切片")
    ap.add_argument("--jar", required=True, type=Path)
    ap.add_argument("--index", required=True, type=Path)
    ap.add_argument("--delta", required=True, type=Path)
    ap.add_argument("--anchors", type=Path,
                    default=ROOT / "orchestration/slice-anchors.json")
    ap.add_argument("--horizon-hooks", required=True, type=Path)
    ap.add_argument("--capabilities", type=Path,
                    default=ROOT / "target/horizon.capabilities.json")
    ap.add_argument("--policy-decision", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)

    forwarded = ["--jar", str(a.jar), "--index", str(a.index), "--delta", str(a.delta),
                 "--anchors", str(a.anchors), "--horizon-hooks", str(a.horizon_hooks),
                 "--capabilities", str(a.capabilities),
                 "--policy-decision", str(a.policy_decision), "--out", str(a.out)]
    return B.main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
