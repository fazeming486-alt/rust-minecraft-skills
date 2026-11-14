#!/usr/bin/env python3
"""parse-java-source 执行层：把 Java 源码树变成 artifact-index（源码轨）。"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import lib_facts as L  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path, help="源码仓库根目录")
    ap.add_argument("--source-root", default="src/main/java")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--loader-profile", default="forge/1.20.1")
    a = ap.parse_args(argv)

    index = L.index_from_source_tree(a.root, a.source_root)
    index["source"]["loader_profile"] = a.loader_profile
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK source-track units=%d out=%s" % (len(index["units"]), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
