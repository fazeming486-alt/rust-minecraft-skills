#!/usr/bin/env python3
"""calibrate-classification 执行层：三轨实验 + 规则命中统计 + 脱敏报告。

所有参数原样转发给 tools/experiment.py；报告只含统计与 unit_id，不含第三方源码。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import experiment  # noqa: E402


def main(argv=None) -> int:
    return experiment.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
