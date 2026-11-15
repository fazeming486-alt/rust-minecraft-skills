#!/usr/bin/env python3
"""把 slice 描述的一件武器打成 Horizon 内容包（.hmod，API 0.2）。

只做「声明 + 资源 + 官方打包」：写 horizon-mod.toml、data/<id>/horizon/item/<item>.json
和 26.3 的 items/ models/item/ textures/item/ lang 四类资源，然后调用官方
cargo-horizon-mod build / check。产物只写 work/，不发布、不重绘贴图。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- 基础工具


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def resolve(path: str, *, must_exist: bool = True) -> Path:
    """相对路径先按仓库根解析，再按当前目录与 workspace 解析。"""
    p = Path(path)
    if p.is_absolute():
        return p
    for base in (ROOT, Path.cwd(), ROOT.parent):
        candidate = (base / p).resolve()
        if candidate.exists() or not must_exist:
            return candidate
    return (ROOT / p).resolve()


def png_header(data: bytes) -> Optional[Tuple[int, int, int, int]]:
    """从 IHDR 读宽高、位深、颜色类型；不是 PNG 返回 None。"""
    if len(data) < 33 or data[:8] != PNG_MAGIC or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height, data[24], data[25]


def toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------- 输入


def load_slice(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def check_policy(slice_doc: Dict[str, Any]) -> None:
    policy = slice_doc.get("policy") or {}
    assets = policy.get("assets") or {}
    if assets.get("transformation") != "technical-only":
        raise SystemExit("policy gate: assets.transformation 必须是 technical-only")
    if assets.get("distribution") != "local-only":
        raise SystemExit("policy gate: assets.distribution 必须是 local-only")
    if (policy.get("code") or {}).get("distribution") != "local-only":
        raise SystemExit("policy gate: code.distribution 必须是 local-only")


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"slice 不完整: {message}")


def read_inputs(slice_doc: Dict[str, Any], workspace_root: Path) -> Dict[str, Any]:
    target = slice_doc.get("target") or {}
    source = slice_doc.get("source") or {}
    for key in ("mod_id", "mod_name", "item_id", "template_item", "hmod_api"):
        require(isinstance(target.get(key), str) and target[key], f"target.{key}")
    for key in ("mod_root", "texture_slot"):
        require(isinstance(source.get(key), str) and source[key], f"source.{key}")

    mod_id = target["mod_id"]
    item_id = target["item_id"]
    require(":" in item_id, "target.item_id 必须是 namespace:path")
    item_ns, item_path = item_id.split(":", 1)
    require(item_ns == mod_id, "target.item_id 的 namespace 必须等于 mod_id")

    mod_root = workspace_root / source["mod_root"]
    texture_src = mod_root / source["texture_slot"]
    require(texture_src.is_file(), f"贴图不存在: {texture_src}")

    return {
        "mod_id": mod_id,
        "mod_name": target["mod_name"],
        "item_ns": item_ns,
        "item_path": item_path,
        "item_id": item_id,
        "template_item": target["template_item"],
        "api": target["hmod_api"],
        "version": str(slice_doc.get("version") or "0.1.0"),
        "texture_src": texture_src,
        "texture_rel": source["texture_slot"],
        "lang_name": target.get("display_name") or target["mod_name"],
        "item_model_ref": f"{mod_id}:item/{item_path}",
    }


# ---------------------------------------------------------------- 生成内容包


def item_declaration(inp: Dict[str, Any]) -> Dict[str, Any]:
    """物品声明：template + 顶层 max_stack_size，不带任何组件。

    两条都是实测约束：
    - `minecraft:max_stack_size` 不能出现在 components 里：`content::check_item` 要求
      「set max_stack_size instead」，所以上限写在顶层。
    - 26.3 的 `minecraft:custom_data` **不是已知组件类型**，写上会让整个内容包拒绝加载
      （`content not loaded: … is not a known component type`）。身份直接用物品 id 判断。
    """
    return {
        "template": inp["template_item"],
        "max_stack_size": 1,
    }


def manifest_text(inp: Dict[str, Any]) -> str:
    lines = [
        f"id = {toml_string(inp['mod_id'])}",
        f"name = {toml_string(inp['mod_name'])}",
        f"version = {toml_string(inp['version'])}",
        'description = "Local research build of a TaCZ weapon for Horizon 26.3; '
        'not published, not for redistribution."',
        "authors = []",
        f"api = {toml_string(inp['api'])}",
        'side = "both"',
        'capabilities = ["registries"]',
        "namespaces = []",
        "",
    ]
    return "\n".join(lines)


def authored_files(inp: Dict[str, Any]) -> Dict[str, bytes]:
    ns, item = inp["item_ns"], inp["item_path"]
    item_def = {
        "model": {"type": "minecraft:model", "model": inp["item_model_ref"]},
    }
    item_model = {
        "parent": "minecraft:item/generated",
        "textures": {"layer0": f"{ns}:item/{item}"},
    }
    lang = {f"item.{ns}.{item}": inp["lang_name"]}
    texture = inp["texture_src"].read_bytes()
    return {
        "horizon-mod.toml": manifest_text(inp).encode("utf-8"),
        f"data/{ns}/horizon/item/{item}.json": (
            json.dumps(item_declaration(inp), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        f"assets/{ns}/items/{item}.json": (
            json.dumps(item_def, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        f"assets/{ns}/models/item/{item}.json": (
            json.dumps(item_model, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        f"assets/{ns}/textures/item/{item}.png": texture,
        f"assets/{ns}/lang/en_us.json": (
            json.dumps(lang, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }


def write_package(mod_dir: Path, files: Dict[str, bytes]) -> None:
    if mod_dir.exists():
        shutil.rmtree(mod_dir)
    mod_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        path = mod_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


# ---------------------------------------------------------------- 官方工具


def _shown_arg(arg: str) -> str:
    """命令行里的仓库内绝对路径改写成相对路径，报告不绑定本机目录。"""
    try:
        p = Path(arg)
        if p.is_absolute() and ROOT in p.parents:
            return str(p.relative_to(ROOT)).replace("\\", "/")
    except (OSError, ValueError):
        pass
    return arg


def run_tool(tool: Path, args: List[str], cwd: Path) -> Dict[str, Any]:
    proc = subprocess.run(
        [str(tool), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    return {
        "cmd": f"{tool.name} {' '.join(_shown_arg(a) for a in args)}",
        "cwd": rel(cwd),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def parse_json_output(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text = (result.get("stdout") or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            return None
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------- 自检


def check_manifest(text: str) -> List[Dict[str, Any]]:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    required = [
        "id = ", "name = ", "version = ", "description = ", "authors = ",
        "api = ", "side = ", "capabilities = ", "namespaces = ",
    ]
    missing = [key for key in required if key not in text]
    add("manifest_fields", not missing, "缺少: " + ", ".join(missing) if missing else "9 个字段齐全")
    add("manifest_api", 'api = "0.2"' in text, "api=0.2")
    add("manifest_capability", 'capabilities = ["registries"]' in text, "capabilities 含 registries")
    add("manifest_side", 'side = "both"' in text, "side=both")
    return checks


def check_assets(mod_dir: Path, inp: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    ns, item = inp["item_ns"], inp["item_path"]
    items_path = mod_dir / f"assets/{ns}/items/{item}.json"
    model_path = mod_dir / f"assets/{ns}/models/item/{item}.json"
    texture_path = mod_dir / f"assets/{ns}/textures/item/{item}.png"
    lang_path = mod_dir / f"assets/{ns}/lang/en_us.json"

    try:
        item_def = json.loads(items_path.read_text(encoding="utf-8"))
        ref = item_def["model"]["model"]
        add("item_model_definition", True, f"items/{item}.json -> {ref}")
    except Exception as exc:  # noqa: BLE001 - 记录任何解析失败
        ref = ""
        add("item_model_definition", False, f"{type(exc).__name__}: {exc}")

    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        parent_ok = model.get("parent") == "minecraft:item/generated"
        layer_ok = (model.get("textures") or {}).get("layer0") == f"{ns}:item/{item}"
        add("item_model", parent_ok and layer_ok,
            f"parent={model.get('parent')} layer0={(model.get('textures') or {}).get('layer0')}")
    except Exception as exc:  # noqa: BLE001
        add("item_model", False, f"{type(exc).__name__}: {exc}")

    expected = inp["texture_src"].read_bytes()
    actual = texture_path.read_bytes() if texture_path.is_file() else b""
    add("texture_bytes_preserved", actual == expected,
        f"源 {sha256(expected)[:16]} / 目标 {sha256(actual)[:16]}" if actual else "贴图缺失")

    raw_ref_ok = ref == f"{ns}:item/{item}" and model_path.is_file() and texture_path.is_file()
    add("asset_reference_closure", raw_ref_ok,
        f"{ref} -> {rel(model_path)} -> {rel(texture_path)}")

    try:
        lang = json.loads(lang_path.read_text(encoding="utf-8"))
        key = f"item.{ns}.{item}"
        add("lang_entry", key in lang, f"{key}={lang.get(key)!r}")
    except Exception as exc:  # noqa: BLE001
        add("lang_entry", False, f"{type(exc).__name__}: {exc}")
    return checks


def check_item_declaration(mod_dir: Path, inp: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    ns, item = inp["item_ns"], inp["item_path"]
    path = mod_dir / f"data/{ns}/horizon/item/{item}.json"
    try:
        decl = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return ([{"name": "item_declaration", "ok": False, "detail": f"{type(exc).__name__}: {exc}"}], {})

    checks = [
        {"name": "item_template", "ok": decl.get("template") == inp["template_item"],
         "detail": f"template={decl.get('template')}"},
        {"name": "item_max_stack_size", "ok": decl.get("max_stack_size") == 1,
         "detail": f"顶层 max_stack_size={decl.get('max_stack_size')}"},
        {"name": "item_no_unknown_components",
         "ok": not (decl.get("components") or {}),
         "detail": "components 为空：26.3 的 minecraft:custom_data 不是已知组件，会拒绝整个内容包"},
    ]
    return checks, decl


def check_package(path: Path, inp: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    with zipfile.ZipFile(path) as zf:
        names = sorted(zf.namelist())
    extra = [n for n in names if n != "horizon-mod.toml" and not n.startswith(("assets/", "data/"))]
    no_code = [n for n in names if n.endswith(".rs") or Path(n).name == "Cargo.toml"]
    add("package_layout", not extra, "多余条目: " + ", ".join(extra) if extra else f"{len(names)} 个条目，只有 manifest/assets/data")
    add("package_no_code", not no_code, "含代码: " + ", ".join(no_code) if no_code else "无 Cargo.toml / .rs")
    add("package_manifest_present", "horizon-mod.toml" in names, "horizon-mod.toml 在根")
    ns, item = inp["item_ns"], inp["item_path"]
    want = {
        f"data/{ns}/horizon/item/{item}.json",
        f"assets/{ns}/items/{item}.json",
        f"assets/{ns}/models/item/{item}.json",
        f"assets/{ns}/textures/item/{item}.png",
        f"assets/{ns}/lang/en_us.json",
    }
    missing = sorted(want - set(names))
    add("package_required_entries", not missing, "缺少: " + ", ".join(missing) if missing else "5 个必需条目都在")
    return checks


def negative_control(tool: Path, mod_dir: Path, inp: Dict[str, Any]) -> Dict[str, Any]:
    """删掉 template 后官方必须拒绝：证明校验不是摆设。"""
    base = mod_dir.parent / "_negative"
    target = base / inp["mod_id"]
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    shutil.copytree(mod_dir, target, ignore=shutil.ignore_patterns("target"))

    ns, item = inp["item_ns"], inp["item_path"]
    item_path = target / f"data/{ns}/horizon/item/{item}.json"
    decl = json.loads(item_path.read_text(encoding="utf-8"))
    removed = decl.pop("template", None)
    write_json(item_path, decl)

    build = run_tool(tool, ["build"], target)
    result: Dict[str, Any] = {
        "what": "复制内容包到 _negative，删除 item JSON 的 template 字段",
        "removed_field": "template",
        "removed_value": removed,
        "build": build,
        "check": None,
        "ok": False,
        "detail": "",
    }
    if build["returncode"] != 0:
        result["ok"] = True
        result["detail"] = "官方 build 按预期失败: " + (build["stderr"] or build["stdout"]).strip()[:800]
        return result

    # 万一 build 放过了（不应发生），再让 check 兜底。
    produced = target / "target/horizon-mod" / f"{inp['mod_id']}.hmod"
    if not produced.is_file():
        result["detail"] = "build 返回 0 却没有产物，无法判定"
        return result
    checked = run_tool(tool, ["check", str(produced), "--kind", "mod", "--json"], target)
    parsed = parse_json_output(checked) or {}
    result["check"] = {"result": checked, "parsed": parsed}
    failed = checked["returncode"] != 0 or parsed.get("ok") is False
    result["ok"] = failed
    result["detail"] = "build 未拒绝破坏样本，但 check 拒绝" if failed else "build 与 check 都放过了破坏样本"
    return result


# ---------------------------------------------------------------- 主流程


def main() -> int:
    parser = argparse.ArgumentParser(description="生成并用官方工具校验 Horizon 内容包 (.hmod)")
    parser.add_argument("--slice", default="orchestration/m5-slice.json")
    parser.add_argument("--official-tool", default="third_party/horizon/target/debug/cargo-horizon-mod.exe")
    parser.add_argument("--report", default="reports/m5-content-mod.json")
    parser.add_argument("--mod-dir", default=None, help="默认取 slice.outputs.content_mod_dir")
    parser.add_argument("--hmod-out", default=None, help="默认取 slice.outputs.hmod")
    args = parser.parse_args()

    slice_path = resolve(args.slice)
    tool = resolve(args.official_tool)
    report_path = resolve(args.report, must_exist=False)
    if not slice_path.is_file():
        raise SystemExit(f"slice 不存在: {slice_path}")
    if not tool.is_file():
        raise SystemExit(f"官方工具不存在: {tool}")

    slice_doc = load_slice(slice_path)
    check_policy(slice_doc)
    workspace = Path(slice_doc["source"].get("workspace_root") or ROOT.parent)
    inp = read_inputs(slice_doc, workspace)

    outputs = slice_doc.get("outputs") or {}
    mod_dir = resolve(args.mod_dir or outputs.get("content_mod_dir") or f"work/m5/content-mod/{inp['mod_id']}")
    hmod_out = resolve(args.hmod_out or outputs.get("hmod") or f"work/m5/{inp['mod_id']}.hmod", must_exist=False)
    for path in (mod_dir, hmod_out):
        if "work" not in path.resolve().parts:
            raise SystemExit(f"产物必须写在 work/ 下: {path}")

    files = authored_files(inp)
    write_package(mod_dir, files)

    # 生成侧自检
    checks: List[Dict[str, Any]] = []
    checks.extend(check_manifest(files["horizon-mod.toml"].decode("utf-8")))
    item_checks, item_decl = check_item_declaration(mod_dir, inp)
    checks.extend(item_checks)
    checks.extend(check_assets(mod_dir, inp))

    # 官方打包两次，验证可复现
    built = mod_dir / "target/horizon-mod" / f"{inp['mod_id']}.hmod"
    runs: List[Dict[str, Any]] = []
    build_logs: List[Dict[str, Any]] = []
    for _ in range(2):
        log = run_tool(tool, ["build"], mod_dir)
        build_logs.append(log)
        if log["returncode"] != 0 or not built.is_file():
            break
        data = built.read_bytes()
        runs.append({"sha256": sha256(data), "bytes": len(data)})

    build_ok = len(runs) == 2
    checks.append({
        "name": "official_build",
        "ok": build_ok,
        "detail": "两次 build 均成功" if build_ok else "build 失败: " + (build_logs[-1]["stderr"] or build_logs[-1]["stdout"]).strip()[:800],
    })

    reproducible = build_ok and runs[0]["sha256"] == runs[1]["sha256"]
    checks.append({
        "name": "reproducible",
        "ok": reproducible,
        "detail": (
            f"两次 sha256 相同 {runs[0]['sha256']}"
            if reproducible
            else f"两次不一致: {runs[0]['sha256']} vs {runs[1]['sha256']}"
            if build_ok
            else "未完成两次打包"
        ),
    })

    official: Dict[str, Any] = {}
    check_log: Dict[str, Any] = {}
    hmod_info: Dict[str, Any] = {"path": rel(hmod_out), "sha256": None, "bytes": 0}
    package_checks: List[Dict[str, Any]] = []
    if build_ok:
        shutil.copyfile(built, hmod_out)
        data = hmod_out.read_bytes()
        hmod_info = {"path": rel(hmod_out), "sha256": sha256(data), "bytes": len(data)}
        package_checks = check_package(hmod_out, inp)
        check_log = run_tool(tool, ["check", str(hmod_out), "--kind", "mod", "--json"], ROOT)
        official = parse_json_output(check_log) or {}
        checks.append({
            "name": "official_check",
            "ok": official.get("ok") is True,
            "detail": json.dumps(official, ensure_ascii=False)[:800]
            if official
            else "check 未返回 JSON: " + (check_log["stderr"] or check_log["stdout"]).strip()[:800],
        })
    else:
        checks.append({"name": "official_check", "ok": False, "detail": "未产出 .hmod，跳过 check"})
    checks.extend(package_checks)

    neg = negative_control(tool, mod_dir, inp)
    checks.append({"name": "negative_control", "ok": neg["ok"], "detail": neg["detail"]})

    ok = (
        official.get("ok") is True
        and reproducible
        and neg["ok"]
        and all(c["ok"] for c in checks)
    )

    texture_bytes = files[f"assets/{inp['item_ns']}/textures/item/{inp['item_path']}.png"]
    dims = png_header(texture_bytes)
    file_entries = []
    for name in sorted(files):
        entry = {"path": name, "bytes": len(files[name]), "sha256": sha256(files[name])}
        if name.endswith(".png"):
            entry["image"] = (
                {"width": dims[0], "height": dims[1], "bit_depth": dims[2], "color_type": dims[3]}
                if dims else None
            )
        file_entries.append(entry)

    report = {
        "schema_version": "0.1.0",
        "skill": "build-content-mod",
        "slice": rel(slice_path),
        "ok": ok,
        "mod": {
            "id": inp["mod_id"],
            "name": inp["mod_name"],
            "version": inp["version"],
            "api": inp["api"],
            "side": "both",
            "capabilities": ["registries"],
        },
        "item": {
            "id": inp["item_id"],
            "declaration": item_decl,
            "display_name": inp["lang_name"],
            "lang_name_source": "target.display_name（缺省回退 target.mod_name）",
            "model": inp["item_model_ref"],
        },
        "official": official,
        "official_commands": {"build": build_logs, "check": check_log},
        "hmod": hmod_info,
        "reproducibility": {"runs": runs, "reproducible": reproducible},
        "files": file_entries,
        "checks": checks,
        "negative_control": neg,
        "policy": {
            "distribution": "local-only",
            "assets_in_repo": False,
            "redrawn": False,
            "published": False,
            "note": "贴图只拷进 work/，报告只含文件名、尺寸与 sha256，不含图像内容",
        },
        "notes": [
            "minecraft:max_stack_size 不能写进 components：官方工具实测报 component \"minecraft:max_stack_size\": set max_stack_size instead，上限因此写在顶层 max_stack_size",
            "不写 components：26.3 的 minecraft:custom_data 不是已知组件类型，写上会让内容包拒绝加载",
            "官方 check 通过只代表声明与包结构合法，不代表物品能在游戏里出现或开火",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(json.dumps({
        "ok": ok,
        "official_ok": official.get("ok"),
        "reproducible": reproducible,
        "negative_ok": neg["ok"],
        "hmod": hmod_info,
        "report": rel(report_path),
    }, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
