#!/usr/bin/env python3
"""从 Horizon 的 native-hooks.json 生成 NeoForge 事件 → Horizon hook 映射表。

只提取名称与契约元数据，不复制任何 Horizon 源码。Horizon 为 MIT；
生成物只含映射关系与证据路径，便于离线使用与审计。

用法:
  python tools/build_hook_mapping.py \
    --horizon-root "D:/RUST重写mc项目/third_party/horizon" \
    --out mappings/forge-to-horizon.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


def clean_events(raw: str) -> List[str]:
    text = re.sub(r"\s*\([^)]*\)", "", raw)
    text = re.sub(r"\s*\[[^\]]*\]", "", text)
    parts = re.split(r"\s*/\s*|\s*,\s*", text)
    out = []
    for part in parts:
        value = part.strip().rstrip(".")
        if value and not value.lower().startswith("none"):
            out.append(value)
    return out


def build(horizon_root: Path) -> Dict[str, Any]:
    catalog_path = horizon_root / "native-hooks.json"
    with catalog_path.open("r", encoding="utf-8") as f:
        catalog = json.load(f)
    hooks = catalog["hooks"]

    entries: List[Dict[str, Any]] = []
    for hook in hooks:
        raw = hook.get("neoforge")
        if not raw:
            continue
        for event in clean_events(raw):
            entries.append({
                "neoforge_event": event,
                "horizon_hook": hook["name"],
                "side": hook.get("side"),
                "contract": (hook.get("mod_api") or {}).get("contract"),
                "cancellable": hook.get("cancellable"),
                "hook_version": hook.get("version"),
                "target_symbol": hook.get("target"),
            })

    none_count = sum(1 for h in hooks if h.get("neoforge") and h["neoforge"].lower().startswith("none"))
    return {
        "schema_version": "0.1.0",
        "mapping_version": "0.1.0",
        "source": {
            "horizon_root": str(horizon_root),
            "catalog": "native-hooks.json",
            "license": "Horizon MIT；本表只含名称与契约元数据，不含源码",
            "note": "由 tools/build_hook_mapping.py 生成，不要手改；升级 Horizon 快照后重跑即可",
        },
        "stats": {
            "hooks_total": len(hooks),
            "hooks_with_neoforge_field": sum(1 for h in hooks if h.get("neoforge")),
            "hooks_with_event_mapping": sum(1 for h in hooks if h.get("neoforge")) - none_count,
            "hooks_without_neoforge_counterpart": none_count,
            "hooks_without_neoforge_field": len(hooks) - sum(1 for h in hooks if h.get("neoforge")),
            "mapping_entries": len(entries),
            "distinct_events": len({e["neoforge_event"] for e in entries}),
            "by_side": dict(sorted(Counter(str(e["side"]) for e in entries).items())),
            "by_contract": dict(sorted(Counter(str(e["contract"]) for e in entries).items())),
        },
        "usage": "api-mapping-table 与 classify 的 behavior_delta → event_hook 路由查此表；未命中即记为能力缺口，不得猜测",
        "entries": sorted(entries, key=lambda e: (e["neoforge_event"], e["horizon_hook"])),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon-root", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    mapping = build(args.horizon_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = mapping["stats"]
    print("OK hooks=%d with_neoforge=%d entries=%d distinct_events=%d out=%s"
          % (s["hooks_total"], s["hooks_with_neoforge_field"],
             s["mapping_entries"], s["distinct_events"], args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
