#!/usr/bin/env python3
"""编译前预检 Horizon 原生 bundle：hook / hook_version / helper / crate / revision。

不依赖第三方库：内置一个够用的 TOML 子集解析器（表头、字符串、整数、浮点、
布尔、数组、内联表、数组表），解析失败带行号。校验规则来自
`third_party/horizon/docs/native-mods.md` 与 `native-hooks.json`。
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # rustmc-skills

KNOWN_KINDS = {
    "HEAD",
    "BEFORE_CALL",
    "AFTER_CALL",
    "AFTER_ASSIGN",
    "RETURN",
    "TAIL",
    "INVOKE",
    "FIELD",
    "MODIFY_ARG",
    "MODIFY_EXPRESSION_VALUE",
    "OVERWRITE",
}
DEPENDENCY_TABLES = {"dependencies", "dev-dependencies", "build-dependencies"}


class TomlError(Exception):
    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


# ---------------------------------------------------------------------------
# TOML 子集
# ---------------------------------------------------------------------------

def strip_comment(text: str) -> str:
    out: list[str] = []
    quote: str | None = None
    escaped = False
    for char in text:
        if quote:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            out.append(char)
        elif char == "#":
            break
        else:
            out.append(char)
    return "".join(out)


def bracket_depth(text: str) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    for char in text:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
    return depth


class ValueParser:
    def __init__(self, text: str, line: int):
        self.text = text
        self.pos = 0
        self.line = line

    def error(self, message: str) -> TomlError:
        return TomlError(self.line, message)

    def skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def parse(self):
        value = self.parse_value()
        self.skip_ws()
        if self.pos != len(self.text):
            raise self.error(f"unexpected trailing text: {self.text[self.pos:]!r}")
        return value

    def parse_value(self):
        self.skip_ws()
        if self.pos >= len(self.text):
            raise self.error("missing value")
        char = self.text[self.pos]
        if char == '"':
            return self.parse_basic_string()
        if char == "'":
            return self.parse_literal_string()
        if char == "[":
            return self.parse_array()
        if char == "{":
            return self.parse_inline_table()
        return self.parse_bare()

    def parse_basic_string(self) -> str:
        self.pos += 1
        out: list[str] = []
        escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "b": "\b", "f": "\f"}
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == '"':
                return "".join(out)
            if char == "\\":
                if self.pos >= len(self.text):
                    raise self.error("unterminated escape")
                code = self.text[self.pos]
                self.pos += 1
                if code in escapes:
                    out.append(escapes[code])
                elif code == "u":
                    hexdigits = self.text[self.pos:self.pos + 4]
                    if not re.fullmatch(r"[0-9a-fA-F]{4}", hexdigits):
                        raise self.error("bad \\u escape")
                    out.append(chr(int(hexdigits, 16)))
                    self.pos += 4
                else:
                    raise self.error(f"unknown escape \\{code}")
            else:
                out.append(char)
        raise self.error("unterminated string")

    def parse_literal_string(self) -> str:
        self.pos += 1
        end = self.text.find("'", self.pos)
        if end < 0:
            raise self.error("unterminated literal string")
        value = self.text[self.pos:end]
        self.pos = end + 1
        return value

    def parse_array(self) -> list:
        self.pos += 1
        items: list = []
        while True:
            self.skip_ws()
            if self.pos >= len(self.text):
                raise self.error("unterminated array")
            if self.text[self.pos] == "]":
                self.pos += 1
                return items
            items.append(self.parse_value())
            self.skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1
                continue
            if self.pos < len(self.text) and self.text[self.pos] == "]":
                self.pos += 1
                return items
            raise self.error("expected ',' or ']' in array")

    def parse_inline_table(self) -> dict:
        self.pos += 1
        table: dict = {}
        while True:
            self.skip_ws()
            if self.pos >= len(self.text):
                raise self.error("unterminated inline table")
            if self.text[self.pos] == "}":
                self.pos += 1
                return table
            key_start = self.pos
            while self.pos < len(self.text) and self.text[self.pos] not in "=,}":
                self.pos += 1
            key = self.text[key_start:self.pos].strip()
            if not key:
                raise self.error("missing key in inline table")
            self.skip_ws()
            if self.pos >= len(self.text) or self.text[self.pos] != "=":
                raise self.error("expected '=' in inline table")
            self.pos += 1
            if key in table:
                raise self.error(f"duplicate key {key!r}")
            table[key] = self.parse_value()
            self.skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1
                continue
            if self.pos < len(self.text) and self.text[self.pos] == "}":
                self.pos += 1
                return table
            raise self.error("expected ',' or '}' in inline table")

    def parse_bare(self):
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ",]}\n":
            self.pos += 1
        raw = self.text[start:self.pos].strip()
        if raw == "true":
            return True
        if raw == "false":
            return False
        cleaned = raw.replace("_", "")
        if re.fullmatch(r"[-+]?\d+", cleaned):
            return int(cleaned)
        if re.fullmatch(r"[-+]?(\d+\.\d*|\d*\.\d+)([eE][-+]?\d+)?", cleaned):
            return float(cleaned)
        raise self.error(f"unsupported bare value {raw!r}")


class TomlParser:
    def __init__(self, text: str):
        self.text = text
        self.doc: dict = {}
        self.line_of: dict[tuple, int] = {}
        self.table_lines: dict[tuple, int] = {}
        self.current_path: tuple = ()

    def parse(self) -> dict:
        buffer: list[str] = []
        start_line = 0
        depth = 0
        for lineno, raw in enumerate(self.text.splitlines(), start=1):
            line = strip_comment(raw).strip()
            if not buffer:
                if not line:
                    continue
                start_line = lineno
            if line:
                buffer.append(line)
            depth += bracket_depth(line)
            if depth > 0:
                continue
            logical = " ".join(buffer).strip()
            buffer = []
            depth = 0
            if logical:
                self.parse_logical(logical, start_line)
        if buffer:
            kind = "table header" if buffer[0].startswith("[") else "array/inline table"
            raise TomlError(start_line, f"unterminated {kind}")
        return self.doc

    def parse_logical(self, line: str, lineno: int) -> None:
        if line.startswith("[["):
            if not line.endswith("]]"):
                raise TomlError(lineno, "unterminated array-of-tables header")
            name = line[2:-2].strip()
            self.open_array_table(name, lineno)
            return
        if line.startswith("["):
            if not line.endswith("]"):
                raise TomlError(lineno, "unterminated table header")
            name = line[1:-1].strip()
            self.open_table(name, lineno)
            return
        if "=" not in line:
            raise TomlError(lineno, "expected 'key = value'")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise TomlError(lineno, "empty key")
        self.assign(key, raw_value.strip(), lineno)

    def split_name(self, name: str, lineno: int) -> list[str]:
        parts = [part.strip() for part in name.split(".")]
        if not parts or any(not part for part in parts):
            raise TomlError(lineno, f"bad table name {name!r}")
        return parts

    def open_table(self, name: str, lineno: int) -> None:
        parts = self.split_name(name, lineno)
        node = self.doc
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise TomlError(lineno, f"{part!r} is not a table")
            node = child
        last = parts[-1]
        child = node.setdefault(last, {})
        if not isinstance(child, dict):
            raise TomlError(lineno, f"{last!r} is not a table")
        path = tuple(parts)
        self.current_path = path
        self.table_lines[path] = lineno

    def open_array_table(self, name: str, lineno: int) -> None:
        parts = self.split_name(name, lineno)
        node = self.doc
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise TomlError(lineno, f"{part!r} is not a table")
            node = child
        last = parts[-1]
        items = node.setdefault(last, [])
        if not isinstance(items, list):
            raise TomlError(lineno, f"{last!r} is not an array of tables")
        items.append({})
        path = tuple(parts) + (len(items) - 1,)
        self.current_path = path
        self.table_lines[path] = lineno

    def assign(self, key: str, raw_value: str, lineno: int) -> None:
        node = self.doc
        for part in self.current_path[:-1]:
            node = node[part]
        node = node[self.current_path[-1]] if self.current_path else node
        if not isinstance(node, dict):
            raise TomlError(lineno, "assignment outside a table")
        if key in node:
            raise TomlError(lineno, f"duplicate key {key!r}")
        node[key] = ValueParser(raw_value, lineno).parse()
        self.line_of[(self.current_path, key)] = lineno


def parse_toml(path: Path) -> TomlParser:
    text = path.read_text(encoding="utf-8-sig")
    return TomlParser(text)


# ---------------------------------------------------------------------------
# 路径与通用
# ---------------------------------------------------------------------------

def resolve_read(value: str | Path) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    for base in (Path.cwd(), ROOT, ROOT.parent):
        candidate = base / p
        if candidate.exists():
            return candidate.resolve()
    return (Path.cwd() / p).resolve()


def resolve_write(value: str | Path) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return (Path.cwd() / p).resolve()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def display_path(path: Path) -> str:
    """报告里的路径相对仓库根/工作区根，避免绝对路径破坏可移植性与幂等。"""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(ROOT.parent).as_posix()
        except ValueError:
            return path.as_posix()


def hash_prefix(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# revision
# ---------------------------------------------------------------------------

def horizon_revision(horizon_root: Path, catalog: Path) -> tuple[str, str, bool]:
    if (horizon_root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(horizon_root), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=20,
            )
            revision = proc.stdout.strip()
            if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", revision):
                return revision, "git", True
        except (OSError, subprocess.SubprocessError):
            pass
    if catalog.exists():
        return "snapshot:" + hash_prefix(catalog), "snapshot-catalog-sha256", False
    return "unknown", "unavailable", False


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def error(errors: list, code: str, file: Path | str, line: int | None, detail: str) -> None:
    errors.append({
        "code": code,
        "file": display_path(file) if isinstance(file, Path) else str(file),
        "line": line,
        "detail": detail,
    })


def collect_dependencies(node, path=()):
    """遍历 crate manifest，产出 (table_path, dep_name, spec)。"""
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        child_path = path + (key,)
        if key in DEPENDENCY_TABLES and isinstance(value, dict):
            for dep_name, spec in value.items():
                yield child_path, dep_name, spec
        elif isinstance(value, dict):
            yield from collect_dependencies(value, child_path)


def validate_bundle(bundle: Path, catalog_path: Path, horizon_root: Path) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    injections_report: list[dict] = []
    crates_report: list[dict] = []

    manifest = bundle / "horizon-mixin.toml"
    if not bundle.is_dir():
        error(errors, "E_BUNDLE_MISSING", bundle, None, "bundle 目录不存在")
        return {
            "errors": errors,
            "warnings": warnings,
            "injections": injections_report,
            "crates": crates_report,
            "checked": {},
            "catalog_api": None,
        }
    if not manifest.exists():
        error(errors, "E_MANIFEST_MISSING", manifest, None, "bundle 缺少 horizon-mixin.toml")
        return {
            "errors": errors,
            "warnings": warnings,
            "injections": injections_report,
            "crates": crates_report,
            "checked": {},
            "catalog_api": None,
        }

    try:
        parser = parse_toml(manifest)
        doc = parser.parse()
    except TomlError as exc:
        error(errors, "E_TOML", manifest, exc.line, exc.message)
        return {
            "errors": errors,
            "warnings": warnings,
            "injections": injections_report,
            "crates": crates_report,
            "checked": {},
            "catalog_api": None,
        }
    except (OSError, UnicodeDecodeError) as exc:
        error(errors, "E_TOML_READ", manifest, None, str(exc))
        return {
            "errors": errors,
            "warnings": warnings,
            "injections": injections_report,
            "crates": crates_report,
            "checked": {},
            "catalog_api": None,
        }

    catalog = None
    hooks: dict[str, dict] = {}
    if not catalog_path.exists():
        error(errors, "E_CATALOG_MISSING", catalog_path, None,
              "native-hooks.json 不存在，无法解析 hook 名")
    else:
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
            hooks = {entry["name"]: entry for entry in catalog.get("hooks", [])}
        except (OSError, ValueError, KeyError) as exc:
            error(errors, "E_CATALOG", catalog_path, None, f"catalog 解析失败: {exc}")

    catalog_api = max((entry.get("version", 0) for entry in hooks.values()), default=0)

    mod = doc.get("mod", {})
    if not isinstance(mod, dict) or not isinstance(mod.get("id"), str):
        error(errors, "E_MOD_ID", manifest, None, "[mod].id 缺失或不是字符串")
    if not isinstance(mod, dict) or not isinstance(mod.get("version"), str):
        error(errors, "E_MOD_VERSION", manifest, None, "[mod].version 缺失或不是字符串")

    compat = doc.get("compatibility", {})
    declared_revision = compat.get("horizon_revision") if isinstance(compat, dict) else None
    actual_revision, revision_source, revision_verified = horizon_revision(horizon_root, catalog_path)
    if not isinstance(declared_revision, str) or not declared_revision:
        error(errors, "E_REVISION_MISSING", manifest, None,
              "[compatibility].horizon_revision 缺失或不是字符串")
    elif declared_revision != actual_revision:
        error(errors, "E_REVISION_MISMATCH", manifest, None,
              f"声明 {declared_revision!r} != 实际 {actual_revision!r}（{revision_source}）")
    if not revision_verified:
        warnings.append({
            "code": "W_REVISION_NOT_GIT",
            "file": display_path(manifest),
            "line": None,
            "detail": (
                "horizon_root 不是 git checkout（无 .git），用 native-hooks.json 内容指纹 "
                f"{actual_revision} 代替 commit；无法证明等于上游 HEAD"
            ),
        })

    raw_injections = doc.get("injection", [])
    if not isinstance(raw_injections, list):
        error(errors, "E_INJECTION_SHAPE", manifest, None, "[[injection]] 不是数组表")
        raw_injections = []
    seen_ids: set[str] = set()
    for entry in raw_injections:
        if not isinstance(entry, dict):
            error(errors, "E_INJECTION_SHAPE", manifest, None, "injection 条目不是表")
            continue
        injection_id = entry.get("id")
        hook = entry.get("hook")
        hook_version = entry.get("hook_version")
        kind = entry.get("kind")
        helper = entry.get("helper")
        target = entry.get("target")
        record = {
            "id": injection_id,
            "hook": hook,
            "hook_version": hook_version,
            "kind": kind,
            "helper": helper,
            "bindings": entry.get("bindings"),
            "status": "ok",
        }
        if not isinstance(injection_id, str) or not injection_id:
            error(errors, "E_INJECTION_ID", manifest, None, "injection.id 缺失")
            record["status"] = "error"
        elif injection_id in seen_ids:
            error(errors, "E_INJECTION_DUPLICATE", manifest, None, f"重复的 injection id {injection_id!r}")
            record["status"] = "error"
        else:
            seen_ids.add(injection_id)

        if isinstance(hook, str) and hook:
            entry_catalog = hooks.get(hook)
            if catalog is not None and entry_catalog is None:
                closest = difflib.get_close_matches(hook, list(hooks), n=3, cutoff=0.0)
                error(
                    errors, "E_HOOK_UNKNOWN", manifest, None,
                    f"hook {hook!r} 不在 catalog；最接近的候选：{closest}",
                )
                record["status"] = "error"
                record["suggestions"] = closest
            elif entry_catalog is not None:
                expected = entry_catalog.get("version")
                if not isinstance(hook_version, int) or isinstance(hook_version, bool):
                    error(errors, "E_HOOK_VERSION", manifest, None,
                          f"hook {hook!r} 的 hook_version 不是整数")
                    record["status"] = "error"
                elif hook_version != expected:
                    error(
                        errors, "E_HOOK_VERSION", manifest, None,
                        f"hook {hook!r} 声明 version {hook_version}，目录是 {expected}",
                    )
                    record["status"] = "error"
        elif isinstance(target, str) and target:
            warnings.append({
                "code": "W_RAW_TARGET",
                "file": display_path(manifest),
                "line": None,
                "detail": f"injection {injection_id!r} 用 raw target {target!r}，目录无法离线校验",
            })
        else:
            error(errors, "E_HOOK_MISSING", manifest, None,
                  f"injection {injection_id!r} 既没有 hook 也没有 target")
            record["status"] = "error"

        if not isinstance(kind, str) or not kind:
            error(errors, "E_KIND_MISSING", manifest, None,
                  f"injection {injection_id!r} 缺少 kind")
            record["status"] = "error"
        elif kind not in KNOWN_KINDS:
            error(
                errors, "E_KIND_UNKNOWN", manifest, None,
                f"injection {injection_id!r} 的 kind {kind!r} 不在 {sorted(KNOWN_KINDS)}",
            )
            record["status"] = "error"

        if not isinstance(helper, str) or not helper:
            error(errors, "E_HELPER_MISSING", manifest, None,
                  f"injection {injection_id!r} 缺少 helper")
            record["status"] = "error"
        else:
            helper_path = (bundle / helper).resolve()
            try:
                helper_path.relative_to(bundle.resolve())
            except ValueError:
                error(errors, "E_HELPER_ESCAPE", manifest, None,
                      f"helper {helper!r} 越出 bundle 目录")
                record["status"] = "error"
            else:
                if not helper_path.is_file():
                    error(errors, "E_HELPER_MISSING", helper_path, None,
                          f"injection {injection_id!r} 引用的 helper 不存在")
                    record["status"] = "error"

        bindings = entry.get("bindings")
        if bindings is not None and not isinstance(bindings, list):
            error(errors, "E_BINDINGS_SHAPE", manifest, None,
                  f"injection {injection_id!r} 的 bindings 不是数组")
            record["status"] = "error"
        elif isinstance(bindings, list) and bindings:
            warnings.append({
                "code": "W_BINDINGS_UNVERIFIED",
                "file": display_path(manifest),
                "line": None,
                "detail": f"injection {injection_id!r} 有 {len(bindings)} 条 bindings，签名未离线验证",
            })
        record["bindings_count"] = len(bindings) if isinstance(bindings, list) else None
        injections_report.append(record)

    raw_crates = doc.get("crate", [])
    if not isinstance(raw_crates, list):
        error(errors, "E_CRATE_SHAPE", manifest, None, "[[crate]] 不是数组表")
        raw_crates = []
    for entry in raw_crates:
        if not isinstance(entry, dict):
            error(errors, "E_CRATE_SHAPE", manifest, None, "crate 条目不是表")
            continue
        crate_id = entry.get("id")
        crate_path = entry.get("path")
        record = {"id": crate_id, "path": crate_path, "status": "ok", "dependencies": []}
        if not isinstance(crate_id, str) or not crate_id:
            error(errors, "E_CRATE_ID", manifest, None, "crate.id 缺失")
            record["status"] = "error"
        if not isinstance(crate_path, str) or not crate_path:
            error(errors, "E_CRATE_PATH", manifest, None,
                  f"crate {crate_id!r} 缺少 path")
            record["status"] = "error"
            crates_report.append(record)
            continue
        crate_dir = (bundle / crate_path).resolve()
        try:
            crate_dir.relative_to(bundle.resolve())
        except ValueError:
            error(errors, "E_CRATE_ESCAPE", manifest, None,
                  f"crate {crate_id!r} 的 path 越出 bundle")
            record["status"] = "error"
            crates_report.append(record)
            continue
        if not crate_dir.is_dir():
            error(errors, "E_CRATE_MISSING", crate_dir, None,
                  f"crate {crate_id!r} 的目录不存在")
            record["status"] = "error"
            crates_report.append(record)
            continue
        crate_manifest = crate_dir / "Cargo.toml"
        if not crate_manifest.is_file():
            error(errors, "E_CRATE_NO_MANIFEST", crate_manifest, None,
                  f"crate {crate_id!r} 缺少 Cargo.toml")
            record["status"] = "error"
            crates_report.append(record)
            continue
        try:
            crate_doc = parse_toml(crate_manifest).parse()
        except TomlError as exc:
            error(errors, "E_CRATE_TOML", crate_manifest, exc.line, exc.message)
            record["status"] = "error"
            crates_report.append(record)
            continue
        except (OSError, UnicodeDecodeError) as exc:
            error(errors, "E_CRATE_TOML_READ", crate_manifest, None, str(exc))
            record["status"] = "error"
            crates_report.append(record)
            continue

        if "workspace" in crate_doc:
            error(errors, "E_CRATE_WORKSPACE", crate_manifest, None,
                  "crate 不能带 [workspace]")
            record["status"] = "error"
        if (crate_dir / "Cargo.lock").exists():
            warnings.append({
                "code": "W_CRATE_LOCK",
                "file": display_path(crate_dir / "Cargo.lock"),
                "line": None,
                "detail": "crate 目录里有 Cargo.lock，horizon-mixins 要求它不自带锁文件",
            })

        dependencies = list(collect_dependencies(crate_doc))
        record["dependencies"] = [dep for _, dep, _ in dependencies]
        for table_path, dep_name, spec in dependencies:
            if dep_name == "horizon-client":
                error(errors, "E_CRATE_HORIZON_DEP", crate_manifest, None,
                      "crate 不能依赖 horizon-client（会成环）")
                record["status"] = "error"
            if isinstance(spec, dict) and "path" in spec:
                error(errors, "E_CRATE_PATH_DEP", crate_manifest, None,
                      f"依赖 {dep_name!r} 含 path = {spec['path']!r}；只允许 registry crate")
                record["status"] = "error"
            if isinstance(spec, dict) and "git" in spec:
                error(errors, "E_CRATE_GIT_DEP", crate_manifest, None,
                      f"依赖 {dep_name!r} 含 git = {spec['git']!r}；只允许 registry crate")
                record["status"] = "error"
            if isinstance(spec, dict) and spec.get("workspace") is True:
                error(errors, "E_CRATE_WORKSPACE_DEP", crate_manifest, None,
                      f"依赖 {dep_name!r} 用 workspace = true，无法离线解析")
                record["status"] = "error"
        if dependencies:
            warnings.append({
                "code": "W_CRATE_DEPS_UNVERIFIED",
                "file": display_path(crate_manifest),
                "line": None,
                "detail": (
                    f"crate {crate_id!r} 有 {len(dependencies)} 个 registry 依赖；"
                    "未与 Horizon Cargo.lock 逐版本比对"
                ),
            })
        crates_report.append(record)

    return {
        "errors": errors,
        "warnings": warnings,
        "injections": injections_report,
        "crates": crates_report,
        "checked": {
            "injections": len(raw_injections),
            "helpers": len({entry.get("helper") for entry in raw_injections
                            if isinstance(entry, dict) and isinstance(entry.get("helper"), str)}),
            "crates": len(raw_crates),
            "hooks_in_catalog": len(hooks),
        },
        "catalog_api": catalog_api,
        "revision": {
            "declared": declared_revision,
            "resolved": actual_revision,
            "source": revision_source,
            "verified": revision_verified,
        },
    }


def run_negative_control(bundle: Path, catalog_path: Path, horizon_root: Path) -> dict:
    target = bundle.parent / "_negative" / bundle.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        bundle,
        target,
        ignore=shutil.ignore_patterns("target", "Cargo.lock", "_negative"),
    )
    manifest = target / "horizon-mixin.toml"
    text = manifest.read_text(encoding="utf-8")
    mutated = text.replace('hook = "use_item"', 'hook = "use_itme"', 1)
    if mutated == text:
        return {
            "ok": False,
            "path": display_path(target),
            "mutation": "none",
            "reason": "bundle 里没有 hook = \"use_item\"，无法构造负例",
            "exit_code": 0,
            "codes": [],
        }
    manifest.write_text(mutated, encoding="utf-8", newline="\n")
    result = validate_bundle(target, catalog_path, horizon_root)
    codes = [item["code"] for item in result["errors"]]
    exit_code = 1 if result["errors"] else 0
    return {
        "ok": exit_code == 1 and "E_HOOK_UNKNOWN" in codes,
        "path": display_path(target),
        "mutation": 'hook "use_item" -> "use_itme"',
        "exit_code": exit_code,
        "codes": codes,
        "errors": result["errors"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Horizon bundle 的 hook/crate/版本预检")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--catalog", default="third_party/horizon/native-hooks.json")
    parser.add_argument("--horizon-root", default="third_party/horizon")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--skip-negative-control", action="store_true")
    args = parser.parse_args(argv)

    bundle = resolve_read(args.bundle)
    catalog_path = resolve_read(args.catalog)
    horizon_root = resolve_read(args.horizon_root)
    report_path = resolve_write(args.report)

    result = validate_bundle(bundle, catalog_path, horizon_root)
    negative = None
    fatal_codes = {
        "E_BUNDLE_MISSING", "E_MANIFEST_MISSING", "E_TOML", "E_TOML_READ",
        "E_CATALOG_MISSING", "E_CATALOG",
    }
    fatal = any(item["code"] in fatal_codes for item in result["errors"])
    if not args.skip_negative_control:
        if fatal:
            negative = {
                "ok": False,
                "skipped": True,
                "path": None,
                "mutation": None,
                "reason": "正例 bundle 无法解析，未构造负例",
                "exit_code": None,
                "codes": [],
            }
        else:
            negative = run_negative_control(bundle, catalog_path, horizon_root)
            if not negative["ok"]:
                result["errors"].append({
                    "code": "E_NEGATIVE_CONTROL",
                    "file": negative["path"],
                    "line": None,
                    "detail": "负例没有被判失败，或没有给出 E_HOOK_UNKNOWN",
                })

    exit_code = 1 if result["errors"] else 0
    report = {
        "schema_version": "0.1.0",
        "task": "m5-04-hook-catalog",
        "status": "ok" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "bundle": display_path(bundle),
        "catalog": {
            "path": display_path(catalog_path),
            "sha256": sha256_file(catalog_path) if catalog_path.exists() else None,
            "hooks": result["checked"].get("hooks_in_catalog", 0),
            "catalog_api": result["catalog_api"],
        },
        "horizon_root": display_path(horizon_root),
        "revision": result.get("revision", {}),
        "checked": result["checked"],
        "injections": result["injections"],
        "crates": result["crates"],
        "errors": result["errors"],
        "warnings": result["warnings"],
        "negative_control": negative,
        "notes": [
            "只做静态预检：不运行 horizon-mixins，不编译 helper，不验证 helper 签名。",
            "crate 的 registry 依赖未与 Horizon Cargo.lock 逐版本比对（W_CRATE_DEPS_UNVERIFIED）。",
            "horizon_revision 在非 git 快照上用 native-hooks.json 指纹代替 commit，见 W_REVISION_NOT_GIT。",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(dump_json(report).encode("utf-8"))

    print(
        "%s injections=%d crates=%d errors=%d warnings=%d negative=%s"
        % (
            "OK" if exit_code == 0 else "FAILED",
            result["checked"].get("injections", 0),
            result["checked"].get("crates", 0),
            len(result["errors"]),
            len(result["warnings"]),
            "pass" if negative and negative["ok"] else ("skipped" if negative is None else "fail"),
        )
    )
    print("   report=%s" % report_path)
    for item in result["errors"]:
        print("   %-24s %s:%s %s" % (item["code"], item["file"], item["line"], item["detail"]))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
