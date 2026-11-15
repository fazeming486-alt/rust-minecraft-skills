#!/usr/bin/env python3
"""差分断言器：把我们的检查结果桥接成官方 harness/result.json 形状。

三类 check：
  logic_replay    — 录制契约 vs 观测序列逐 tick 比对
  shared_states   — 跨层切片状态枚举双向可查
  asset_integrity — 格式等价转换 roundtrip 闭合

输出同时给：
  - 官方形状 result.json（可被 report.rs:283-306 直接消费）
  - 脱敏差分报告（仓库内只放这个）

关键诚实点：offline fixture 只验证「断言器本身正确」，不代表真机 oracle 录制。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lib_conversion as C  # noqa: E402

CHECK_NAMES = ("logic_replay", "shared_states", "asset_integrity")


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


class Check:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.examples: List[str] = []

    def record(self, ok: bool, why: str) -> None:
        if ok:
            self.passed += 1
        else:
            self.failed += 1
            if len(self.examples) < 8:
                self.examples.append(why)

    def json(self) -> Dict[str, Any]:
        return {"passed": self.passed, "failed": self.failed, "examples": self.examples}


def check_logic_replay(contracts: List[Dict[str, Any]],
                       observations: Dict[str, Any]) -> Check:
    c = Check()
    obs = observations.get("contracts", {})
    for contract in contracts:
        cid = contract["contract_id"]
        o = obs.get(cid)
        if o is None:
            c.record(False, "%s: 无观测序列" % cid)
            continue
        expected = contract["state_sequence"]
        actual = o.get("state_sequence", [])
        c.record(len(expected) == len(actual),
                 "%s: 长度 %d vs %d" % (cid, len(expected), len(actual)))
        for i, (e, a) in enumerate(zip(expected, actual)):
            c.record(e.get("tick") == a.get("tick"),
                     "%s[%d]: tick %s vs %s" % (cid, i, e.get("tick"), a.get("tick")))
            c.record(e.get("shared_state") == a.get("shared_state"),
                     "%s[%d]: state %s vs %s" % (cid, i, e.get("shared_state"), a.get("shared_state")))
        ticks = [x.get("tick", -1) for x in actual]
        c.record(all(b > a for a, b in zip(ticks, ticks[1:])),
                 "%s: tick 序列非严格递增" % cid)
        actions = [x.get("capability_id") for x in o.get("input_sequence", [])]
        c.record(all(x in contract["capability_ids"] for x in actions),
                 "%s: 输入引用了未声明的 capability" % cid)
    return c


def check_shared_states(slices_doc: Dict[str, Any],
                        observations: Dict[str, Any]) -> Check:
    c = Check()
    universe = {s for sl in slices_doc["slices"] for s in sl["shared_states"]}
    c.record(bool(universe), "shared_states 全集为空")
    for sl in slices_doc["slices"]:
        states = sl["shared_states"]
        c.record(len(states) == len(set(states)),
                 "%s: shared_states 有重复" % sl["slice_id"])
        c.record(all(s in universe for s in states),
                 "%s: 状态越出全集" % sl["slice_id"])
        c.record(sl["state_parameters"]["roundtrip_closed"],
                 "%s: 参数化 roundtrip 未闭合" % sl["slice_id"])
    observed = observations.get("observed_states", [])
    for s in observed:
        c.record(s in universe, "观测状态 %r 不在 shared_states 全集" % s)
    return c


def check_asset_integrity(conv: Dict[str, Any]) -> Check:
    c = Check()
    c.record(conv["closed"], "转换报告 closed=false")
    for item in conv["converters"]:
        c.record(item["roundtrip_closed"], "%s: roundtrip 未闭合" % item["id"])
        c.record(item["schema_status"] in ("bound", "partial", "unbound"),
                 "%s: 未知 schema_status" % item["id"])
    c.record(any(x["schema_status"] == "unbound" for x in conv["converters"]),
            "未如实标注 unbound 中间表示")
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="差分断言 + 官方 result.json 桥接")
    ap.add_argument("--contracts", required=True, type=Path)
    ap.add_argument("--observations", required=True, type=Path,
                    help="观测序列 JSON；offline fixture 或真机 oracle 录制，结果里会记录来源")
    ap.add_argument("--slices", required=True, type=Path)
    ap.add_argument("--conversion", required=True, type=Path)
    ap.add_argument("--mod-key", default="rustmc-skills")
    ap.add_argument("--result-out", required=True, type=Path,
                    help="官方形状 harness/result.json（写 work/ 下）")
    ap.add_argument("--report", required=True, type=Path)
    a = ap.parse_args(argv)

    contracts_doc = load(a.contracts)
    observations = load(a.observations)
    slices_doc = load(a.slices)
    conv = load(a.conversion)

    checks = {
        "logic_replay": check_logic_replay(contracts_doc["contracts"], observations),
        "shared_states": check_shared_states(slices_doc, observations),
        "asset_integrity": check_asset_integrity(conv),
    }
    failed = sum(v.failed for v in checks.values())
    total = sum(v.passed + v.failed for v in checks.values())
    result = {
        "mod": a.mod_key,
        "passed": failed == 0 and total > 0,
        "checks": {k: v.json() for k, v in checks.items()},
    }
    C.write_json(a.result_out, result)

    report = {
        "schema_version": "0.1.0",
        "generated_by": "diff-assertions@0.1.0",
        "mod_key": a.mod_key,
        "observation_source": observations.get("source", "unspecified"),
        "observation_is_fixture": bool(observations.get("fixture", False)),
        "official_harness_covers_logic_replay": False,
        "checks": {k: {"passed": v.passed, "failed": v.failed, "examples": v.examples}
                   for k, v in checks.items()},
        "verdict": "PASS" if result["passed"] else "FAIL",
        "result_json": a.result_out.as_posix(),
        "bridge": "mappings/harness-contract.json#bridge_mapping",
        "limitations": [
            "offline fixture 只验证断言器本身正确，不代表真机 Java oracle 录制",
            "官方 harness 不覆盖 C1 逻辑行为录制；logic_replay 是本仓库自建层",
            "result.json 必须在 carry() 之后生成，否则会被 carry 删除（carry.rs:1000）",
            "report.rs 动态遍历 checks，自定义 check 名可被消费（report.rs:292-303）",
        ],
    }
    C.write_json(a.report, report)
    print("OK verdict=%s checks=%s failed=%d total=%d fixture=%s"
          % (report["verdict"], ",".join(CHECK_NAMES), failed, total,
             report["observation_is_fixture"]))
    for k, v in checks.items():
        print("   %-18s passed=%-3d failed=%-3d %s"
              % (k, v.passed, v.failed, v.examples[:2]))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
