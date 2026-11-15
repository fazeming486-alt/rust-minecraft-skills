#!/usr/bin/env python3
"""verify-generalization 执行层：转发到 tools/m4_generalize.py。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import m4_generalize as M  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="第二样本泛化验证")
    ap.add_argument("--samples", required=True, type=Path)
    ap.add_argument("--profile", type=Path)
    ap.add_argument("--rules", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    args = ["--samples", str(a.samples), "--out", str(a.out)]
    if a.profile:
        args += ["--profile", str(a.profile)]
    if a.rules:
        args += ["--rules", str(a.rules)]
    return M.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
