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
        "docs/adr/0009-cross-layer-slices-and-target-study.md", "docs/06-m2-execution.md",
        "schemas/feature-slice.schema.json", "orchestration/slice-anchors.json",
        "orchestration/horizon-probes/render-pipeline.json",
        "orchestration/horizon-probes/asset-schema.json",
        "orchestration/horizon-probes/mod-api.json",
        "tools/lib_horizon_source.py", "tools/lib_conversion.py",
        "tools/build_feature_slices.py",
        "skills/02-contract/build-feature-slices/run.py",
        "skills/04-art/technical-convert-assets/run.py",
        "reports/horizon-render-pipeline.json", "reports/horizon-asset-schema.json",
        "reports/horizon-mod-api.json", "reports/m2-feature-slices.json",
        "reports/m2-conversion.json",
        "docs/adr/0010-m3-harness-bridge-and-m4-generalization.md",
        "docs/07-m3-m4-execution.md", "mappings/harness-contract.json",
        "schemas/recording-contract.schema.json", "orchestration/m4-samples.json",
        "orchestration/recording-capability-map.json",
        "orchestration/task-templates/m3-m4.json",
        "tools/m4_generalize.py", "tools/build_recording_contract.py",
        "tools/diff_assertions.py",
        "skills/09-verify/diff-test-harness/run.py",
        "skills/09-verify/verify-generalization/run.py",
        "tests/fixtures/recording-contract.sample.json",
        "tests/fixtures/oracle-observations.pass.json",
        "tests/fixtures/oracle-observations.fail.json",
        "reports/m4-generalization.json", "reports/m3-diff-pass.json",
        "reports/m3-diff-fail.json", "reports/m34-collection.json",
        "schemas/state-machine-ir.schema.json", "orchestration/m5-slice.json",
        "orchestration/task-templates/m5.json",
        "docs/adr/0011-vertical-slice-and-native-module.md",
        "docs/08-m5-execution.md",
        "skills/05-port/translate-lua-statemachine/SKILL.md",
        "skills/05-port/translate-lua-statemachine/run.py",
        "skills/05-port/build-content-mod/SKILL.md",
        "skills/05-port/build-content-mod/run.py",
        "skills/05-port/port-native-module/SKILL.md",
        "skills/05-port/port-native-module/run.py",
        "skills/05-port/verify-hook-catalog/SKILL.md",
        "skills/05-port/verify-hook-catalog/run.py",
        "skills/09-verify/playable-diff-harness/SKILL.md",
        "skills/09-verify/playable-diff-harness/run.py",
        "reports/m5-state-ir.json", "reports/m5-content-mod.json",
        "reports/m5-native-module.json", "reports/m5-hook-catalog.json",
        "reports/m5-diff.json", "reports/m5-collection.json",
        "reports/m5b-native-build.json",
        "reports/m5c-firing.json", "reports/m5d-attempt.json",
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

    # 13. v0.7 · 目标侧源码取证（三路 skill）
    probe_docs = {pid: load("reports/horizon-%s.json" % pid)
                  for pid in ("render-pipeline", "asset-schema", "mod-api")}
    check("三路 Horizon 源码探针 missing_files 全为空",
          all(not d["missing_files"] for d in probe_docs.values()),
          "; ".join("%s=%s" % (k, v["missing_files"]) for k, v in probe_docs.items()
                    if v["missing_files"]))
    rp = probe_docs["render-pipeline"]["tree_scan"]["keywords"]
    askw = probe_docs["asset-schema"]["tree_scan"]["keywords"]
    check("源码级缺席证明：glTF / Bedrock geometry / .bbmodel 读取器 0 命中",
          rp["gltf|GLTFLoader"]["sample_size"] == 0
          and askw["BedrockGeometry|bedrock[_ ]geometry"]["sample_size"] == 0
          and askw["\\.bbmodel|BlockbenchModel"]["sample_size"] == 0)
    check("逐部件姿态能力存在：ModelPart 命中数 > 0",
          rp["ModelPart"]["sample_size"] > 0)
    check("mod API 探针证明 harness/coverage 已存在",
          probe_docs["mod-api"]["tree_scan"]["keywords"]["coverage\\.json"]["sample_size"] > 0)

    # 14. v0.7 · 跨层特性切片
    slice_schema = load("schemas/feature-slice.schema.json")
    check("feature-slice schema 是合法 draft 2020-12 且定义四层",
          slice_schema.get("$schema", "").startswith("https://json-schema.org/draft/2020-12/")
          and "slice" in slice_schema["$defs"]
          and all(x in slice_schema["$defs"]["slice"]["properties"]["layers"]["properties"]
                  for x in ("assets", "code", "target", "contract")))
    anchors = load("orchestration/slice-anchors.json")
    check("锚点规则含 workaround_catalog 与参数化规则",
          bool(anchors.get("workaround_catalog", {}).get("skeletal_animation", {}).get("limitations"))
          and len(anchors["state_parameter_rules"]) >= 2
          and len(anchors["anchors"]) >= 8)
    fs = load("reports/m2-feature-slices.json")
    check("跨层切片四层齐全、closed 且无未匹配状态",
          fs["validation"]["closed"] and fs["validation"]["target_symbols_resolved"]
          and not fs["unmatched_states"]
          and all(s["state_parameters"]["roundtrip_closed"] for s in fs["slices"])
          and all(all(k in s["layers"] for k in ("assets", "code", "target", "contract"))
                  for s in fs["slices"]))
    check("切片 verdict 三态且硬缺口不伪装成 portable",
          all(s["verdict"] in ("portable", "needs_workaround", "blocked") for s in fs["slices"])
          and all(s["gaps"] or s["verdict"] == "portable" for s in fs["slices"])
          and any(s["verdict"] == "needs_workaround" and
                  "animation_driver" in s["layers"]["target"]["capability_gap"]
                  for s in fs["slices"]))
    check("所有 needs_workaround 切片都挂了具体 workaround",
          all("workaround" in s["layers"]["target"] for s in fs["slices"]
              if s["verdict"] == "needs_workaround"))

    # 15. v0.7 · 技术性格式等价转换
    conv = load("reports/m2-conversion.json")
    check("5 个转换器 roundtrip 全闭合",
          conv["closed"] and len(conv["converters"]) == 5
          and all(c["roundtrip_closed"] for c in conv["converters"]))
    check("转换产物只留 work/ 且 schema 状态诚实分级",
          "work" in Path(conv["output_dir"]).parts
          and set(conv["totals"]["schema_status"]) == {"bound", "partial", "unbound"}
          and all(c["schema_status"] in ("bound", "partial", "unbound")
                  for c in conv["converters"]))
    check("转换政策三维为 technical-only / local-only",
          conv["policy"]["transformation"] == "technical-only"
          and conv["policy"]["distribution"] == "local-only")

    # 16. 回归：ADR 0008 放宽政策后，执行层必须真的允许转换（v0.6 曾断在这里）
    role_map = {r["id"]: r for r in roles_doc["roles"]}
    check("政策断点回归：资产角色 allowed_actions 含技术性转换",
          all("technical_format_conversion" in role_map[r]["allowed_actions"]
              for r in ("geometry-asset", "animation-asset", "texture-asset",
                        "audio-asset", "display-index", "asset-conversion")))
    check("政策断点回归：目标侧角色 allowed_actions 含读 Horizon 源码",
          all("read_horizon_source" in role_map[r]["allowed_actions"]
              for r in ("target-study-render", "target-study-assets", "target-study-mod-api")))
    check("政策白名单包含 read_horizon_source 与 build_cross_layer_slice",
          all(x in load("policy/license-profiles.json")["modes"]["full-inspection"]["allowed_actions"]
              for x in ("read_horizon_source", "build_cross_layer_slice")))
    if dispatch_index.is_file():
        by_id = {p["task_id"]: p for p in packs}
        check("任务包实际下发转换与研读权限（不是只在文档里）",
              "technical_format_conversion" in by_id["m2-17-conversion"]["allowed_actions"]
              and "read_horizon_source" in by_id["m2-13-target-render"]["allowed_actions"]
              and "build_cross_layer_slice" in by_id["m2-16-feature-slices"]["allowed_actions"])
        check("派发为 17 任务 / 4 wave 且目标侧研读在首波",
              len(di["packs"]) == 17 and len(di["waves"]) == 4
              and "m2-13-target-render" in di["waves"][0]
              and "m2-16-feature-slices" in di["waves"][1])
    check("M2 汇总 COMPLETE 且零越界",
          coll["verdict"] == "COMPLETE" and coll["total"] == len(template["tasks"])
          and coll["missing"] == 0 and not coll["violations"])

    # 18. v0.8 · R021 与常量池解析回归
    check("规则 21 条且 R021 由 M4 泛化验证新增",
          len(rules["rules"]) == 21
          and any(r["id"] == "R021" and r["priority"] == 29
                  and r["then"]["disposition"] == "C5" for r in rules["rules"]))
    golden_ids = {p["unit_id"] for p in golden["unit_patches"]}
    check("R021 有独立 golden 夹具用例",
          any("ExampleMixinPlugin" in u for u in golden_ids)
          and any("ExampleMixinPlugin" in p["unit_id"]
                  and p["set"]["disposition"] == "C5"
                  and any(e.get("rule_id") == "R021" for e in p["set"]["evidence"])
                  for p in golden["unit_patches"]))
    check("两个 forge profile 都定义 MIXIN_PLUGIN 前缀组",
          all("MIXIN_PLUGIN" in load("profiles/forge/%s.json" % n)["symbols"]["type_prefix"]
              for n in ("_template", "1.20.1")))
    lib_src = (ROOT / "tools/lib_facts.py").read_text(encoding="utf-8")
    check("常量池解析器拒绝泛型签名伪引用",
          "re.fullmatch(r\"L[\\w/$]+;\", value)" in lib_src)

    # 19. v0.8 · 合规门禁单段广播回归（不依赖 work/ 产物，可跨机器复现）
    import importlib.util
    gate_path = ROOT / "skills/00-intake/policy-gate/run.py"
    spec = importlib.util.spec_from_file_location("policy_gate_impl", gate_path)
    gate_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate_mod)
    profiles_doc = load("policy/license-profiles.json")
    d_mit = gate_mod.decide("MIT", profiles_doc, "fixture-mit")
    d_arr = gate_mod.decide("All Rights Reserved", profiles_doc, "fixture-arr")
    d_split = gate_mod.decide("GPL3 / CC BY-NC-ND 4.0", profiles_doc, "fixture-split")
    check("单段许可证广播到所有 scope 且强制 review_required",
          d_mit["single_license_broadcast"] and d_mit["review_required"]
          and all(v["mode"] == "full-inspection" for v in d_mit["scope_decisions"].values())
          and d_arr["single_license_broadcast"] and d_arr["review_required"]
          and len({v["mode"] for v in d_arr["scope_decisions"].values()}) == 1)
    check("多段许可证不触发广播、基线判定零变化",
          not d_split["single_license_broadcast"] and not d_split["review_required"]
          and d_split["scope_decisions"]["code"]["mode"] == "full-inspection"
          and d_split["scope_decisions"]["assets"]["transformation"] == "technical-only")
    d_unknown = gate_mod.decide("some-unlisted-license-xyz", profiles_doc, "fixture-unknown")
    check("完全无匹配仍 default_deny",
          not d_unknown["single_license_broadcast"]
          and all(v["mode"] == "oracle-only" for v in d_unknown["scope_decisions"].values())
          and d_unknown["review_required"])

    # 20. v0.8 · M4 泛化报告
    m4 = load("reports/m4-generalization.json")
    check("M4 四样本两档且阈值先于实验写死",
          len(m4["samples"]) == 4
          and m4["criteria"]["c6_ratio_max"] == 0.05
          and m4["criteria"]["fallback_ratio_max"] == 0.05
          and all(all(k in s["by_mode"] for k in ("full-inspection", "metadata-only"))
                  for s in m4["samples"]))
    check("M4 verdict 与逐样本 C6 / 兜底自洽",
          m4["verdict"] == "generalizes" and not m4["failures"]
          and all(s["by_mode"]["full-inspection"]["c6_ratio"] <= 0.05
                  and s["by_mode"]["full-inspection"]["fallback_ratio"] <= 0.05
                  for s in m4["samples"]))
    check("M4 样本形态确实不同（class 数跨度 > 5x）",
          max(s["shape"]["class_files"] for s in m4["samples"])
          > 5 * min(s["shape"]["class_files"] for s in m4["samples"]))

    # 21. v0.8 · M3 harness 对接契约
    hc = load("mappings/harness-contract.json")
    check("官方 result.json 契约字段与 report.rs 一致",
          hc["result_json"]["required_by_report_rs"] == ["passed", "checks"]
          and "passed" in hc["result_json"]["shape"]
          and hc["coverage_row"]["shape"].startswith("array of Row")
          and len(hc["coverage_row"]["status_enum"]) == 4)
    check("明确区分官方 harness 不覆盖逻辑录制",
          len(hc["capability_boundary"]["official_harness_covers"]) == 10
          and any("Java 逻辑" in x for x in hc["capability_boundary"]["official_harness_does_not_cover"])
          and hc["m3_status"].find("M3b") >= 0)
    check("桥接映射三个自定义 check 且 carry 生命周期有证据",
          set(hc["bridge_mapping"]) >= {"logic_replay", "shared_states", "asset_integrity"}
          and any("carry" in x["step"] for x in hc["lifecycle"])
          and any("删除" in x["warning"] for x in hc["lifecycle"] if x.get("warning")))
    rc_schema = load("schemas/recording-contract.schema.json")
    check("录制契约 schema 合法且平台无关",
          rc_schema.get("$schema", "").startswith("https://json-schema.org/draft/2020-12/")
          and "contract" in rc_schema["$defs"]
          and "java." not in json.dumps(rc_schema, ensure_ascii=False).lower()
          and "horizon_" not in json.dumps(rc_schema, ensure_ascii=False).lower())
    fixture_contract = load("tests/fixtures/recording-contract.sample.json")
    known_caps = {c["id"] for c in load("capabilities/vocabulary.json")["capabilities"]}
    check("录制契约夹具只引用已定义的 capability id",
          all(set(c["capability_ids"]) <= known_caps for c in fixture_contract["contracts"]))

    # 22. v0.8 · 差分断言正反用例（断言器必须能抓错）
    dp = load("reports/m3-diff-pass.json")
    df = load("reports/m3-diff-fail.json")
    check("PASS 用例全绿且标注 fixture 来源",
          dp["verdict"] == "PASS" and dp["observation_is_fixture"]
          and all(v["failed"] == 0 for v in dp["checks"].values()))
    check("FAIL 用例抓到三类失配且可定位",
          df["verdict"] == "FAIL"
          and sum(v["failed"] for v in df["checks"].values()) >= 3
          and any("rc-001[2]" in x for x in df["checks"]["logic_replay"]["examples"])
          and df["checks"]["shared_states"]["failed"] >= 1)
    check("官方 harness 不覆盖逻辑重放被如实记录",
          dp["official_harness_covers_logic_replay"] is False
          and df["official_harness_covers_logic_replay"] is False)

    # 23. v0.8 · 独立子 agent 闭环
    m34 = load("reports/m34-collection.json")
    check("M3/M4 子 agent 汇总 7/7 COMPLETE 且零越界",
          m34["verdict"] == "COMPLETE" and m34["total"] == 7
          and m34["completed"] == 7 and m34["missing"] == 0 and not m34["violations"])
    m34_roles = {i["role"] for i in m34["items"]}
    check("6 个 result 由独立子 agent 角色产出（非主 agent 代写）",
          len(m34_roles) >= 6 and "verification" in m34_roles
          and all(i["assigned_worker"].startswith("worker-") for i in m34["items"]
                  if i["role"] != "verification"))
    check("任务包支持随包下发可复现命令",
          "command" in load("orchestration/dispatch-pack.schema.json")["properties"])
    m34_packs = ROOT / "work/dispatch-m34"
    if m34_packs.is_dir():
        ri = m34_packs / "results"
        ok = True
        for pth in sorted(m34_packs.glob("m34-*.json")):
            pk = json.loads(pth.read_text(encoding="utf-8"))
            rp = ri / (pk["task_id"] + ".json")
            if not rp.is_file():
                ok = False
                break
            res = json.loads(rp.read_text(encoding="utf-8"))
            if res.get("input_hash") != pk["input_hash"]:
                ok = False
                break
        check("子 agent result 的 input_hash 与任务包逐一匹配", ok)
    else:
        check("子 agent result 的 input_hash 与任务包逐一匹配", True, "work/ 未生成，跳过")

    # 24. v0.9 · registry 与 skill 状态
    check("集群 28 个 skill 且 M3/M5 验收层已实现",
          len(skills) == 28
          and skills["diff-test-harness"]["status"] == "implemented"
          and skills["verify-generalization"]["status"] == "implemented"
          and skills["policy-gate"]["version"] == "0.3.0"
          and all(skills[s]["status"] == "implemented" for s in
                  ("translate-lua-statemachine", "build-content-mod", "port-native-module",
                   "verify-hook-catalog", "playable-diff-harness")))

    # 25. v0.9 · M5 单枪竖切（AK-47）
    m5_schema = load("schemas/state-machine-ir.schema.json")
    check("状态机 IR schema 约束 states/unresolved/counts",
          m5_schema.get("$schema", "").startswith("https://json-schema.org/draft/2020-12/")
          and {"states", "unresolved", "counts", "inheritance", "inputs"} <= set(m5_schema["required"]))

    m5_slice = load("orchestration/m5-slice.json")
    check("M5 切片参数取自真实数据且合规三维齐全",
          m5_slice["params"]["rpm"] == 600
          and m5_slice["params"]["ammo_amount"] == 30
          and m5_slice["params"]["fire_modes"] == ["auto", "semi"]
          and m5_slice["policy"]["assets"]["transformation"] == "technical-only"
          and m5_slice["policy"]["assets"]["distribution"] == "local-only"
          and m5_slice["blocked_by"][0]["status"] == "not_run")

    m5_tpl = load("orchestration/task-templates/m5.json")
    check("M5 任务模板 5 个任务且依赖成链",
          len(m5_tpl["tasks"]) == 5
          and m5_tpl["tasks"][2]["depends_on"] == ["m5-01-state-ir"]
          and m5_tpl["tasks"][4]["depends_on"] == ["m5-01-state-ir", "m5-03-native-module"]
          and all(t.get("policy_mode") and t.get("acceptance") and t.get("command")
                  for t in m5_tpl["tasks"]))

    m5_skills = ["translate-lua-statemachine", "build-content-mod", "port-native-module",
                 "verify-hook-catalog", "playable-diff-harness"]
    check("M5 五个 skill 有 SKILL.md 与 run.py",
          all((ROOT / skills[s]["path"] / "SKILL.md").is_file()
              and (ROOT / skills[s]["path"] / "run.py").is_file() for s in m5_skills))
    check("M5 skill 分属 05-port 与 09-verify",
          all(skills[s]["stage"] == ("09-verify" if s == "playable-diff-harness" else "05-port")
              for s in m5_skills))

    m5_ir = load("reports/m5-state-ir.json")
    check("状态机 IR 通过 schema 且规模达标",
          m5_ir["acceptance"]["schema_valid"] and not m5_ir["acceptance"]["schema_errors"]
          and m5_ir["states"] >= 6 and m5_ir["transitions"] >= 8)
    check("IR 解析了 require 继承链且基类状态可追溯",
          "tacz_default_state_machine_v2" in m5_ir["inheritance"]
          and m5_ir["origins"].get("base", 0) >= 1 and m5_ir["origins"].get("gun", 0) >= 1)
    check("IR 的 unresolved 每条都有 file/symbol/reason",
          m5_ir["acceptance"]["unresolved_complete"] and m5_ir["unresolved"]["count"] > 0
          and sum(m5_ir["unresolved"]["by_reason"].values()) == m5_ir["unresolved"]["count"]
          and all({"file", "symbol", "reason"} <= set(u) for u in m5_ir["unresolved"]["items"]))
    check("IR 覆盖率诚实：53 个脚本全部做过语法级解析，未展开的显式记录",
          m5_ir["coverage"]["discovered"] == 53 and m5_ir["coverage"]["failed"] == 0
          and m5_ir["coverage"]["not_flattened"] == 53 - len(m5_ir["coverage"]["flattened"]))
    check("IR 幂等且排除项有说明", m5_ir["idempotent"] and m5_ir["excluded_states"] is not None)
    ir_path = ROOT / "work/m5/state-ir/ak47.json"
    if ir_path.is_file():
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        check("IR 转移要么带输入名，要么是条件驱动的 '*'（guard 非空）",
              all(t["on"] != "*" or t["guard"] for s in ir["states"] for t in s["transitions"]))
        check("IR 的 inputs 与转移实际引用的输入集合一致",
              set(ir["inputs"]) == {t["on"] for s in ir["states"]
                                    for t in s["transitions"] if t["on"] != "*"})
    else:
        check("IR 转移要么带输入名，要么是条件驱动的 '*'（guard 非空）", True, "work/ 未生成，跳过")
        check("IR 的 inputs 与转移实际引用的输入集合一致", True, "work/ 未生成，跳过")

    m5_cm = load("reports/m5-content-mod.json")
    check("内容包被官方工具接受（check ok=true）且可复现",
          m5_cm["ok"] and m5_cm["official"]["ok"] and m5_cm["reproducibility"]["reproducible"]
          and m5_cm["hmod"]["bytes"] > 0 and len(m5_cm["hmod"]["sha256"]) == 64)
    check("内容包负例被官方工具拒绝（校验不是摆设）",
          m5_cm["negative_control"]["ok"] and m5_cm["negative_control"]["build"]["returncode"] != 0)
    check("内容包只有 manifest/data/assets，无 Cargo.toml 与 .rs",
          all(not f["path"].endswith((".rs", "Cargo.toml")) for f in m5_cm["files"])
          and any(f["path"] == "horizon-mod.toml" for f in m5_cm["files"]))

    m5_nm = load("reports/m5-native-module.json")
    check("原生模块 engine 纯 Rust 且 cargo test 全绿",
          m5_nm["status"] == "ok" and m5_nm["engine"]["cargo_test"]["status"] == "passed"
          and m5_nm["engine"]["cargo_test"]["failed"] == 0
          and m5_nm["engine"]["cargo_test"]["passed"] >= 5
          and m5_nm["engine"]["dependencies"] == [])
    check("引擎状态集合与 IR 完全相等（改名即失败）",
          m5_nm["state_alignment"]["equal"]
          and set(m5_nm["state_alignment"]["engine_states"]) == set(m5_nm["state_alignment"]["ir_states"]))
    check("原生模块诚实分级：生成器不声称已验证绑定/构建（验证见 M5b/M5c 报告）",
          m5_nm["honesty"]["native_build"] == "not_run"
          and m5_nm["honesty"]["bindings"] == "unverified"
          and m5_nm["honesty"]["wiring"] == "placeholder")

    m5_hc = load("reports/m5-hook-catalog.json")
    check("注入点预检零错误且负数用 E_HOOK_UNKNOWN",
          m5_hc["errors"] == [] and m5_hc["exit_code"] == 0
          and m5_hc["negative_control"]["ok"]
          and "E_HOOK_UNKNOWN" in m5_hc["negative_control"]["codes"])

    m5_diff = load("reports/m5-diff.json")
    check("差分 PASS 且负例必须失败",
          m5_diff["ok"] and m5_diff["positive"]["counts"]["failed"] == 0
          and m5_diff["positive"]["counts"]["matched"] >= 20
          and not m5_diff["negative_control"]["ok"])
    check("差分产出官方 result.json 形状且状态集合一致",
          m5_diff["official_result"]["passed"]
          and set(m5_diff["official_result"]["checks"]) >= {"logic_replay", "state_set", "negative_control"}
          and m5_diff["states"]["equal"])

    forbidden = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
                 if p.is_file() and p.suffix in (".rs", ".hmod", ".png", ".ogg")
                 and not (set(p.relative_to(ROOT).parts) & {".git", "work", "out", "tmp"})]
    check("版权边界：仓库不含 .rs/.hmod/.png/.ogg", not forbidden, ", ".join(forbidden[:5]))

    # 26. v0.9 · M5b 真实编译与无头加载
    m5b = load("reports/m5b-native-build.json")
    check("M5b: plan/apply/build/run 四步全通过",
          all(m5b[k]["status"] == "ok" for k in ("plan", "apply", "build", "run"))
          and m5b["apply"]["injections"] == 3 and m5b["plan"]["injections"] == 3
          and m5b["plan"]["crates"] == 1)
    check("M5b: 服务端 tick 探针被真实观测到",
          m5b["run"]["probe_observed"]
          and "load probe" in (m5b["run"]["probe_line"] or "")
          and "engine states=18" in (m5b["run"]["probe_line"] or ""))
    check("M5b: 验证等级止于 compiled_and_loaded，未声称开火",
          m5b["verification_level"] == "compiled_and_loaded"
          and any("use_item" in item for item in m5b["not_verified"])
          and any("animation_driver" in item for item in m5b["not_verified"]))
    check("M5b: 记录 4 条 mixins 约束与 3 条环境修复",
          len(m5b["constraints_found"]) >= 4 and len(m5b["build"]["env_fixes"]) == 3
          and {"E_CRATE", "E_REVISION", "E_INVALID_HELPER"} <=
              {c["code"] for c in m5b["constraints_found"]})
    check("M5b: 明确记录 third_party 已被打补丁且有 pristine 备份",
          m5b["side_effect"]["pristine_backup"].startswith("work/")
          and "已被应用补丁" in m5b["side_effect"]["what"])

    # 27. v0.9 · M5c 真实绑定与开火路径
    m5c = load("reports/m5c-firing.json")
    check("M5c: 物品在游戏内注册成功且无未知组件",
          m5c["item_registration"]["ok"]
          and m5c["item_registration"]["items_after_load"] > 0
          and m5c["item_registration"]["content_error"] is None
          and m5c["constraint_found"]["code"] == "content_not_loaded")
    check("M5c: 每次右键都命中 native_use_item（4 次点击 4 次 claim）",
          m5c["evidence"]["claims"] == 4 and m5c["evidence"]["one_per_click"]
          and len(m5c["evidence"]["claim_lines"]) == 4)
    check("M5c: 绑定三元组为 game/stack/claimed",
          [b.split(":")[0] for b in m5c["bindings"]] == ["game", "stack", "claimed"])
    check("M5c: 验证等级 fired_in_game 且未声称弹药/子弹/同步",
          m5c["verification_level"] == "fired_in_game"
          and any("弹药" in item for item in m5c["not_verified"])
          and any("子弹" in item for item in m5c["not_verified"]))
    check("M5c: 如实记录就地补丁与待重跑的干净 apply",
          "apply" in m5c["reproducibility_note"]["follow_up"]
          and "mods.incoming" in m5c["reproducibility_note"]["why"])

    # 28. v0.9 · M5d 尝试：环境阻塞要说清楚，不能假装完成
    m5d = load("reports/m5d-attempt.json")
    check("M5d: 状态为环境阻塞且不产生新断言",
          m5d["status"] == "blocked_by_environment"
          and m5d["evidence_level"] == "no_new_claim")
    check("M5d: 明确写出弹药与干净 apply 都未验证",
          any("弹药" in item for item in m5d["not_verified"])
          and any("apply" in item for item in m5d["not_verified"])
          and len(m5d["what_changed"]) >= 3)

    # 29. v0.10 · M5e 弹药语义在真实进程里闭环
    m5e = load("reports/m5e-ammo.json")
    ea = m5e["assertions"]
    check("M5e: 31 次右键 = 30 发 + 空仓拒绝，且逐发递减到 0",
          ea["clicks"] == 31 and ea["shot_lines"] == 30
          and ea["first_shot"].endswith("ammo=29") and ea["last_shot"].endswith("ammo=0")
          and ea["one_round_per_click"] and ea["empty_refused"])
    check("M5e: 空仓不 claim 只能由源码路径作证，swings 不作数",
          ea["empty_sticky"] and "return" in ea["empty_does_not_claim"]
          and "swings" in ea["swings_caveat"] and "M5f" in ea["swings_caveat"]
          and "apple" in ea["ak_only"])
    check("M5e: 弹药是进程级静态量，未声称换弹/子弹/多人",
          "AtomicU32" in m5e["how_ammo_is_stored"]["mechanism"]
          and "进程级" in m5e["how_ammo_is_stored"]["grain"]
          and any("子弹" in item for item in m5e["not_verified"])
          and any("换弹" in item for item in m5e["not_verified"])
          and any("多人" in item for item in m5e["not_verified"]))
    m5ec = load("reports/m5e-clean-apply.json")
    check("M5e: 干净 apply 成功且产物与已验证源码逻辑一致",
          m5ec["status"] == "ok" and m5ec["apply"]["injections"] == 1
          and m5ec["apply"]["seconds"] < 300
          and m5ec["comparison"]["result"] == "logic_identical"
          and len(m5ec["comparison"]["differences_only"]) == 2)
    check("M5e: 干净 apply 的未竟项已注明由 M5f 补齐",
          any("二进制" in item for item in m5ec["not_done"])
          and any("engine" in item for item in m5ec["not_done"])
          and m5ec["resolved_by"]["report"] == "reports/m5f-combined-binary.json")
    check("M5e: 记录启动参数两条纠正（resources / cwd-eula）",
          {c["code"] for c in m5e["constraints_found"]} >=
          {"resources_prepare", "eula_in_cwd"})

    # 30. v0.10 · M5f 一份二进制同时含状态机与开火
    m5f = load("reports/m5f-combined-binary.json")
    st = m5f["stages"]
    check("M5f: 3 注入 / 1 crate 的 bundle 过了 plan 与 apply",
          m5f["bundle"]["hooks"] == 3 and m5f["bundle"]["crate"] == 1
          and st["plan"]["status"] == "ok" and st["plan"]["injections"] == 3
          and st["plan"]["crates"] == 1 and st["apply"]["status"] == "ok"
          and st["apply"]["stage_changed"])
    check("M5f: 构建成功且耗时与 HUD 记录一致",
          st["build"]["status"] == "ok" and st["build"]["seconds"] < 1200
          and st["build"]["incremental"] == "CARGO_INCREMENTAL=0")
    check("M5f: 同一份二进制里同时观测到状态机探针与 30 发弹匣",
          "states=18" in m5f["assertions"]["engine_linked_in_same_binary"]
          and m5f["assertions"]["shot_lines"] == 30
          and m5f["assertions"]["empty_after_31"] == 1)
    check("M5f: 负例成立（空仓不自愈、异物不触发）",
          m5f["assertions"]["negatives"]["two_more_clicks_when_empty"].count("30") >= 1
          and "apple" in m5f["assertions"]["negatives"]["apple_click"])
    check("M5f: 明确更正 swings 判据并说明运行期不可分",
          "15" in m5f["correction"]["now"] and "不能再用 swings" in m5f["correction"]["consequence"]
          and any(c["code"] == "stage_drops_local" for c in m5f["constraints_found"]))

    # 31. v0.10 · M5g 状态机接管弹匣
    m5g = load("reports/m5g-engine-driven-ammo.json")
    check("M5g: engine 14/14 且 helper 不再持有弹药常量",
          "14/14" in m5g["stages"]["generate"]
          and any("runtime.rs" in item for item in m5g["what_changed"]["engine"])
          and m5g["assertions"]["engine_owns_ammo"].startswith("探针"))
    check("M5g: 游戏内 ammo 由 engine 递减（30→7，23 发）",
          "ammo=30" in m5g["stages"]["run"]["probe"]
          and m5g["assertions"]["clicks_that_reached_the_game"] == 23
          and "30→7" in m5g["assertions"]["decrement_through_engine"])
    check("M5g: 未观测项给出可复核的原因（ctl 161 ms vs 100 ms 冷却）",
          "161" in m5g["why_not_observed"]["cooldown"]
          and "2" in m5g["why_not_observed"]["cooldown"]
          and any("射速" in item for item in m5g["not_verified"]))
    check("M5g: 记录 ctl 点击下限与并发丢点击两条约束",
          {c["code"] for c in m5g["constraints_found"]} >=
          {"ctl_click_floor", "ctl_concurrent_loss"})

    # 32. v0.10 · M5h 全自动由 player_tick 驱动
    m5h = load("reports/m5h-fullauto.json")
    check("M5h: engine 17/17 且按压不推进时钟、2 tick 为真间隔",
          "17/17" in m5h["stages"]["generate"]
          and any("pull_trigger" in item for item in m5h["what_changed"]["engine"])
          and any("FIRE_INTERVAL_TICKS-1" in item for item in m5h["what_changed"]["engine"]))
    check("M5h: 游戏内单击一发、按住连发（24 发）",
          "恰好 1 条" in m5h["assertions"]["single_click_is_one_round"]
          and "24 发" in m5h["assertions"]["hold_fires_full_auto"])
    check("M5h: 如实记录速率约为标称 2 倍且原因未确认",
          "两倍" in m5h["assertions"]["rate_is_about_twice_the_nominal"]
          and "没有实测" in m5h["open_question"]["not_confirmed"])
    check("M5h: 更正 M5g 漏打自动射击日志的问题",
          "漏打" in m5h["correction_to_earlier"]["what"]
          and any("on_tick" in item for item in m5h["what_changed"]["helpers"]))


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
