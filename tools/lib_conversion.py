#!/usr/bin/env python3
"""技术性格式等价转换的共享原语（纯标准库、确定性）。

technical-only 的定义：语义不变的结构转换。每个转换都必须能用 roundtrip 证明
「没丢东西、没改写含义」；做不到就标 unbound，不许伪装成已转换。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Set, Tuple


def canonicalize(state: str, rules: List[Dict[str, Any]]) -> Tuple[str, Set[str]]:
    """把参数化变体折叠为 canonical 状态，返回用到的参数名集合。"""
    params: Set[str] = set()
    canon = state
    for rule in rules:
        pattern = re.compile(rule["pattern"])
        while True:
            m = pattern.search(canon)
            if not m:
                break
            params.add(rule["parameter"])
            canon = canon[:m.start()] + canon[m.end():]
            canon = canon.rstrip("_")
            if not canon:
                canon = state
                break
    return canon, params


def build_state_map(states: List[str], rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构造 canonical -> raw 映射并做 roundtrip 闭合校验。

    closed 为 true 当且仅当：展开后集合与原集合完全相等，且没有 raw 状态
    被映射到两个 canonical。
    """
    mapping: Dict[str, List[str]] = {}
    parameters: Set[str] = set()
    for state in states:
        canon, params = canonicalize(state, rules)
        mapping.setdefault(canon, []).append(state)
        parameters |= params
    for group in mapping.values():
        group.sort()
    expanded = [s for group in mapping.values() for s in group]
    closed = (sorted(expanded) == sorted(states)
              and len(expanded) == len(set(expanded)))
    return {
        "canonical": {k: mapping[k] for k in sorted(mapping)},
        "parameters": sorted(parameters),
        "raw_count": len(states),
        "canonical_count": len(mapping),
        "compression_ratio": round(1 - len(mapping) / len(states), 4) if states else 0.0,
        "roundtrip_closed": closed,
    }


def normalize(obj: Any) -> Any:
    """JSON 归一化：键排序、列表保序。用于 roundtrip 语义等价比较。"""
    if isinstance(obj, dict):
        return {k: normalize(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [normalize(x) for x in obj]
    return obj


def json_equal(a: Any, b: Any) -> bool:
    return json.dumps(normalize(a), sort_keys=True, ensure_ascii=False) == \
           json.dumps(normalize(b), sort_keys=True, ensure_ascii=False)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
