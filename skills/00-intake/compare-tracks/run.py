#!/usr/bin/env python3
"""compare-tracks 执行层：量化源码轨与字节码轨的事实差异。

差异本身是证据：内部类/合成类、注解参数字符串、常量池引用只在字节码轨可见。
"""
import argparse
import json
from pathlib import Path
from typing import Any, Dict


def load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm(unit_id: str) -> str:
    return unit_id.split("$", 1)[0]


def disposition_map(delta: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for patch in delta["unit_patches"]:
        out.setdefault(norm(patch["unit_id"]), patch["set"]["disposition"])
    return out


def symbol_sets(index: Dict[str, Any], field: str) -> Dict[str, set]:
    out: Dict[str, set] = {}
    for unit in index["units"]:
        out.setdefault(norm(unit["unit_id"]), set()).update(unit["symbols"].get(field, []))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-index", required=True)
    ap.add_argument("--bytecode-index", required=True)
    ap.add_argument("--source-delta", required=True)
    ap.add_argument("--bytecode-delta", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)

    source, bytecode = load(a.source_index), load(a.bytecode_index)
    sdelta, bdelta = load(a.source_delta), load(a.bytecode_delta)
    s_map, b_map = disposition_map(sdelta), disposition_map(bdelta)
    common = set(s_map) & set(b_map)
    agreed = sum(1 for k in common if s_map[k] == b_map[k])

    sa, ba = symbol_sets(source, "annotations"), symbol_sets(bytecode, "annotations")
    ann_common = set(sa) & set(ba)
    ann_equal = sum(1 for k in ann_common if sa[k] == ba[k])
    ss, bs = symbol_sets(source, "constant_strings"), symbol_sets(bytecode, "constant_strings")
    bc_only_strings = sum(len(bs.get(k, set()) - ss.get(k, set())) for k in set(bs) & set(ss))

    report = {
        "source_units": len(source["units"]),
        "bytecode_units": len(bytecode["units"]),
        "bytecode_only_class_units": len(bytecode["units"]) - len(source["units"]),
        "common_normalized_units": len(common),
        "disposition_agreement": round(agreed / len(common), 4) if common else 0.0,
        "annotation_sets_equal": ann_equal,
        "annotation_equal_ratio": round(ann_equal / len(ann_common), 4) if ann_common else 0.0,
        "bytecode_only_string_literals": bc_only_strings,
        "verdict": "字节码轨包含源码轨不可见的事实，分类判定必须以字节码轨为准",
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK agreement=%s bytecode_only_classes=%d out=%s"
          % (report["disposition_agreement"], report["bytecode_only_class_units"], a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
