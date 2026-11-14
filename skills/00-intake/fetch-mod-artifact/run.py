#!/usr/bin/env python3
"""fetch-mod-artifact 执行层：下载第三方产物、校验 sha256、记录 provenance。

产物只允许落在 work/ 等被 .gitignore 排除的目录，绝不入库。
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--expected-sha256")
    ap.add_argument("--provenance-out", type=Path)
    ap.add_argument("--timeout", type=int, default=180)
    a = ap.parse_args(argv)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["curl", "-sS", "-L", "--max-time", str(a.timeout), "-o", str(a.out), a.url],
        capture_output=True, text=True)
    if result.returncode != 0 or not a.out.is_file() or a.out.stat().st_size == 0:
        print("FAIL download: %s" % result.stderr.strip(), file=sys.stderr)
        return 2

    digest = hashlib.sha256(a.out.read_bytes()).hexdigest()
    if a.expected_sha256 and digest != a.expected_sha256:
        print("FAIL checksum mismatch: %s" % digest, file=sys.stderr)
        return 3

    prov = {"url": a.url, "path": str(a.out), "size_bytes": a.out.stat().st_size,
            "sha256": digest,
            "license_note": "第三方产物仅可存于 work/，禁止入库；Code GPL-3.0 / Assets CC BY-NC-ND 4.0"}
    if a.provenance_out:
        a.provenance_out.parent.mkdir(parents=True, exist_ok=True)
        a.provenance_out.write_text(json.dumps(prov, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    print("OK sha256=%s size=%d out=%s" % (digest, prov["size_bytes"], a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
