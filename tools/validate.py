#!/usr/bin/env python3
"""集群一致性自检器。仅依赖 Python 标准库。

检查: JSON 可解析 / schema 与规则一致 / profile 符号完整 / 能力词汇表与绑定表 /
registry DAG 与读写冲突 / SKILL.md frontmatter / 分诊器 golden 与幂等 / 文档齐全。

用法: python tools/validate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify  # noqa: E402

PASSED: List[str] = []
FAILED: List[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
    else:
        FAILED.append("%s%s" % (name, (" -- " + detail) if detail else ""))


def load(rel: str) -> Any:
    with (ROOT / rel).open("r", encoding="utf-8") as f:
        return json.load(f)


def norm(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def parse_frontmatter(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: Dict[str, Any] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("["):
            try:
                out[key.strip()] = json.loads(value)
            except json.JSONDecodeError:
                out[key.strip()] = value
        else:
            out[key.strip()] = value.strip('"').strip("'")
    return out


def depends_reachable(skills: Dict[str, Dict[str, Any]], start: str, target: str) -> bool:
    seen = set()
    stack = list(skills[start].get("depends_on", []))
    while stack:
        cur = stack.pop()
        if cur == target:
            return True
        if cur in seen or cur not in skills:
            continue
        seen.add(cur)
        stack.extend(skills[cur].get("depends_on", []))
    return False


def main() -> int:
    # 1. 所有 JSON 可解析
    excluded = {".git", "work", "out", "tmp", "__pycache__"}
    json_files = sorted(
        p for p in ROOT.rglob("*.json")
        if not (set(p.relative_to(ROOT).parts[:-1]) & excluded)
    )
    bad_json: List[str] = []
    for path in json_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            bad_json.append("%s: %s" % (path.relative_to(ROOT), exc))
    check("JSON 全部可解析 (%d 个文件)" % len(json_files), not bad_json, "; ".join(bad_json))

    # 2. 核心文件存在且 schema_version 一致
    required_files = [
        "README.md", "docs/00-methodology.md", "docs/01-java-decompiled-classification.md",
        "docs/02-skill-cluster-protocol.md", "docs/adr/0001-target-agnostic-contract.md",
        "docs/adr/0002-forge-version-agnostic.md", "docs/adr/0003-skill-cluster-protocol.md",
        "schemas/manifest.schema.json", "schemas/delta.schema.json",
        "schemas/artifact-index.schema.json", "schemas/capability.schema.json",
        "capabilities/vocabulary.json", "profiles/forge/_template.json",
        "target/horizon.capabilities.json", "rules/classification.rules.json",
        "skills/registry.json", "tests/fixtures/artifact-index.sample.json",
        "tests/golden/classification.delta.json",
        "docs/03-empirical-calibration.md", "docs/adr/0004-empirical-rule-calibration.md",
        "docs/adr/0005-horizon-target-binding-and-policy-boundary.md",
        "docs/04-roadmap.md", "docs/adr/0006-policy-tiered-inspection.md",
        "policy/license-profiles.json", "mappings/forge-to-horizon.json",
        "mappings/disposition-to-tier.json", "tools/build_hook_mapping.py",
        "docs/05-m2-plan.md", "docs/adr/0007-subagent-dispatch.md",
        "docs/adr/0008-policy-three-dimensions.md",
        "orchestration/roles.json", "orchestration/complexity-model.json",
        "orchestration/task-templates/m2.json", "orchestration/dispatch-pack.schema.json",
        "tools/estimate_complexity.py", "tools/plan_dispatch.py", "tools/collect_results.py",
        "reports/m2-complexity.json", "reports/m2-collection.json",
        "profiles/forge/1.20.1.json", "reports/calibration-before.json",
        "reports/calibration-1.20.1.json", "tools/lib_facts.py", "tools/experiment.py",
    ]
    missing = [rel for rel in required_files if not (ROOT / rel).is_file()]
    check("核心文件齐全 (%d 项)" % len(required_files), not missing, ", ".join(missing))
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("版权边界：work/ 与二进制产物被排除入库",
          all(token in gitignore for token in ("work/", "*.jar", "*.png", "*.class")))

    for rel in ["schemas/manifest.schema.json", "schemas/delta.schema.json",
                "schemas/artifact-index.schema.json", "schemas/capability.schema.json"]:
        schema = load(rel)
        check("%s 是合法 draft 2020-12 schema" % rel,
              schema.get("$schema", "").startswith("https://json-schema.org/draft/2020-12/")
              and isinstance(schema.get("properties"), dict)
              and isinstance(schema.get("required"), list))

    # 3. 规则符号在 profile 中完整展开
    rules = load("rules/classification.rules.json")
    profile = load("profiles/forge/_template.json")
    try:
        classify.verify_profile_symbols(profile, rules)
        check("规则引用的符号全部在 forge profile 中定义", True)
    except classify.ClassificationError as exc:
        check("规则引用的符号全部在 forge profile 中定义", False, str(exc))

    # 4. 规则的 evidence_kind 必须在 manifest schema 枚举内
    manifest_schema = load("schemas/manifest.schema.json")
    allowed_kinds = set(manifest_schema["$defs"]["evidence"]["properties"]["kind"]["enum"])
    used_kinds = {r["then"]["evidence_kind"] for r in rules["rules"]}
    check("evidence_kind 全部在 manifest schema 枚举内", used_kinds <= allowed_kinds,
          "越界: %s" % sorted(used_kinds - allowed_kinds))

    # 5. 规则 priority 唯一、兜底规则存在且最后
    priorities = [r["priority"] for r in rules["rules"]]
    fallbacks = [r for r in rules["rules"] if r["then"]["evidence_kind"] == "fallback"]
    check("规则 priority 唯一", len(priorities) == len(set(priorities)))
    check("存在且仅有一条兜底规则，并位于末尾",
          len(fallbacks) == 1 and max(priorities) == fallbacks[0]["priority"])

    # 6. 能力词汇表自洽
    vocab = load("capabilities/vocabulary.json")
    cap_ids = [c["id"] for c in vocab["capabilities"]]
    group_ids = {g["id"] for g in vocab["groups"]}
    check("capability id 唯一", len(cap_ids) == len(set(cap_ids)))
    check("capability 的 group 都已声明",
          all(c["group"] in group_ids for c in vocab["capabilities"]))
    check("capability 均有 contract 且不含平台实现字段",
          all("contract" in c and "inputs" in c["contract"] and "outputs" in c["contract"]
              and "mechanism" not in c and "status" not in c
              for c in vocab["capabilities"]))

    # 7. target 绑定表覆盖全部能力
    target = load("target/horizon.capabilities.json")
    bindings = target["bindings"]
    check("Horizon 绑定表覆盖全部 capability", set(bindings) == set(cap_ids),
          "缺: %s / 多: %s" % (sorted(set(cap_ids) - set(bindings)), sorted(set(bindings) - set(cap_ids))))
    check("绑定状态取值合法",
          all(b["status"] in ("unbound", "declared", "implemented") for b in bindings.values()))
    check("已绑定能力均可追溯到 Horizon 快照证据",
          all(b.get("evidence") for b in bindings.values() if b["status"] != "unbound"))
    check("能力缺口被显式记录且数量可控",
          sum(1 for b in bindings.values() if b["status"] == "unbound") <= 3)

    # 8. registry DAG
    registry = load("skills/registry.json")
    skills = {s["id"]: s for s in registry["skills"]}
    check("skill id 唯一", len(skills) == len(registry["skills"]))
    stage_ids = {s["id"] for s in registry["stages"]}
    check("skill 的 stage 都已声明", all(s["stage"] in stage_ids for s in skills.values()))
    check("depends_on 均指向存在的 skill",
          all(d in skills for s in skills.values() for d in s["depends_on"]))

    visiting: set = set()
    done: set = set()
    cycle: List[str] = []

    def visit(node: str) -> bool:
        if node in visiting:
            cycle.append(node)
            return False
        if node in done:
            return True
        visiting.add(node)
        for dep in skills.get(node, {}).get("depends_on", []):
            if not visit(dep):
                return False
        visiting.discard(node)
        done.add(node)
        return True

    acyclic = all(visit(sid) for sid in skills)
    check("registry 依赖图无环", acyclic, "环: %s" % cycle)

    # 9. 写冲突检测：同一非追加字段被无拓扑序的两个 skill 写入
    conflicts: List[str] = []
    writers: Dict[str, List[str]] = {}
    for sid, skill in skills.items():
        for field in skill["writes"]:
            if field.endswith("[]"):
                continue
            writers.setdefault(field, []).append(sid)
    for field, owners in writers.items():
        for i, a in enumerate(owners):
            for b in owners[i + 1:]:
                if not (depends_reachable(skills, a, b) or depends_reachable(skills, b, a)):
                    conflicts.append("%s <- %s / %s" % (field, a, b))
    check("无无拓扑序的写字段冲突", not conflicts, "; ".join(conflicts))

    implemented = [s for s in skills.values() if s["status"] == "implemented"]
    missing_runners = [s["id"] for s in implemented
                       if not (ROOT / s.get("runner", s["path"] + "/run.py")).is_file()]
    check("implemented skill 均有确定性执行层 (%d 个)" % len(implemented),
          not missing_runners, ", ".join(missing_runners))

    # 10. SKILL.md 存在且 frontmatter 与 registry 一致
    fm_errors: List[str] = []
    for sid, skill in skills.items():
        path = ROOT / skill["path"] / "SKILL.md"
        if not path.is_file():
            fm_errors.append("%s 缺 SKILL.md" % sid)
            continue
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        for key in ("id", "version", "stage", "execution", "status"):
            if fm.get(key) != skill.get(key):
                fm_errors.append("%s.%s: %r != %r" % (sid, key, fm.get(key), skill.get(key)))
        for key in ("reads", "writes", "depends_on", "acceptance"):
            if fm.get(key) != skill.get(key):
                fm_errors.append("%s.%s frontmatter 与 registry 不一致" % (sid, key))
        if not skill.get("acceptance"):
            fm_errors.append("%s 缺可执行验收断言" % sid)
    check("SKILL.md frontmatter 与 registry 完全一致", not fm_errors, "; ".join(fm_errors))

    # 11. 分诊器：golden 一致 + 幂等
    index = load("tests/fixtures/artifact-index.sample.json")
    golden = load("tests/golden/classification.delta.json")
    delta = classify.classify(index, profile, rules)
    check("分诊器输出与 golden 逐字段一致", norm(delta) == norm(golden))
    check("分诊器幂等（重跑逐字段一致）", norm(classify.classify(index, profile, rules)) == norm(delta))

    # 12. classify 验收断言
    patches = delta["unit_patches"]
    check("每个 unit 都有 disposition", all("disposition" in p["set"] for p in patches))
    check("每条标签至少 1 条 evidence", all(len(p["set"]["evidence"]) >= 1 for p in patches))
    check("confidence 均在 [0,1]", all(0 <= p["set"]["confidence"] <= 1 for p in patches))
    c6 = [p for p in patches if p["set"]["disposition"] == "C6"]
    check("C6 单元全部显式进入人工关卡",
          all(any(w == "review_required:" + p["unit_id"] for w in delta["warnings"]) for p in c6))
    check("存在混合层下钻用例",
          any(p["set"]["requires_drilldown"] for p in patches))

    # 13. delta 结构符合 schema 的 required
    check("delta 结构字段齐全",
          all(k in delta for k in ("delta_id", "skill_id", "skill_version", "input_hash", "unit_patches")))

    # 14. 方案 C：许可证分档与降级提取
    import importlib.util
    sys.path.insert(0, str(ROOT / "tools"))
    import lib_facts as L  # noqa: E402

    profiles = load("policy/license-profiles.json")
    check("policy 规则三档齐全且 default_deny 最严格",
          set(profiles["modes"]) == {"full-inspection", "metadata-only", "oracle-only"}
          and profiles["severity"][profiles["default_mode"]]
          == max(profiles["severity"].values()))
    check("policy 规则的 mode/scope 取值合法",
          all(p["mode"] in profiles["modes"] and p["scope"] in profiles["scopes"]
              for p in profiles["license_patterns"]))

    spec = importlib.util.spec_from_file_location(
        "policy_gate", ROOT / "skills/00-intake/policy-gate/run.py")
    pg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pg)
    tacz = pg.decide("GPL3 / CC BY-NC-ND 4.0", profiles, "tacz")
    check("ADR 0008：非标准 license 串按 scope 三维分档",
          tacz["scope_decisions"]["code"]["mode"] == "full-inspection"
          and tacz["scope_decisions"]["assets"]["mode"] == "full-inspection"
          and tacz["scope_decisions"]["assets"]["transformation"] == "technical-only"
          and tacz["scope_decisions"]["assets"]["distribution"] == "local-only"
          and tacz["distribution"] == "local-only"
          and tacz["redistribution"] is False)
    unknown = pg.decide("SomeWeirdLicense 9.9", profiles, "unknown")
    check("default_deny：未知许可证强制 oracle-only + review_required",
          unknown["policy_mode"] == "oracle-only" and unknown["review_required"] is True)

    sample = ('package com.tacz.demo;\nimport net.minecraft.world.item.Item;\n'
              'public class Gun {\n  public void shoot() { String s = "tacz:ak47"; }\n}\n')
    full = L.parse_java_source(sample, "com/tacz/demo/Gun.java", "full-inspection")
    meta = L.parse_java_source(sample, "com/tacz/demo/Gun.java", "metadata-only")
    oracle = L.parse_java_source(sample, "com/tacz/demo/Gun.java", "oracle-only")
    check("metadata-only 降级：方法名与字符串字面量被清除，签名保留",
          meta["symbols"]["methods"] == [] and meta["symbols"]["constant_strings"] == []
          and meta["symbols"]["annotations"] == full["symbols"]["annotations"]
          and meta["symbols"]["declared_kind"] == full["symbols"]["declared_kind"])
    check("oracle-only 降级：不读取任何内容",
          all(not v for v in oracle["symbols"].values() if isinstance(v, list)))
    check("full-inspection 保留完整事实",
          len(full["symbols"]["methods"]) >= 1 and bool(full["symbols"]["constant_strings"]))

    # 15. M1 映射表自洽
    mapping = load("mappings/forge-to-horizon.json")
    ms = mapping["stats"]
    check("NeoForge → hook 映射表条目自洽",
          ms["mapping_entries"] == len(mapping["entries"])
          and ms["hooks_with_event_mapping"] + ms["hooks_without_neoforge_counterpart"]
          == ms["hooks_with_neoforge_field"])
    routes = load("mappings/disposition-to-tier.json")
    check("C1–C6 → API tier 路由覆盖六种处置",
          set(routes["routes"]) == {"C1", "C2", "C3", "C4", "C5", "C6"})

    # 16. 子 agent 编排层（ADR 0007）
    roles_doc = load("orchestration/roles.json")
    template = load("orchestration/task-templates/m2.json")
    cmodel = load("orchestration/complexity-model.json")
    role_ids = {r["id"] for r in roles_doc["roles"]}
    check("角色 id 唯一且模板任务角色均已定义",
          len(role_ids) == len(roles_doc["roles"])
          and all(t["role"] in role_ids for t in template["tasks"]))
    check("复杂度模型权重归一且 band 连续",
          abs(sum(s["weight"] for s in cmodel["signals"].values()) - 1.0) < 1e-6
          and cmodel["bands"][0]["min"] == 0.0
          and all(cmodel["bands"][i]["max"] == cmodel["bands"][i + 1]["min"]
                  for i in range(len(cmodel["bands"]) - 1)))
    check("派发包 schema 定义完整",
          isinstance(load("orchestration/dispatch-pack.schema.json").get("required"), list))
    cr = load("reports/m2-complexity.json")
    check("复杂度报告 band 与 score / 硬门槛自洽",
          cr["band"] == next(b["id"] for b in cmodel["bands"]
                            if b["min"] <= cr["score"] < b["max"])
          and cr["human_gate"] is True and len(cr["hard_gates"]) >= 1)
    coll = load("reports/m2-collection.json")
    check("汇总报告 verdict 与计数自洽",
          coll["total"] == len(template["tasks"])
          and coll["completed"] + coll["missing"] + len(coll["violations"]) == coll["total"]
          and coll["verdict"] in ("COMPLETE", "PARTIAL", "BLOCKED"))

    dispatch_index = ROOT / "work/dispatch/index.json"
    if dispatch_index.is_file():
        di = json.loads(dispatch_index.read_text(encoding="utf-8"))
        packs = [json.loads((ROOT / "work/dispatch" / (e["task_id"] + ".json")).read_text(
            encoding="utf-8")) for e in di["packs"]]
        check("每个任务包携带 policy 约束与 input_hash",
              all(p.get("policy_mode") and p.get("forbidden_actions")
                  and p.get("input_hash") and p.get("allowed_actions") for p in packs))
        check("任务包三维度合规：技术性转换 + local-only + 禁止发布/商用",
              all(p.get("transformation") in ("technical-only", "port", "none")
                  and p.get("distribution") == "local-only"
                  and all(x in p["forbidden_actions"] for x in
                          ("creative_adaptation", "publish_adapted_material", "commercial_use"))
                  for p in packs))
    else:
        check("派发产物存在（work/dispatch/index.json）", False, "未生成")

    print("=" * 68)
    for name in PASSED:
        print("  PASS  %s" % name)
    for name in FAILED:
        print("  FAIL  %s" % name)
    print("=" * 68)
    print("TOTAL: %d passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
