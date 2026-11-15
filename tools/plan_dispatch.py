#!/usr/bin/env python3
"""派发规划器：把里程碑任务模板切成自包含的子 agent 任务包。

复杂度由 estimate_complexity.py 确定性给出；本脚本只做切分、角色绑定、
policy 传导与拓扑分批，不做任何语义判断。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def waves(tasks: List[Dict[str, Any]]) -> List[List[str]]:
    remaining = {t["id"]: t for t in tasks}
    done: set = set()
    out: List[List[str]] = []
    while remaining:
        ready = [tid for tid, t in remaining.items()
                 if all(dep in done for dep in t.get("depends_on", []))]
        if not ready:
            out.append(sorted(remaining))  # 环或缺失依赖，单独列出供人工处理
            break
        out.append(sorted(ready))
        for tid in ready:
            done.add(tid)
            remaining.pop(tid)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--complexity", required=True, type=Path)
    ap.add_argument("--roles", required=True, type=Path)
    ap.add_argument("--template", required=True, type=Path)
    ap.add_argument("--policy-profiles", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    a = ap.parse_args(argv)

    complexity = load(a.complexity)
    roles_doc = load(a.roles)
    template = load(a.template)
    profiles = load(a.policy_profiles)
    roles = {r["id"]: r for r in roles_doc["roles"]}
    modes = profiles["modes"]
    workers = complexity["recommended_workers"]

    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "results").mkdir(exist_ok=True)

    packs: List[Dict[str, Any]] = []
    parallel_index = 0
    for task in template["tasks"]:
        role = roles.get(task["role"])
        if role is None:
            raise SystemExit("未知角色: %s" % task["role"])
        mode = task["policy_mode"]
        mode_spec = modes[mode]
        allowed = [x for x in role["allowed_actions"] if x in mode_spec["allowed_actions"]]
        compliance = template.get("compliance", {})
        forbidden = list(dict.fromkeys(
            mode_spec["forbidden_actions"]
            + profiles.get("global_forbidden_actions", [])
            + compliance.get("forbidden_actions", [])))
        if role.get("can_parallel"):
            assigned = "worker-%d" % (parallel_index % max(workers, 1) + 1)
            parallel_index += 1
        else:
            assigned = "main-agent"

        payload = {"task": task["id"], "role": task["role"], "mode": mode,
                   "band": complexity["band"], "template": template["template_id"]}
        input_hash = "sha256:" + hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]

        pack = {
            "task_id": task["id"],
            "role": task["role"],
            "goal": task["goal"],
            "milestone": template["milestone"],
            "policy_mode": mode,
            "transformation": compliance.get("transformation", "none"),
            "distribution": compliance.get("distribution", "local-only"),
            "distribution_conditions": compliance.get("distribution_conditions", []),
            "allowed_actions": allowed,
            "forbidden_actions": forbidden,
            "inputs": task["inputs"],
            "output_contract": task["output_contract"],
            "output_path": "work/dispatch/results/%s.json" % task["id"],
            "acceptance": task["acceptance"],
            "depends_on": task.get("depends_on", []),
            "can_parallel": role.get("can_parallel", False),
            "complexity": {
                "band": complexity["band"],
                "score": complexity["score"],
                "reason": "score=%.4f, band=%s, workers=%d, hard_gates=%d"
                          % (complexity["score"], complexity["band"], workers,
                             len(complexity["hard_gates"])),
            },
            "input_hash": input_hash,
            "invariants": roles_doc["invariants"],
            "assigned_worker": assigned,
        }
        (a.out_dir / (task["id"] + ".json")).write_text(
            json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        packs.append({"task_id": task["id"], "role": task["role"],
                      "assigned_worker": assigned, "policy_mode": mode,
                      "output_path": pack["output_path"], "input_hash": input_hash,
                      "can_parallel": pack["can_parallel"]})

    index = {
        "schema_version": "0.1.0",
        "milestone": template["milestone"],
        "template_id": template["template_id"],
        "complexity": {k: complexity[k] for k in
                       ("score", "band", "recommended_workers", "human_gate", "hard_gates")},
        "waves": waves(template["tasks"]),
        "packs": packs,
        "invariants": roles_doc["invariants"],
        "created_by": "plan-dispatch@0.1.0",
    }
    (a.out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK packs=%d waves=%d band=%s workers=%d human_gate=%s out=%s"
          % (len(packs), len(index["waves"]), complexity["band"], workers,
             complexity["human_gate"], a.out_dir))
    for i, wave in enumerate(index["waves"], 1):
        print("   wave %d: %s" % (i, ", ".join(wave)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
