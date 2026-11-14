#!/usr/bin/env python3
"""结果汇总器：收集子 agent 的 result，校验契约与 policy 越界。

子 agent 之间不通信，只把 result 写到约定路径；本脚本是唯一汇总入口。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

FORBIDDEN_RESULT_KEYS = {
    "asset_content", "source_text", "constant_strings", "string_literals",
    "annotation_values", "method_bodies", "raw_bytes",
}


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, type=Path, help="work/dispatch/index.json")
    ap.add_argument("--packs-dir", required=True, type=Path)
    ap.add_argument("--results-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--allow-missing", action="store_true",
                    help="规划阶段允许 result 缺失，只列为阻塞项")
    a = ap.parse_args(argv)

    index = load(a.index)
    items: List[Dict[str, Any]] = []
    violations: List[str] = []
    completed = 0
    missing = 0

    for entry in index["packs"]:
        task_id = entry["task_id"]
        pack = load(a.packs_dir / (task_id + ".json"))
        result_path = a.results_dir / (task_id + ".json")
        item: Dict[str, Any] = {"task_id": task_id, "role": entry["role"],
                               "policy_mode": entry["policy_mode"],
                               "assigned_worker": entry["assigned_worker"]}
        if not result_path.is_file():
            item["status"] = "missing"
            missing += 1
        else:
            result = load(result_path)
            item["status"] = result.get("status", "unknown")
            problems = []
            if result.get("task_id") != task_id:
                problems.append("task_id 不匹配")
            if not result.get("evidence"):
                problems.append("缺 evidence")
            if entry["policy_mode"] == "oracle-only":
                leaked = FORBIDDEN_RESULT_KEYS & set(result)
                if leaked:
                    problems.append("oracle-only 越界字段: %s" % sorted(leaked))
            if pack["input_hash"] != result.get("input_hash"):
                problems.append("input_hash 不匹配（任务包已变更）")
            if problems:
                item["problems"] = problems
                violations.append("%s: %s" % (task_id, "; ".join(problems)))
                item["status"] = "violation"
            else:
                completed += 1
        items.append(item)

    report = {
        "schema_version": "0.1.0",
        "milestone": index["milestone"],
        "total": len(items),
        "completed": completed,
        "missing": missing,
        "violations": violations,
        "human_gate": index["complexity"]["human_gate"],
        "waves": index["waves"],
        "items": items,
        "verdict": "BLOCKED" if violations else ("PARTIAL" if missing else "COMPLETE"),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK total=%d completed=%d missing=%d violations=%d verdict=%s out=%s"
          % (report["total"], completed, missing, len(violations), report["verdict"], a.out))
    if violations and not a.allow_missing:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
