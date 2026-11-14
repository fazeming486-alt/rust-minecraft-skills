#!/usr/bin/env python3
"""decompile-forge-jar 执行层：编排 Vineflower 反编译，记录工具版本与产物规模。

反编译源码是「源码轨」的补充，不是 ground truth；字节码轨由 parse-bytecode 负责。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decompiler", required=True, type=Path, help="vineflower-*.jar")
    ap.add_argument("--input", required=True, type=Path, help="mod jar")
    ap.add_argument("--out", required=True, type=Path, help="输出目录，需位于 work/")
    ap.add_argument("--java", default="java")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--report-out", type=Path)
    a = ap.parse_args(argv)

    a.out.mkdir(parents=True, exist_ok=True)
    cmd = [a.java, "-jar", str(a.decompiler), str(a.input), str(a.out)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout)
    except subprocess.TimeoutExpired:
        print("FAIL decompiler timeout", file=sys.stderr)
        return 2
    if result.returncode != 0:
        print("FAIL decompiler rc=%d: %s" % (result.returncode, result.stderr[-500:]), file=sys.stderr)
        return 3

    java_files = sorted(a.out.rglob("*.java"))
    report = {"decompiler": a.decompiler.name, "input": a.input.name,
              "decompiled_java_files": len(java_files),
              "note": "反编译源码会折叠内部类与合成方法；字节码轨才是 ground truth"}
    if a.report_out:
        a.report_out.parent.mkdir(parents=True, exist_ok=True)
        a.report_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    print("OK decompiled_java_files=%d out=%s" % (len(java_files), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
