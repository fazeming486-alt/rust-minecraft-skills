#!/usr/bin/env python3
"""双轨事实提取库：Java 源码解析 + class 字节码常量池解析。

仅用 Python 标准库。输出符合 schemas/artifact-index.schema.json。
源码轨给人和模型读；字节码轨是 ground truth。两者结构一致，便于对照。
"""
from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

RE_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
RE_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+?)(\.\*)?\s*;", re.M)
RE_ANNOTATION = re.compile(r"@([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)")
RE_STRING = re.compile(r'"((?:\\.|[^"\\])*)"')
RE_CLASS_DECL = re.compile(
    r"\b(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)*\s*"
    r"(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)"
)
RE_METHOD = re.compile(
    r"\b(?:public|protected|private)\s+(?:static\s+|final\s+|abstract\s+|synchronized\s+|native\s+)*"
    r"(?:<[^>]+>\s*)?[\w$<>,\[\].?]+\s+([A-Za-z_$][\w$]*)\s*\("
)
RE_REGISTER_CALL = re.compile(r"\.register\s*\(\s*\"")


def strip_comments(text: str) -> str:
    """把注释替换为空格，保留字符串字面量与整体长度。"""
    out = list(text)
    i, n = 0, len(text)
    state = "code"
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == '"' or c == "'":
                state = c
            elif c == "/" and nxt == "/":
                out[i] = out[i + 1] = " "
                state = "line"
            elif c == "/" and nxt == "*":
                out[i] = out[i + 1] = " "
                state = "block"
        elif state in ('"', "'"):
            if c == "\\":
                i += 2
                continue
            if c == state:
                state = "code"
        elif state == "line":
            if c == "\n":
                state = "code"
            else:
                out[i] = " "
        elif state == "block":
            if c == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "code"
                continue
            if c != "\n":
                out[i] = " "
        i += 1
    return "".join(out)


def empty_symbols() -> Dict[str, Any]:
    return {"annotations": [], "superclasses": [], "interfaces": [],
            "import_prefixes": [], "referenced_types": [], "constant_strings": [],
            "methods": [], "declared_kind": "class"}


def default_flags() -> Dict[str, Any]:
    return {"synthetic": False, "anonymous": False, "decompile_failed": False,
            "native": False, "obfuscated": False, "registration_id_count": 0}


def parse_java_source(text: str, rel_path: str) -> Dict[str, Any]:
    text = text.lstrip("\ufeff")
    clean = strip_comments(text)
    imports = RE_IMPORT.findall(clean)
    imported_types: Dict[str, str] = {}
    prefixes: Set[str] = set()
    for fqn, wildcard in imports:
        if wildcard:
            prefixes.add(fqn + ".")
        else:
            simple = fqn.rsplit(".", 1)[-1]
            imported_types[simple] = fqn
            prefixes.add(fqn.rsplit(".", 1)[0] + ".")

    annotations: Set[str] = set()
    for match in RE_ANNOTATION.finditer(clean):
        raw = match.group(1)
        head, _, tail = raw.partition(".")
        base = imported_types.get(head)
        if base:
            annotations.add(base + ("." + tail if tail else ""))
        else:
            annotations.add(raw)

    pkg = RE_PACKAGE.search(clean)
    package = pkg.group(1) if pkg else ""
    if not package:
        parent = Path(rel_path).parent.as_posix()
        package = parent.replace("/", ".") if parent != "." else ""
    kind_match = re.search(r"@?\b(class|interface|enum|record)\s+([A-Za-z_$][\w$]*)", clean)
    declared_kind = "class"
    if kind_match:
        token = kind_match.group(0)
        declared_kind = "annotation" if token.startswith("@interface") else kind_match.group(1)
    strings = [m.group(1) for m in RE_STRING.finditer(clean)]
    strings = [s for s in strings if 1 <= len(s) <= 160]
    decl = RE_CLASS_DECL.search(clean)
    class_name = decl.group(1) if decl else (kind_match.group(2) if kind_match else Path(rel_path).stem)
    methods = list(dict.fromkeys(RE_METHOD.findall(clean)))

    symbols = empty_symbols()
    symbols.update({
        "annotations": sorted(annotations),
        "import_prefixes": sorted(prefixes),
        "referenced_types": sorted(set(imported_types.values())),
        "constant_strings": strings[:400],
        "methods": methods[:200],
        "declared_kind": declared_kind,
    })
    flags = default_flags()
    flags["registration_id_count"] = len(RE_REGISTER_CALL.findall(clean))
    return {
        "unit_id": "cls:" + (package.replace(".", "/") + "/" if package else "") + class_name,
        "path": rel_path,
        "kind": "class",
        "symbols": symbols,
        "flags": flags,
    }


def index_from_source_tree(root: Path, source_root: str = "src/main/java") -> Dict[str, Any]:
    base = root / source_root
    units = []
    for path in sorted(base.rglob("*.java")):
        rel = path.relative_to(base).as_posix()
        try:
            units.append(parse_java_source(path.read_text(encoding="utf-8", errors="replace"), rel))
        except OSError:
            continue
    return {"schema_version": "0.1.0",
            "source": {"artifact_id": root.name, "loader": "forge",
                       "loader_profile": "forge/1.20.1", "mc_version": "1.20.1",
                       "mapping_id": "mojmap+parchment", "checksum_sha256": None},
            "units": units}


# ---- class 文件解析 ----

def _u1(data: bytes, pos: int) -> Tuple[int, int]:
    return data[pos], pos + 1


def _u2(data: bytes, pos: int) -> Tuple[int, int]:
    return struct.unpack_from(">H", data, pos)[0], pos + 2


def _u4(data: bytes, pos: int) -> Tuple[int, int]:
    return struct.unpack_from(">I", data, pos)[0], pos + 4


class ClassFile:
    def __init__(self, data: bytes):
        self.data = data
        self.cp: List[Any] = []
        self.utf8: List[str] = []
        self.annotations: Set[str] = set()
        self.strings: Set[str] = set()
        self.class_refs: Set[str] = set()
        self.methods: Set[str] = set()
        self.superclass = ""
        self.interfaces: Set[str] = set()
        self._parse()

    def _utf8(self, idx: int) -> str:
        """idx 是常量池索引，需先解析出对应的 Utf8 条目。"""
        if 0 < idx <= len(self.cp):
            entry = self.cp[idx - 1]
            if entry and entry[0] == 1 and 0 < entry[1] <= len(self.utf8):
                return self.utf8[entry[1] - 1]
        return ""

    def _class_name(self, idx: int) -> str:
        entry = self.cp[idx - 1] if 0 < idx <= len(self.cp) else None
        if isinstance(entry, tuple) and entry[0] == 7:
            return self._utf8(entry[1]).replace("/", ".")
        return ""

    def _parse(self) -> None:
        d = self.data
        pos = 8  # magic + minor + major
        count, pos = _u2(d, pos)
        idx = 1
        while idx < count:
            tag, pos = _u1(d, pos)
            if tag == 1:
                length, pos = _u2(d, pos)
                raw = d[pos:pos + length]
                pos += length
                self.cp.append((tag,))
                self.utf8.append(raw.decode("utf-8", errors="replace"))
                # cp index -> utf8 index mapping
                self.cp[-1] = (tag, len(self.utf8))
            elif tag in (7, 8, 16, 19, 20):
                v, pos = _u2(d, pos)
                self.cp.append((tag, v))
            elif tag in (9, 10, 11, 12, 17, 18):
                a, pos = _u2(d, pos)
                b, pos = _u2(d, pos)
                self.cp.append((tag, a, b))
            elif tag == 15:
                a, pos = _u1(d, pos)
                b, pos = _u2(d, pos)
                self.cp.append((tag, a, b))
            elif tag in (3, 4):
                _, pos = _u4(d, pos)
                self.cp.append((tag,))
            elif tag in (5, 6):
                pos += 8
                self.cp.append((tag,))
                self.cp.append((0,))  # Long/Double 占两个 cp 槽，第二个不可用
                idx += 1
            else:
                raise ValueError("未知常量池 tag %d @%d" % (tag, pos))
            idx += 1

        for entry in self.cp:
            if entry[0] == 1:
                value = self.utf8[entry[1] - 1]
                if value.startswith("L") and value.endswith(";") and "/" in value:
                    self.class_refs.add(value[1:-1].replace("/", ".").replace("$", "."))
                for m in re.findall(r"L([\w/$]+);", value):
                    self.class_refs.add(m.replace("/", ".").replace("$", "."))
            elif entry[0] == 8:
                value = self._utf8(entry[1])
                if 0 < len(value) <= 160:
                    self.strings.add(value)

        self.access_flags, pos = _u2(d, pos)
        this_idx, pos = _u2(d, pos)
        super_idx, pos = _u2(d, pos)
        self.this_class = self._class_name(this_idx)
        self.superclass = self._class_name(super_idx)
        iface_count, pos = _u2(d, pos)
        for _ in range(iface_count):
            i, pos = _u2(d, pos)
            name = self._class_name(i)
            if name:
                self.interfaces.add(name)
            pos += 0

        def skip_members(p: int, collect: bool = False) -> int:
            mcount, p = _u2(d, p)
            for _ in range(mcount):
                _, p = _u2(d, p)  # access
                name_idx, p = _u2(d, p)
                _, p = _u2(d, p)  # descriptor
                if collect and name_idx:
                    name = self._utf8(name_idx)
                    if name and not name.startswith("<"):
                        self.methods.add(name)
                p = self._skip_attributes(p)
            return p

        pos = skip_members(pos)  # fields
        pos = skip_members(pos, collect=True)  # methods
        pos = self._skip_attributes(pos)

    def _skip_attributes(self, pos: int) -> int:
        d = self.data
        acount, pos = _u2(d, pos)
        for _ in range(acount):
            name_idx, pos = _u2(d, pos)
            length, pos = _u4(d, pos)
            name = self._utf8(name_idx)
            end = pos + length
            if name in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
                self._parse_annotations(pos, end)
            pos = end
        return pos

    def _parse_annotations(self, pos: int, end: int) -> None:
        d = self.data
        try:
            n, p = _u2(d, pos)
            for _ in range(n):
                type_idx, p = _u2(d, p)
                desc = self._utf8(type_idx)
                if desc.startswith("L") and desc.endswith(";"):
                    self.annotations.add(desc[1:-1].replace("/", ".").replace("$", "."))
                pairs, p = _u2(d, p)
                for _ in range(pairs):
                    _, p = _u2(d, p)
                    p = self._skip_element_value(p)
        except (struct.error, IndexError):
            return

    def _skip_element_value(self, p: int) -> int:
        d = self.data
        tag = chr(d[p]); p += 1
        if tag in ("B", "C", "D", "F", "I", "J", "S", "Z", "s"):
            ci, p = _u2(d, p)
            if tag == "s":
                value = self._utf8(ci)
                if 0 < len(value) <= 160:
                    self.strings.add(value)
        elif tag == "e":
            p += 4
        elif tag == "c":
            p += 2
        elif tag == "@":
            p = self._parse_single_annotation(p)
        elif tag == "[":
            n, p = _u2(d, p)
            for _ in range(n):
                p = self._skip_element_value(p)
        return p

    def _parse_single_annotation(self, p: int) -> int:
        d = self.data
        type_idx, p = _u2(d, p)
        desc = self._utf8(type_idx)
        if desc.startswith("L") and desc.endswith(";"):
            self.annotations.add(desc[1:-1].replace("/", ".").replace("$", "."))
        pairs, p = _u2(d, p)
        for _ in range(pairs):
            _, p = _u2(d, p)
            p = self._skip_element_value(p)
        return p


def parse_class_bytes(data: bytes) -> Dict[str, Any]:
    cf = ClassFile(data)
    name = cf.this_class or "unknown"
    path = name.replace(".", "/") + ".class"
    prefixes = sorted({t.rsplit(".", 1)[0] + "." for t in cf.class_refs if "." in t})
    af = cf.access_flags
    if af & 0x4000:
        declared_kind = "enum"
    elif af & 0x2000:
        declared_kind = "annotation"
    elif af & 0x0200:
        declared_kind = "interface"
    elif cf.superclass == "java.lang.Record":
        declared_kind = "record"
    else:
        declared_kind = "class"
    symbols = empty_symbols()
    symbols.update({
        "annotations": sorted(cf.annotations),
        "superclasses": [cf.superclass] if cf.superclass else [],
        "interfaces": sorted(cf.interfaces),
        "import_prefixes": prefixes,
        "referenced_types": sorted(cf.class_refs),
        "constant_strings": sorted(cf.strings)[:400],
        "methods": sorted(cf.methods)[:200],
        "declared_kind": declared_kind,
    })
    flags = default_flags()
    short = name.rsplit(".", 1)[-1]
    flags["synthetic"] = "$$Lambda" in name or bool(re.search(r"\$\d+$", short)) and "access$" in "".join(cf.methods)
    flags["anonymous"] = bool(re.search(r"\$\d+$", short))
    flags["registration_id_count"] = len([s for s in cf.strings
                                          if re.fullmatch(r"[a-z0-9_]+:[a-z0-9_/]+", s)])
    return {"unit_id": "cls:" + name.replace(".", "/"), "path": path,
            "kind": "class", "symbols": symbols, "flags": flags}


def index_from_jar(jar_path: Path, artifact_id: str = "") -> Dict[str, Any]:
    units = []
    with zipfile.ZipFile(jar_path) as zf:
        names = sorted(n for n in zf.namelist() if n.endswith(".class") and not n.startswith("META-INF/versions/"))
        for name in names:
            try:
                units.append(parse_class_bytes(zf.read(name)))
            except (ValueError, struct.error, IndexError, KeyError):
                continue
    return {"schema_version": "0.1.0",
            "source": {"artifact_id": artifact_id or jar_path.name, "loader": "forge",
                       "loader_profile": "forge/1.20.1", "mc_version": "1.20.1",
                       "mapping_id": "mojmap+parchment", "checksum_sha256": None},
            "units": units}
