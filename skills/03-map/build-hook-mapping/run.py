#!/usr/bin/env python3
"""build-hook-mapping 执行层：转发 tools/build_hook_mapping.py。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import build_hook_mapping  # noqa: E402


def main(argv=None) -> int:
    return build_hook_mapping.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
