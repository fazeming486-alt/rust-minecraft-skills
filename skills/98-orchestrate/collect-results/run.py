#!/usr/bin/env python3
"""collect-results 执行层：转发 tools/collect_results.py。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import collect_results  # noqa: E402


def main(argv=None) -> int:
    return collect_results.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
