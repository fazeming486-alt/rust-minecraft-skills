#!/usr/bin/env python3
"""plan-dispatch 执行层：转发 tools/plan_dispatch.py。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import plan_dispatch  # noqa: E402


def main(argv=None) -> int:
    return plan_dispatch.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
