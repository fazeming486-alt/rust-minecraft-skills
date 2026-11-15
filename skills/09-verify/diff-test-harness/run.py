#!/usr/bin/env python3
"""diff-test-harness 执行层：行为差分 + 官方 harness result.json 桥接。

两种用法：
  1) --delta 存在时，先生成 C1/C2 录制契约骨架（oracle.status=pending，不编造观测）。
  2) 用 --contracts + --observations 跑差分断言，产出官方形状 result.json。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import build_recording_contract as B  # noqa: E402
import diff_assertions as D  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="行为差分与 harness 桥接")
    ap.add_argument("--delta", type=Path, help="分诊 delta；给定时先生成录制契约骨架")
    ap.add_argument("--policy-decision", type=Path)
    ap.add_argument("--slices", required=True, type=Path)
    ap.add_argument("--conversion", required=True, type=Path)
    ap.add_argument("--contracts", required=True, type=Path,
                    help="录制契约路径；--delta 给定时作为生成目标")
    ap.add_argument("--observations", type=Path, help="观测序列；缺省时只生成骨架")
    ap.add_argument("--mod-key", default="rustmc-skills")
    ap.add_argument("--result-out", type=Path)
    ap.add_argument("--report", type=Path)
    a = ap.parse_args(argv)

    if a.delta:
        if not a.policy_decision:
            raise SystemExit("--delta 需要 --policy-decision")
        b_args = ["--delta", str(a.delta), "--slices", str(a.slices),
                  "--policy-decision", str(a.policy_decision), "--out", str(a.contracts)]
        rc = B.main(b_args)
        if rc:
            return rc

    if not a.observations:
        print("OK 只生成录制契约骨架；真实观测需 dev-only Java oracle，未虚构")
        return 0
    if not a.result_out or not a.report:
        raise SystemExit("--observations 需要 --result-out 与 --report")
    return D.main([
        "--contracts", str(a.contracts), "--observations", str(a.observations),
        "--slices", str(a.slices), "--conversion", str(a.conversion),
        "--mod-key", a.mod_key, "--result-out", str(a.result_out),
        "--report", str(a.report),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
