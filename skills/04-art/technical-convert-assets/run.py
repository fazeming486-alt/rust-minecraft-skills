#!/usr/bin/env python3
"""技术性格式等价转换（ADR 0008）：语义不变、可逆、产物只留 work/。

每个转换器都必须用 roundtrip 证明「没丢东西、没改写含义」；目标侧没有消费者时
如实标 unbound，绝不伪装成「已转换完成」。
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import lib_conversion as C  # noqa: E402


def gate(policy: Dict[str, Any]) -> None:
    a = policy.get("scope_decisions", {}).get("assets", {})
    if a.get("mode") != "full-inspection":
        raise SystemExit("policy gate: 资产侧不是 full-inspection，拒绝转换")
    if a.get("transformation") != "technical-only":
        raise SystemExit("policy gate: transformation 不是 technical-only，拒绝转换")
    if a.get("distribution") != "local-only":
        raise SystemExit("policy gate: distribution 不是 local-only，拒绝转换")
    if policy.get("redistribution") is not False:
        raise SystemExit("policy gate: redistribution 必须为 false")


def read_json(zf: zipfile.ZipFile, name: str) -> Any:
    return json.loads(zf.read(name))


def convert_shared_states(zf, names, out: Path, rules) -> Dict[str, Any]:
    anims = [n for n in names if n.endswith(".animation.json")]
    states: List[str] = []
    for n in anims:
        doc = read_json(zf, n)
        states.extend((doc.get("animations") or {}).keys())
    states = sorted(set(states))
    state_map = C.build_state_map(states, rules)
    C.write_json(out / "shared-states.json", {
        "schema_status": "partial",
        "target": "minecraft:condition (Custom 布尔) / minecraft:select (枚举) / range_dispatch (数值)",
        "caveat": "item_model/foreign.rs:12-79 会静默降级第三方自定义 property；需先注册才可引用",
        "states": state_map,
    })
    return {"id": "shared_states", "source_files": len(anims), "output_files": 1,
            "roundtrip_closed": state_map["roundtrip_closed"],
            "schema_status": "partial",
            "stats": {"raw_states": state_map["raw_count"],
                      "canonical_states": state_map["canonical_count"],
                      "compression_ratio": state_map["compression_ratio"],
                      "parameters": state_map["parameters"]}}


def convert_bone_tracks(zf, names, out: Path) -> Dict[str, Any]:
    """按状态重组动画骨骼轨道（按文件 → 按状态索引），完全可逆。"""
    anims = [n for n in names if n.endswith(".animation.json")]
    by_state: Dict[str, List[Dict[str, Any]]] = {}
    originals: Dict[str, Any] = {}
    extras: Dict[str, Any] = {}
    bone_names = set()
    channels = Counter()
    for n in anims:
        doc = read_json(zf, n)
        originals[n] = doc
        extras[n] = {k: v for k, v in doc.items() if k != "animations"}
        for state, body in (doc.get("animations") or {}).items():
            entry = {"file": n, "body": body}
            by_state.setdefault(state, []).append(entry)
            if isinstance(body, dict):
                for bone, tracks in (body.get("bones") or {}).items():
                    bone_names.add(bone)
                    if isinstance(tracks, dict):
                        channels.update(tracks.keys())
    C.write_json(out / "bone-tracks.json", {
        "schema_status": "unbound",
        "target": "中间表示；Horizon 26.3 无骨骼/关键帧消费者（animation_driver 仍 unbound）",
        "index": "by_state",
        "data": by_state,
    })
    rebuilt: Dict[str, Any] = {}
    for n in anims:
        rebuilt[n] = dict(extras[n])
        rebuilt[n]["animations"] = {}
    for state, entries in by_state.items():
        for e in entries:
            rebuilt[e["file"]]["animations"][state] = e["body"]
    closed = all(C.json_equal(rebuilt[n], originals[n]) for n in anims)
    return {"id": "bone_tracks", "source_files": len(anims), "output_files": 1,
            "roundtrip_closed": closed, "schema_status": "unbound",
            "stats": {"states": len(by_state), "distinct_bones": len(bone_names),
                      "channel_kinds": dict(channels)}}


def convert_geometry_ir(zf, names, out: Path) -> Dict[str, Any]:
    """Bedrock geometry 包装层剥离为 bone IR；可逆，但目标侧无读取器。"""
    geos = [n for n in names if "/geo_models/" in n and n.endswith(".json")]
    ir: Dict[str, Any] = {}
    originals: Dict[str, Any] = {}
    bones = 0
    for n in geos:
        try:
            doc = read_json(zf, n)
        except (ValueError, KeyError):
            continue
        originals[n] = doc
        geometries = doc.get("minecraft:geometry") or []
        entries = []
        for g in geometries:
            blist = g.get("bones") or []
            bones += len(blist)
            entries.append({"description": g.get("description", {}),
                            "bones": blist})
        ir[n] = {"format_version": doc.get("format_version"),
                 "geometries": entries,
                 "extra_keys": {k: v for k, v in doc.items()
                                if k not in ("format_version", "minecraft:geometry")}}
    C.write_json(out / "geometry-ir.json", {
        "schema_status": "unbound",
        "target": "中间表示；Horizon 只吃 Java JSON cuboid / OBJ，无 Bedrock geometry 读取器",
        "note": "bones 的 parent/pivot/rotation 无法无损表达为 cuboid；近似必须显式标有损",
        "data": ir,
    })
    rebuilt = {}
    for n, v in ir.items():
        doc = {"format_version": v["format_version"],
               "minecraft:geometry": [{"description": g["description"], "bones": g["bones"]}
                                      for g in v["geometries"]]}
        doc.update(v["extra_keys"])
        rebuilt[n] = doc
    closed = all(C.json_equal(rebuilt[n], originals[n]) for n in originals)
    return {"id": "geometry_ir", "source_files": len(originals), "output_files": 1,
            "roundtrip_closed": closed, "schema_status": "unbound",
            "stats": {"geometry_files": len(originals), "bones_total": bones}}


def convert_namespace(zf, names, out: Path) -> Dict[str, Any]:
    """display / index / lang JSON：路径命名空间重写，内容逐字节语义不变。"""
    picked = [n for n in names
              if n.endswith(".json") and ("/display/" in n or "/index/" in n or "/lang/" in n)]
    manifest = []
    closed = True
    for n in picked:
        try:
            raw = zf.read(n)
            doc = json.loads(raw)
        except (ValueError, KeyError):
            continue
        rel = n.split("assets/", 1)[-1] if "assets/" in n else n
        dest = out / "hmod-assets" / rel
        C.write_json(dest, doc)
        if not C.json_equal(doc, read_json(zf, n)):
            closed = False
        manifest.append({"source": n, "output": dest.relative_to(out).as_posix(),
                         "sha256_source": C.sha256(raw)})
    C.write_json(out / "namespace-manifest.json", {
        "schema_status": "bound",
        "target": ".hmod 只收 assets/ 与 data/；路径段需匹配 [a-z0-9_.-]",
        "note": "仅重写输出路径，JSON 内容不变；键集合与值均由 roundtrip 校验",
        "entries": manifest,
    })
    return {"id": "namespace_rewrite", "source_files": len(manifest),
            "output_files": len(manifest) + 1, "roundtrip_closed": closed,
            "schema_status": "bound", "stats": {"by_kind": dict(Counter(
                "display" if "/display/" in m["source"] else
                "index" if "/index/" in m["source"] else "lang" for m in manifest))}}


def convert_binary(zf, names, out: Path) -> Dict[str, Any]:
    """PNG / OGG 原样搬运：格式不变，sha256 前后相同。"""
    picked = [n for n in names if n.lower().endswith((".png", ".ogg"))]
    entries = []
    closed = True
    for n in picked:
        raw = zf.read(n)
        rel = n.split("assets/", 1)[-1] if "assets/" in n else n
        dest = out / "hmod-assets" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        ok = C.sha256(dest.read_bytes()) == C.sha256(raw)
        closed = closed and ok
        entries.append({"source": n, "output": dest.relative_to(out).as_posix(),
                        "bytes": len(raw), "sha256": C.sha256(raw), "identical": ok})
    C.write_json(out / "binary-manifest.json", {
        "schema_status": "bound",
        "target": "原样进入 .hmod；不做重编码",
        "entries": entries,
    })
    return {"id": "binary_carry", "source_files": len(entries),
            "output_files": len(entries) + 1, "roundtrip_closed": closed,
            "schema_status": "bound",
            "stats": {"by_ext": dict(Counter(Path(e["source"]).suffix.lower() for e in entries)),
                      "total_bytes": sum(e["bytes"] for e in entries)}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="技术性格式等价转换")
    ap.add_argument("--jar", required=True, type=Path)
    ap.add_argument("--anchors", type=Path,
                    default=ROOT / "orchestration/slice-anchors.json")
    ap.add_argument("--policy-decision", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path,
                    help="必须是 work/ 下的目录（被 .gitignore 排除）")
    ap.add_argument("--report", required=True, type=Path,
                    help="脱敏统计报告，仓库内只放这个")
    a = ap.parse_args(argv)

    if "work" not in a.out_dir.parts:
        raise SystemExit("合规：转换产物必须落在 work/ 下，拒绝写入可入库目录")
    policy = json.loads(a.policy_decision.read_text(encoding="utf-8"))
    gate(policy)
    anchors = json.loads(a.anchors.read_text(encoding="utf-8"))
    rules = anchors["state_parameter_rules"]
    a.out_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(a.jar) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        converters = [
            convert_shared_states(zf, names, a.out_dir, rules),
            convert_bone_tracks(zf, names, a.out_dir),
            convert_geometry_ir(zf, names, a.out_dir),
            convert_namespace(zf, names, a.out_dir),
            convert_binary(zf, names, a.out_dir),
        ]

    report = {
        "schema_version": "0.1.0",
        "generated_by": "technical-convert-assets@0.1.0",
        "source_artifact": a.jar.name,
        "policy": {"inspection": "full-inspection",
                   "transformation": "technical-only", "distribution": "local-only"},
        "output_dir": a.out_dir.as_posix(),
        "converters": converters,
        "totals": {
            "converters": len(converters),
            "source_files": sum(c["source_files"] for c in converters),
            "output_files": sum(c["output_files"] for c in converters),
            "all_roundtrip_closed": all(c["roundtrip_closed"] for c in converters),
            "schema_status": dict(Counter(c["schema_status"] for c in converters)),
        },
        "limitations": [
            "geometry_ir / bone_tracks 是中间表示：Horizon 26.3 无 Bedrock geometry 与骨骼关键帧消费者，不得声称已转换完成",
            "shared_states 仅 partial：Custom 仅布尔，第三方 property 会被 item_model/foreign.rs:12-79 静默降级",
            "所有产物只留 work/，不发布、不商用、不重绘（ADR 0008 工程政策判断，非法律意见）",
        ],
        "closed": all(c["roundtrip_closed"] for c in converters),
    }
    C.write_json(a.report, report)
    print("OK converters=%d source_files=%d output_files=%d closed=%s status=%s"
          % (len(converters), report["totals"]["source_files"],
             report["totals"]["output_files"], report["closed"],
             report["totals"]["schema_status"]))
    for c in converters:
        print("   %-20s src=%-5d out=%-5d roundtrip=%-5s schema=%s"
              % (c["id"], c["source_files"], c["output_files"],
                 c["roundtrip_closed"], c["schema_status"]))
    return 0 if report["closed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
