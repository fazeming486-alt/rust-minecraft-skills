#!/usr/bin/env python3
"""estimate-complexity 执行层：转发 tools/estimate_complexity.py。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import estimate_complexity  # noqa: E402


def main(argv=None) -> int:
    return estimate_complexity.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
