#!/usr/bin/env python3
"""Horizon Rust 源码事实扫描器（纯标准库、确定性、零模型参与）。

把「读源码」变成可回归的取证：按探针配置提取声明位置、符号命中与缺失证据，
输出结构化 JSON。只记录行号与不超过 160 字符的短签名，不复制源码正文。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


DECL = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?"
    r"(?:unsafe\s+|async\s+|const\s+)*"
    r"(struct|enum|trait|fn|type|const|static|impl|mod)\s+([A-Za-z_][\w]*)")


def scan_file(path: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    if not path.is_file():
        return {"path": spec["path"], "exists": False, "lines": 0,
                "declarations": [], "pattern_hits": {}, "absence_hits": {}}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"path": spec["path"], "exists": False, "lines": 0,
                "declarations": [], "pattern_hits": {}, "absence_hits": {}}

    wanted = set(spec.get("declarations", []))
    decls: List[Dict[str, Any]] = []
    for i, line in enumerate(lines, 1):
        m = DECL.match(line)
        if m and (not wanted or m.group(2) in wanted):
            decls.append({"line": i, "kind": m.group(1), "name": m.group(2),
                          "signature": " ".join(line.split())[:160]})

    hits: Dict[str, Any] = {}
    for pat in spec.get("patterns", []):
        rx = re.compile(pat, re.I)
        found = [i for i, line in enumerate(lines, 1) if rx.search(line)]
        hits[pat] = {"count": len(found), "lines": found[:12]}

    absence: Dict[str, Any] = {}
    for pat in spec.get("absence_patterns", []):
        rx = re.compile(pat, re.I)
        found = [i for i, line in enumerate(lines, 1) if rx.search(line)]
        absence[pat] = {"count": len(found), "lines": found[:6]}

    return {"path": spec["path"], "exists": True, "lines": len(lines),
            "declarations": decls[:80], "pattern_hits": hits, "absence_hits": absence}


def scan_tree(root: Path, glob_patterns: List[str], keywords: List[str]) -> Dict[str, Any]:
    """全仓关键词缺席检查：用于证明某能力「确实不存在」，而不是没找到。"""
    out: Dict[str, Any] = {
        "files_scanned": 0, "keywords": {},
        "note": "tree_keywords 按正则大小写不敏感匹配；命中只说明该词出现，是否为目标能力需结合 files[].pattern_hits 与人工判读。skeleton 一类词可能指 vanilla 骷髅生物，不能据此认定存在骨骼动画。",
    }
    files = set()
    for pattern in glob_patterns:
        files |= {p for p in root.glob(pattern) if p.is_file() and ".git" not in p.parts}
    compiled = {k: re.compile(k, re.I) for k in keywords}
    found: Dict[str, List[str]] = {k: [] for k in keywords}
    for p in sorted(files):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out["files_scanned"] += 1
        for k, rx in compiled.items():
            if rx.search(text) and len(found[k]) < 12:
                found[k].append(p.relative_to(root).as_posix())
    out["keywords"] = {k: {"matching_files_sample": v, "sample_size": len(v)}
                       for k, v in found.items()}
    return out


def run_probe(root: Path, probe: Dict[str, Any]) -> Dict[str, Any]:
    files = [scan_file(root / spec["path"], spec) for spec in probe["files"]]
    tree = scan_tree(root, probe.get("tree_globs", ["crates/**/*.rs"]),
                     probe.get("tree_keywords", [])) if probe.get("tree_keywords") else None
    declared = {d["name"] for f in files for d in f["declarations"]}
    return {
        "schema_version": "0.1.0",
        "probe_id": probe["id"],
        "title": probe["title"],
        "horizon_root": root.as_posix(),
        "source_kind": "rust-source",
        "files": files,
        "declared_symbols": sorted(declared),
        "missing_files": [f["path"] for f in files if not f["exists"]],
        "tree_scan": tree,
        "invariants": [
            "只记录行号与 <=160 字符短签名，不复制源码正文",
            "absence_patterns / tree_keywords 用于证明能力缺席，命中数必须如实记录",
            "换 Horizon 快照后重跑即可对比，禁止手工编辑本报告"
        ],
    }


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
