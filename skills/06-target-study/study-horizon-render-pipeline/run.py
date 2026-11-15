#!/usr/bin/env python3
"""研读 Horizon 客户端渲染 / 手部 / 姿态管线，产出可回归的源码事实报告。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import lib_horizon_source as H  # noqa: E402

DEFAULT_PROBE = ROOT / "orchestration/horizon-probes/render-pipeline.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Horizon 渲染管线源码取证")
    ap.add_argument("--horizon-root", required=True, type=Path)
    ap.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)

    probe = H.load_json(a.probe)
    report = H.run_probe(a.horizon_root, probe)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("OK probe=%s files=%d declarations=%d missing=%d out=%s"
          % (probe["id"], len(report["files"]), len(report["declared_symbols"]),
             len(report["missing_files"]), a.out))
    for f in report["files"]:
        print("   %-70s lines=%-6d decls=%-3d %s"
              % (f["path"], f["lines"], len(f["declarations"]),
                 "" if f["exists"] else "MISSING"))
    if report["tree_scan"]:
        for k, v in report["tree_scan"]["keywords"].items():
            print("   tree %-30s files=%d" % (k, v["sample_size"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
