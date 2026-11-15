#!/usr/bin/env python3
"""translate-lua-statemachine 执行层：把 TaCZ 的 Lua 状态机翻译成平台无关 IR。

只做静态分析，不运行 Lua、不联网、不调用模型、不读取时间/随机数。
产物只写到 --out / --report 指定的路径（默认在 work/ 与 reports/ 下）。

用法：
  python skills/05-port/translate-lua-statemachine/run.py \
    --slice orchestration/m5-slice.json \
    --out work/m5/state-ir/ak47.json \
    --report reports/m5-state-ir.json

  python skills/05-port/translate-lua-statemachine/run.py \
    --slice orchestration/m5-slice.json --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# 常量表
# ---------------------------------------------------------------------------

LUA_KEYWORDS = frozenset(
    "and break do else elseif end false for function goto if in local nil not or "
    "repeat return then true until while".split()
)

# 已知的 Lua 标准库名字：出现时不记为 runtime-global
LUA_STDLIB = frozenset(
    "print tostring tonumber type pairs ipairs next select rawget rawset rawequal "
    "setmetatable getmetatable require pcall error assert unpack string table math "
    "os io load loadstring dofile collectgarbage xpcall".split()
)

# 状态命名空间 -> 稳定 id 前缀（规则写进 SKILL.md）
NAMESPACE_ALIASES = {
    "main_track_states": "main",
    "bolt_caught_states": "bolt",
    "over_heat_states": "heat",
    "fire_mode_state": "fire_mode",
    "movement_track_states": "movement",
    "ADS_states": "ads",
    "slide_states": "slide",
}

# 顶层单状态对象 -> 稳定 id
SINGLE_STATE_ALIASES = {
    "base_track_state": "base_track",
    "gun_kick_state": "gun_kick",
}

# unresolved 的稳定 reason 前缀（SKILL.md 中逐条解释）
R_RUNTIME_GLOBAL = "R1 runtime-global"
R_DYNAMIC_ANIM = "R2 dynamic-animation"
R_UNSUPPORTED_FLOW = "R3 unsupported-control-flow"
R_DELEGATION = "R4 unresolved-delegation"
R_REQUIRE = "R5 unresolved-require"
R_TARGET = "R6 unresolved-target"
R_LOCAL_HELPER = "R7 local-helper-side-effect"
R_TRACK = "R8 unresolved-track"
R_PARSE = "R9 parse-error"


class LuaSyntaxError(Exception):
    def __init__(self, message: str, line: int):
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


# ---------------------------------------------------------------------------
# 词法
# ---------------------------------------------------------------------------

class Token:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind: str, value, line: int):
        self.kind = kind          # name | keyword | number | string | op | eof
        self.value = value
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return f"Token({self.kind},{self.value!r},{self.line})"


_OP2 = ("..", "==", "~=", "<=", ">=", "::", "//")
_OP1 = "+-*/%^#<>=(){}[];:,."
_NUM_RE = re.compile(r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _decode_escapes(raw: str) -> str:
    out = []
    i = 0
    n = len(raw)
    simple = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b",
              "f": "\f", "v": "\v", "\\": "\\", '"': '"', "'": "'", "\n": "\n"}
    while i < n:
        ch = raw[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= n:
            break
        c = raw[i]
        if c in simple:
            out.append(simple[c])
            i += 1
        elif c == "z":
            i += 1
            while i < n and raw[i] in " \t\r\n":
                i += 1
        elif c == "x" and i + 2 < n:
            out.append(chr(int(raw[i + 1:i + 3], 16)))
            i += 3
        elif c.isdigit():
            j = i
            while j < n and j - i < 3 and raw[j].isdigit():
                j += 1
            out.append(chr(int(raw[i:j])))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def tokenize(src: str) -> list[Token]:
    toks: list[Token] = []
    i = 0
    n = len(src)
    line = 1
    while i < n:
        ch = src[i]
        if ch in " \t\r":
            i += 1
            continue
        if ch == "\n":
            line += 1
            i += 1
            continue
        # 注释
        if src.startswith("--", i):
            j = i + 2
            if j < n and src[j] == "[":
                long = _scan_long_bracket(src, j)
                if long is not None:
                    body, end = long
                    line += body.count("\n")
                    i = end
                    continue
            while i < n and src[i] != "\n":
                i += 1
            continue
        # 长字符串
        if ch == "[":
            long = _scan_long_bracket(src, i)
            if long is not None:
                body, end = long
                line += body.count("\n")
                toks.append(Token("string", body, line))
                i = end
                continue
        if ch in "\"'":
            quote = ch
            j = i + 1
            buf = []
            start_line = line
            while j < n:
                c = src[j]
                if c == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if c == quote:
                    break
                if c == "\n":
                    raise LuaSyntaxError("unterminated string", start_line)
                buf.append(c)
                j += 1
            if j >= n:
                raise LuaSyntaxError("unterminated string", start_line)
            toks.append(Token("string", _decode_escapes("".join(buf)), start_line))
            i = j + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            m = _NUM_RE.match(src, i)
            if not m:
                raise LuaSyntaxError(f"bad number at {ch!r}", line)
            toks.append(Token("number", m.group(0), line))
            i = m.end()
            continue
        if ch.isalpha() or ch == "_":
            m = _NAME_RE.match(src, i)
            word = m.group(0)
            kind = "keyword" if word in LUA_KEYWORDS else "name"
            toks.append(Token(kind, word, line))
            i = m.end()
            continue
        three = src[i:i + 3]
        if three == "...":
            toks.append(Token("op", "...", line))
            i += 3
            continue
        two = src[i:i + 2]
        if two in _OP2:
            toks.append(Token("op", two, line))
            i += 2
            continue
        if ch in _OP1:
            toks.append(Token("op", ch, line))
            i += 1
            continue
        raise LuaSyntaxError(f"unexpected character {ch!r}", line)
    toks.append(Token("eof", "<eof>", line))
    return toks


def _scan_long_bracket(src: str, i: int):
    """src[i] == '['；返回 (内容, 结束位置) 或 None。"""
    n = len(src)
    j = i + 1
    level = 0
    while j < n and src[j] == "=":
        level += 1
        j += 1
    if j >= n or src[j] != "[":
        return None
    start = j + 1
    close = "]" + "=" * level + "]"
    k = src.find(close, start)
    if k < 0:
        raise LuaSyntaxError("unterminated long bracket", 1)
    body = src[start:k]
    if body.startswith("\n"):
        body = body[1:]
    return body, k + len(close)


# ---------------------------------------------------------------------------
# 语法（递归下降 + 优先级爬升）
# ---------------------------------------------------------------------------

_BINPRI = {
    "or": (1, 1), "and": (2, 2),
    "<": (3, 3), ">": (3, 3), "<=": (3, 3), ">=": (3, 3), "~=": (3, 3), "==": (3, 3),
    "..": (5, 4),
    "+": (6, 6), "-": (6, 6),
    "*": (7, 7), "/": (7, 7), "//": (7, 7), "%": (7, 7),
    "^": (10, 9),
}
_UNARY_PRI = 8


class Parser:
    MAX_EXPR_DEPTH = 200

    def __init__(self, toks: list[Token]):
        self.toks = toks
        self.i = 0
        self.depth = 0

    # -- 基础 --
    def peek(self, k: int = 0) -> Token:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def advance(self) -> Token:
        t = self.toks[self.i]
        if t.kind != "eof":
            self.i += 1
        return t

    def at(self, value: str) -> bool:
        t = self.peek()
        return t.kind in ("keyword", "op") and t.value == value

    def accept(self, value: str) -> bool:
        if self.at(value):
            self.advance()
            return True
        return False

    def expect(self, value: str) -> Token:
        if not self.at(value):
            t = self.peek()
            raise LuaSyntaxError(f"expected {value!r}, got {t.value!r}", t.line)
        return self.advance()

    def expect_name(self) -> str:
        t = self.peek()
        if t.kind != "name":
            raise LuaSyntaxError(f"expected name, got {t.value!r}", t.line)
        self.advance()
        return t.value

    # -- 入口 --
    def parse_chunk(self) -> list:
        block = self.block()
        if self.peek().kind != "eof":
            t = self.peek()
            raise LuaSyntaxError(f"trailing token {t.value!r}", t.line)
        return block

    def block(self) -> list:
        stmts = []
        while True:
            t = self.peek()
            if t.kind == "eof":
                break
            if t.kind == "keyword" and t.value in ("end", "else", "elseif", "until"):
                break
            if self.accept(";"):
                continue
            stmt = self.statement()
            if stmt is not None:
                stmts.append(stmt)
            self.accept(";")
        return stmts

    def statement(self):
        t = self.peek()
        line = t.line
        if t.kind == "keyword":
            kw = t.value
            if kw == "local":
                self.advance()
                if self.at("function"):
                    self.advance()
                    name = self.expect_name()
                    fn = self.funcbody(line)
                    return ("local_function", name, fn)
                names = [self.expect_name()]
                while self.accept(","):
                    names.append(self.expect_name())
                exprs = self.explist() if self.accept("=") else []
                return ("local", names, exprs)
            if kw == "function":
                self.advance()
                path = [self.expect_name()]
                while self.accept("."):
                    path.append(self.expect_name())
                is_method = False
                if self.accept(":"):
                    path.append(self.expect_name())
                    is_method = True
                fn = self.funcbody(line)
                return ("function_def", path, is_method, fn)
            if kw == "if":
                self.advance()
                branches = []
                cond = self.expr()
                self.expect("then")
                branches.append((cond, self.block()))
                while self.at("elseif"):
                    self.advance()
                    c = self.expr()
                    self.expect("then")
                    branches.append((c, self.block()))
                else_block = None
                if self.at("else"):
                    self.advance()
                    else_block = self.block()
                self.expect("end")
                return ("if", branches, else_block)
            if kw == "while":
                self.advance()
                cond = self.expr()
                self.expect("do")
                body = self.block()
                self.expect("end")
                return ("while", cond, body)
            if kw == "repeat":
                self.advance()
                body = self.block()
                self.expect("until")
                cond = self.expr()
                return ("repeat", body, cond)
            if kw == "for":
                self.advance()
                first = self.expect_name()
                if self.accept("="):
                    start = self.expr()
                    self.expect(",")
                    stop = self.expr()
                    step = self.expr() if self.accept(",") else None
                    self.expect("do")
                    body = self.block()
                    self.expect("end")
                    return ("for_num", first, start, stop, step, body)
                names = [first]
                while self.accept(","):
                    names.append(self.expect_name())
                self.expect("in")
                exprs = self.explist()
                self.expect("do")
                body = self.block()
                self.expect("end")
                return ("for_in", names, exprs, body)
            if kw == "do":
                self.advance()
                body = self.block()
                self.expect("end")
                return ("do", body)
            if kw == "return":
                self.advance()
                if self.peek().kind in ("eof",) or self.at("end") or self.at("else") \
                        or self.at("elseif") or self.at("until") or self.at(";"):
                    return ("return", [], line)
                exprs = self.explist()
                self.accept(";")
                return ("return", exprs, line)
            if kw == "break":
                self.advance()
                return ("break", line)
            if kw in ("goto", "in"):
                raise LuaSyntaxError(f"unsupported statement {kw!r}", line)
        # 表达式语句 / 赋值
        prefix = self.suffixedexp()
        if self.at("=") or self.at(","):
            targets = [prefix]
            while self.accept(","):
                targets.append(self.suffixedexp())
            self.expect("=")
            values = self.explist()
            return ("assign", targets, values, line)
        if prefix[0] not in ("call", "methodcall"):
            raise LuaSyntaxError("expression is not a statement", line)
        return ("call_stmt", prefix)

    def funcbody(self, line: int):
        self.expect("(")
        params: list[str] = []
        is_vararg = False
        if not self.at(")"):
            while True:
                if self.accept("..."):
                    is_vararg = True
                    break
                params.append(self.expect_name())
                if not self.accept(","):
                    break
        self.expect(")")
        body = self.block()
        self.expect("end")
        return ("function", params, is_vararg, body, line)

    def explist(self) -> list:
        exprs = [self.expr()]
        while self.accept(","):
            exprs.append(self.expr())
        return exprs

    def expr(self, limit: int = 0):
        self.depth += 1
        if self.depth > self.MAX_EXPR_DEPTH:
            raise LuaSyntaxError("expression nesting exceeds 200", self.peek().line)
        try:
            return self._expr(limit)
        finally:
            self.depth -= 1

    def _expr(self, limit: int = 0):
        t = self.peek()
        if (t.kind == "keyword" and t.value == "not") or (t.kind == "op" and t.value in ("-", "#")):
            self.advance()
            operand = self.expr(_UNARY_PRI)
            left = ("un", t.value, operand)
        else:
            left = self.simpleexp()
        while True:
            op_tok = self.peek()
            op = op_tok.value
            if op_tok.kind not in ("op", "keyword") or op not in _BINPRI:
                break
            lpri, rpri = _BINPRI[op]
            if lpri <= limit:
                break
            self.advance()
            right = self.expr(rpri)
            left = ("bin", op, left, right)
        return left

    def simpleexp(self):
        t = self.peek()
        if t.kind == "number":
            self.advance()
            return ("number", t.value)
        if t.kind == "string":
            self.advance()
            return ("string", t.value)
        if t.kind == "keyword":
            if t.value == "nil":
                self.advance()
                return ("nil",)
            if t.value == "true":
                self.advance()
                return ("true",)
            if t.value == "false":
                self.advance()
                return ("false",)
            if t.value == "function":
                self.advance()
                return self.funcbody(t.line)
        if t.kind == "op" and t.value == "...":
            self.advance()
            return ("vararg",)
        if t.kind == "op" and t.value == "{":
            return self.table()
        return self.suffixedexp()

    def primaryexp(self):
        t = self.peek()
        if t.kind == "name":
            self.advance()
            return ("name", t.value)
        if t.kind == "op" and t.value == "(":
            self.advance()
            e = self.expr()
            self.expect(")")
            return ("paren", e)
        raise LuaSyntaxError(f"unexpected token {t.value!r}", t.line)

    def suffixedexp(self):
        e = self.primaryexp()
        while True:
            t = self.peek()
            if t.kind == "op" and t.value == ".":
                self.advance()
                e = ("index", e, ("name", self.expect_name()))
            elif t.kind == "op" and t.value == "[":
                self.advance()
                k = self.expr()
                self.expect("]")
                e = ("index", e, k)
            elif t.kind == "op" and t.value == ":":
                self.advance()
                name = self.expect_name()
                args = self.callargs()
                e = ("methodcall", e, name, args)
            elif (t.kind == "op" and t.value in ("(", "{")) or t.kind == "string":
                args = self.callargs()
                e = ("call", e, args)
            else:
                break
        return e

    def callargs(self) -> list:
        t = self.peek()
        if t.kind == "string":
            self.advance()
            return [("string", t.value)]
        if t.kind == "op" and t.value == "{":
            return [self.table()]
        self.expect("(")
        if self.at(")"):
            self.advance()
            return []
        args = self.explist()
        self.expect(")")
        return args

    def table(self) -> tuple:
        self.expect("{")
        fields = []
        while not self.at("}"):
            if self.at("["):
                self.advance()
                k = self.expr()
                self.expect("]")
                self.expect("=")
                fields.append(("keyed", k, self.expr()))
            elif self.peek().kind == "name" and self.peek(1).kind == "op" and self.peek(1).value == "=":
                name = self.expect_name()
                self.expect("=")
                fields.append(("named", name, self.expr()))
            else:
                fields.append(("pos", self.expr()))
            if not (self.accept(",") or self.accept(";")):
                break
        self.expect("}")
        return ("table", fields)


def parse_lua(src: str) -> list:
    return Parser(tokenize(src)).parse_chunk()


# ---------------------------------------------------------------------------
# 求值模型（只覆盖状态机脚本用到的 Lua 子集）
# ---------------------------------------------------------------------------

class Scalar:
    __slots__ = ("value", "raw")

    def __init__(self, value, raw=None):
        self.value = value
        self.raw = raw

    def __repr__(self):  # pragma: no cover
        return f"Scalar({self.value!r})"


class Table:
    __slots__ = ("path", "fields", "items", "meta", "module")

    def __init__(self, path: str, module, fields=None, items=None, meta=None):
        self.path = path
        self.module = module
        self.fields: dict[str, object] = fields or {}
        self.items: list = items or []
        self.meta = meta

    def __repr__(self):  # pragma: no cover
        return f"Table({self.path})"


class Func:
    __slots__ = ("name", "params", "is_vararg", "body", "module", "line")

    def __init__(self, name, params, is_vararg, body, module, line):
        self.name = name
        self.params = params
        self.is_vararg = is_vararg
        self.body = body
        self.module = module
        self.line = line

    def __repr__(self):  # pragma: no cover
        return f"Func({self.name})"


class Opaque:
    __slots__ = ("text", "module")

    def __init__(self, text, module=None):
        self.text = text
        self.module = module

    def __repr__(self):  # pragma: no cover
        return f"Opaque({self.text})"


def table_field(tbl: Table, name: str):
    """沿 __index 链查字段。"""
    seen = set()
    cur = tbl
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if name in cur.fields:
            return cur.fields[name]
        cur = cur.meta
    return None


def table_field_names(tbl: Table) -> list[str]:
    """自身 + 继承链上的字段名，自身优先。"""
    names: list[str] = []
    seen = set()
    cur = tbl
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        for k in cur.fields:
            if k not in names:
                names.append(k)
        cur = cur.meta
    return names


class Module:
    def __init__(self, require_id: str, file_rel: str, src: str):
        self.require_id = require_id
        self.file_rel = file_rel
        self.src = src
        self.stmts: list = []
        self.bindings: dict[str, object] = {}
        self.export = None
        self.deps: list[str] = []
        self.unresolved: list[dict] = []
        self.parse_error: str | None = None


class Loader:
    """按 require id 加载脚本；require 的 `ns_path` 命名反解成文件路径。"""

    def __init__(self, scripts_dir: Path):
        self.dir = scripts_dir
        self.cache: dict[str, Module] = {}

    def candidate_paths(self, require_id: str) -> list[Path]:
        parts = require_id.split("_")
        cands: list[Path] = []
        for i in range(len(parts)):
            rest = parts[i:]
            for joiner in ("_", "/"):
                name = joiner.join(rest)
                p = self.dir / f"{name}.lua"
                if p not in cands:
                    cands.append(p)
        return cands

    def resolve(self, require_id: str) -> Path | None:
        for p in self.candidate_paths(require_id):
            if p.is_file():
                return p
        return None

    def load(self, require_id: str) -> Module | None:
        if require_id in self.cache:
            return self.cache[require_id]
        path = self.resolve(require_id)
        if path is None:
            return None
        file_rel = path.name
        src = path.read_text(encoding="utf-8", errors="replace")
        mod = Module(require_id, file_rel, src)
        self.cache[require_id] = mod
        try:
            mod.stmts = parse_lua(src)
        except LuaSyntaxError as exc:
            mod.parse_error = str(exc)
            mod.unresolved.append({"file": file_rel, "symbol": "<chunk>", "reason": f"{R_PARSE}: {exc}"})
            return mod
        _ModuleCtx(self, mod).run()
        return mod


class _ModuleCtx:
    """执行模块顶层语句，只建立表结构/函数/别名，不做控制流求值。"""

    def __init__(self, loader: Loader, mod: Module):
        self.loader = loader
        self.mod = mod
        self.vars: dict[str, object] = dict(mod.bindings)

    def run(self) -> None:
        for stmt in self.mod.stmts:
            self.exec_stmt(stmt)
        if self.mod.export is None:
            self.mod.export = self.vars.get("M")
        self.mod.bindings = self.vars

    # -- 语句 --
    def exec_stmt(self, stmt) -> None:
        kind = stmt[0]
        if kind == "local":
            names, exprs = stmt[1], stmt[2]
            for idx, name in enumerate(names):
                if idx < len(exprs):
                    self.vars[name] = self.eval(exprs[idx], name)
                else:
                    self.vars[name] = Scalar(None)
        elif kind == "local_function":
            name, fn_node = stmt[1], stmt[2]
            self.vars[name] = self.make_func(name, fn_node)
        elif kind == "function_def":
            path, is_method, fn_node = stmt[1], stmt[2], stmt[3]
            parent = self.vars.get(path[0])
            if len(path) == 1:
                # function M() ... 覆盖绑定
                self.vars[path[0]] = self.make_func(path[0], fn_node)
                return
            if not isinstance(parent, Table):
                self.note(R_TARGET, ".".join(path),
                          "function target root is not a known table")
                return
            node = parent
            for seg in path[1:-1]:
                nxt = table_field(node, seg)
                if not isinstance(nxt, Table):
                    self.note(R_TARGET, ".".join(path), f"path segment {seg!r} is not a table")
                    return
                node = nxt
            leaf = path[-1]
            fn = self.make_func(".".join(path), fn_node)
            if is_method:
                fn.params = ["self"] + list(fn.params)
            node.fields[leaf] = fn
        elif kind == "assign":
            for target, value in zip(stmt[1], stmt[2]):
                self.exec_assign(target, value)
        elif kind == "return":
            if stmt[1]:
                vals = [self.eval(e) for e in stmt[1]]
                self.mod.export = vals[0] if len(vals) == 1 else vals
            else:
                self.mod.export = Scalar(None)
        elif kind in ("if", "while", "repeat", "for_num", "for_in", "do"):
            self.note(R_UNSUPPORTED_FLOW, kind,
                      "control flow at module scope is not evaluated")
        # call_stmt / break: 顶层副作用不影响 IR

    def exec_assign(self, target, value_expr) -> None:
        value = self.eval(value_expr)
        if target[0] == "name":
            self.vars[target[1]] = value
            return
        if target[0] != "index":
            return
        chain = []
        node = target
        while node[0] == "index":
            key = node[2]
            if key[0] != "name":
                return
            chain.append(key[1])
            node = node[1]
        if node[0] != "name":
            return
        base = self.vars.get(node[1])
        if not isinstance(base, Table):
            return
        chain.reverse()
        cur = base
        for seg in chain[:-1]:
            nxt = table_field(cur, seg)
            if not isinstance(nxt, Table):
                return
            cur = nxt
        cur.fields[chain[-1]] = value

    # -- 表达式 --
    def make_func(self, name, fn_node) -> Func:
        _, params, is_vararg, body, line = fn_node
        return Func(name, list(params), is_vararg, body, self.mod, line)

    def eval(self, node, path_hint: str | None = None):
        kind = node[0]
        if kind == "number":
            raw = node[1]
            try:
                val = int(raw, 0) if raw.lower().startswith("0x") else float(raw)
            except ValueError:
                val = 0.0
            return Scalar(val, raw)
        if kind == "string":
            return Scalar(node[1])
        if kind == "nil":
            return Scalar(None)
        if kind == "true":
            return Scalar(True)
        if kind == "false":
            return Scalar(False)
        if kind == "name":
            return self.vars.get(node[1], Opaque(node[1], self.mod))
        if kind == "paren":
            return self.eval(node[1], path_hint)
        if kind == "index":
            base = self.eval(node[1])
            key = node[2]
            if key[0] != "name":
                return Opaque("<dynamic index>", self.mod)
            if isinstance(base, Table):
                got = table_field(base, key[1])
                if got is None:
                    return Opaque(f"{base.path}.{key[1]}", self.mod)
                return got
            if isinstance(base, ModuleRef):
                target = base.module.export
                if isinstance(target, Table):
                    got = table_field(target, key[1])
                    if got is not None:
                        return got
                return Opaque(f"<module {base.require_id}>.{key[1]}", self.mod)
            return Opaque(_render_raw(node), self.mod)
        if kind == "table":
            return self.eval_table(node, path_hint or "<anon>")
        if kind == "function":
            return self.make_func(path_hint or "<anon>", node)
        if kind == "call":
            return self.eval_call(node, path_hint)
        if kind == "methodcall":
            return Opaque(_render_raw(node), self.mod)
        if kind == "bin":
            left = self.eval(node[2])
            right = self.eval(node[3])
            if isinstance(left, Scalar) and isinstance(right, Scalar):
                return _fold_bin(node[1], left, right)
            return Opaque(_render_raw(node), self.mod)
        if kind == "un":
            inner = self.eval(node[2])
            if isinstance(inner, Scalar):
                if node[1] == "not":
                    return Scalar(not _truthy(inner))
                if node[1] == "-" and isinstance(inner.value, (int, float)):
                    return Scalar(-inner.value)
            return Opaque(_render_raw(node), self.mod)
        return Opaque(_render_raw(node), self.mod)

    def eval_table(self, node, path: str) -> Table:
        tbl = Table(path, self.mod)
        for field in node[1]:
            if field[0] == "pos":
                tbl.items.append(self.eval(field[1], f"{path}[{len(tbl.items) + 1}]"))
            elif field[0] == "named":
                tbl.fields[field[1]] = self.eval(field[2], f"{path}.{field[1]}")
            else:
                key_node = field[1]
                if key_node[0] == "string":
                    tbl.fields[key_node[1]] = self.eval(field[2], f"{path}.{key_node[1]}")
                else:
                    self.note(R_UNSUPPORTED_FLOW, _render_raw(key_node),
                              "dynamic table key is not evaluated")
        return tbl

    def eval_call(self, node, path_hint):
        fn_expr, args = node[1], node[2]
        if fn_expr[0] == "name" and fn_expr[1] == "require":
            if len(args) == 1 and args[0][0] == "string":
                rid = args[0][1]
                self.mod.deps.append(rid)
                dep = self.loader.load(rid)
                if dep is None:
                    self.note(R_REQUIRE, rid, "require target not found under scripts dir")
                    return Opaque(f"require({rid})", self.mod)
                if dep.parse_error:
                    self.note(R_REQUIRE, rid, f"required module failed to parse: {dep.parse_error}")
                    return Opaque(f"require({rid})", self.mod)
                return ModuleRef(rid, dep)
            self.note(R_REQUIRE, "<require>", "require with non-literal argument")
            return Opaque("require(?)", self.mod)
        if fn_expr[0] == "name" and fn_expr[1] == "setmetatable":
            base = self.eval(args[0], path_hint) if args else None
            meta = self.eval(args[1]) if len(args) > 1 else None
            if isinstance(meta, ModuleRef):
                meta = meta.module.export
            if isinstance(base, Table) and isinstance(meta, Table):
                idx = meta.fields.get("__index")
                if isinstance(idx, ModuleRef):
                    idx = idx.module.export
                if isinstance(idx, Table):
                    base.meta = idx
                elif isinstance(idx, Func):
                    self.note(R_LOCAL_HELPER, "__index",
                              "function-valued __index is not statically resolved")
                elif idx is not None:
                    pass
            elif isinstance(base, Table):
                self.note(R_LOCAL_HELPER, "setmetatable",
                          "metatable is not a table literal; inheritance link not recorded")
            return base if base is not None else Opaque("setmetatable(?)", self.mod)
        return Opaque(_render_raw(node), self.mod)

    def note(self, reason: str, symbol: str, detail: str) -> None:
        self.mod.unresolved.append({
            "file": self.mod.file_rel,
            "symbol": symbol,
            "reason": f"{reason}: {detail}",
        })


class ModuleRef:
    __slots__ = ("require_id", "module")

    def __init__(self, require_id: str, module: Module):
        self.require_id = require_id
        self.module = module


def _truthy(scalar: Scalar) -> bool:
    return bool(scalar.value)


def _fold_bin(op: str, left: Scalar, right: Scalar):
    lv, rv = left.value, right.value
    try:
        if op == "..":
            return Scalar(f"{_lua_str(lv)}{_lua_str(rv)}")
        if op in ("+", "-", "*", "/", "%", "^", "//"):
            if not isinstance(lv, (int, float)) or not isinstance(rv, (int, float)):
                return Opaque(f"{lv}{op}{rv}")
            if op == "+":
                return Scalar(lv + rv)
            if op == "-":
                return Scalar(lv - rv)
            if op == "*":
                return Scalar(lv * rv)
            if op == "/":
                return Scalar(lv / rv if rv else 0.0)
            if op == "%":
                return Scalar(lv % rv if rv else 0.0)
            if op == "^":
                return Scalar(lv ** rv)
            return Scalar(lv // rv if rv else 0.0)
        if op == "==":
            return Scalar(lv == rv)
        if op == "~=":
            return Scalar(lv != rv)
        if op in ("<", ">", "<=", ">="):
            return Scalar({"<": lv < rv, ">": lv > rv,
                           "<=": lv <= rv, ">=": lv >= rv}[op])
        if op == "and":
            return right if _truthy(left) else left
        if op == "or":
            return left if _truthy(left) else right
    except TypeError:
        return Opaque(f"{lv}{op}{rv}")
    return Opaque(f"{lv}{op}{rv}")


def _lua_str(value) -> str:
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


# ---------------------------------------------------------------------------
# 表达式渲染（IR 里所有字符串都由此产生，保证确定性）
# ---------------------------------------------------------------------------

def _snake(name: str) -> str:
    out = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return re.sub(r"_+", "_", out).strip("_")


def _strip_getter(name: str) -> str:
    s = _snake(name)
    return s[4:] if s.startswith("get_") else s


def _render_raw(node) -> str:
    kind = node[0]
    if kind == "name":
        return node[1]
    if kind == "number":
        return node[1]
    if kind == "string":
        return json.dumps(node[1], ensure_ascii=False)
    if kind == "nil":
        return "nil"
    if kind == "true":
        return "true"
    if kind == "false":
        return "false"
    if kind == "paren":
        return f"({_render_raw(node[1])})"
    if kind == "index":
        return f"{_render_raw(node[1])}.{_render_raw(node[2])}"
    if kind == "call":
        return f"{_render_raw(node[1])}({', '.join(_render_raw(a) for a in node[2])})"
    if kind == "methodcall":
        return f"{_render_raw(node[1])}:{node[2]}({', '.join(_render_raw(a) for a in node[3])})"
    if kind == "bin":
        return f"{_render_raw(node[2])} {node[1]} {_render_raw(node[3])}"
    if kind == "un":
        return f"{node[1]} {_render_raw(node[2])}"
    if kind == "table":
        return "{...}"
    if kind == "function":
        return "function"
    return "<expr>"


class ExprNormalizer:
    """把 Lua 条件表达式归一化成平台无关文本（IR 只出现这一种写法）。"""

    def __init__(self, id_of, aliases: dict[str, str], predicates: dict[str, tuple] | None = None):
        self.id_of = id_of
        self.aliases = aliases
        self.predicates = predicates or {}
        self._depth = 0

    def norm(self, node) -> str:
        return self._n(node)

    def _n(self, node) -> str:
        kind = node[0]
        if kind == "bin":
            op = node[1]
            if op == "and":
                return f"{self._n(node[2])} && {self._n(node[3])}"
            if op == "or":
                return f"{self._n(node[2])} || {self._n(node[3])}"
            if op == "~=":
                return f"{self._n(node[2])} != {self._n(node[3])}"
            if op == "==":
                return f"{self._n(node[2])} == {self._n(node[3])}"
            if op == "..":
                return f"{self._n(node[2])} .. {self._n(node[3])}"
            return f"{self._n(node[2])} {op} {self._n(node[3])}"
        if kind == "un":
            if node[1] == "not":
                return f"!{self._wrap(self._n(node[2]))}"
            return f"-{self._wrap(self._n(node[2]))}"
        if kind == "paren":
            inner = node[1]
            text = self._n(inner)
            return f"({text})" if inner[0] in ("bin", "un") else text
        if kind == "name":
            return node[1]
        if kind == "string":
            return json.dumps(node[1], ensure_ascii=False)
        if kind == "number":
            return node[1]
        if kind == "nil":
            return "null"
        if kind == "true":
            return "true"
        if kind == "false":
            return "false"
        if kind == "methodcall":
            obj, name, args = node[1], node[2], node[3]
            if obj[0] == "name" and obj[1] in ("context", "this", "self"):
                if name in ("getTrack", "findIdleTrack") and len(args) >= 2:
                    return f"track:{self._track_sym(args[-1] if name == 'getTrack' else args[0])}"
                if not args:
                    return _strip_getter(name)
                return f"{_strip_getter(name)}({', '.join(self._n(a) for a in args)})"
            return f"{self._n(obj)}:{_snake(name)}({', '.join(self._n(a) for a in args)})"
        if kind == "call":
            fn = node[1]
            if fn[0] == "name":
                pred = self.predicates.get(fn[1])
                if pred is not None and self._depth < 2:
                    self._depth += 1
                    try:
                        return self._n(pred)
                    finally:
                        self._depth -= 1
                rest = [a for a in node[2] if a[0] != "name" or a[1] != "context"]
                if not rest:
                    return _strip_getter(fn[1])
                return f"{_strip_getter(fn[1])}({', '.join(self._n(a) for a in rest)})"
            return f"{self._n(fn)}({', '.join(self._n(a) for a in node[2])})"
        if kind == "index":
            chain = self._chain(node)
            if chain:
                if chain[0] in ("this", "self"):
                    chain = chain[1:]
                head = self.aliases.get(chain[0], chain[0])
                return ".".join([head] + chain[1:])
            return _render_raw(node)
        return _render_raw(node)

    def _chain(self, node):
        parts: list[str] = []
        cur = node
        while cur[0] == "index":
            key = cur[2]
            if key[0] != "name":
                return None
            parts.append(key[1])
            cur = cur[1]
        if cur[0] != "name":
            return None
        parts.append(cur[1])
        parts.reverse()
        return parts

    @staticmethod
    def _wrap(text: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_.:]+|!?[A-Za-z0-9_.:]+\(.*\)", text):
            return text
        return f"({text})"

    @staticmethod
    def _track_sym(node) -> str:
        if node[0] == "name":
            return node[1]
        if node[0] == "string":
            return node[1]
        if node[0] == "number":
            return node[1]
        return _render_raw(node)


def guard_kind(expr: str) -> str:
    e = expr.lower()
    if "ammo" in e or "bullet" in e:
        return "ammo"
    if "fire_mode" in e:
        return "fire_mode"
    if "mag" in e or "extent" in e or "attachment" in e or "scope" in e or "muzzle" in e:
        return "attachment"
    if any(k in e for k in ("is_stopped", "is_holding", "allow_run_overlay", "aiming_progress",
                            "should_slide", "is_aiming", "on_ground", "is_input_",
                            "charging", "timestamp", "mode", "slide")):
        return "state"
    return "other"


# ---------------------------------------------------------------------------
# 状态机分析
# ---------------------------------------------------------------------------

class Analyzer:
    def __init__(self, scripts_dir: Path, gun: str):
        self.dir = scripts_dir
        self.gun = gun
        self.loader = Loader(scripts_dir)
        self.unresolved: list[dict] = []
        self.unresolved_seen: set[tuple[str, str, str]] = set()
        self.guards: list[dict] = []
        self.guard_index: dict[str, str] = {}
        self.transitions_total = 0
        self.extra_tracks: set[str] = set()
        self.delegated_fallbacks = 0
        self.condition_driven = 0
        self.inputs_unreferenced: list[str] = []
        self.on_distribution: dict[str, int] = {}
        self.predicates: dict[str, tuple] = {}
        self.M = None
        self.gun_mod = None
        self.id_map: dict[str, Table] = {}
        self.obj_id: dict[int, str] = {}

    # -- 公共 --
    def note(self, file_rel: str, reason: str, symbol: str, detail: str = "") -> None:
        reason_text = f"{reason}: {detail}" if detail else reason
        key = (file_rel, symbol, reason_text)
        if key in self.unresolved_seen:
            return
        self.unresolved_seen.add(key)
        self.unresolved.append({"file": file_rel, "symbol": symbol, "reason": reason_text})

    def run(self) -> dict:
        gun_id = f"{self.gun}_state_machine"
        gun_mod = self.loader.load(gun_id)
        if gun_mod is None or gun_mod.parse_error or not isinstance(gun_mod.export, Table):
            detail = "module not found" if gun_mod is None else (gun_mod.parse_error or "export is not a table")
            self.note(f"{gun_id}.lua", R_PARSE, gun_id, detail)
            return self.empty_ir()

        for item in gun_mod.unresolved:
            self.note(item["file"], item["reason"].split(":")[0], item["symbol"],
                      item["reason"].split(":", 1)[1].strip() if ":" in item["reason"] else "")
        for dep in self.dep_closure(gun_mod):
            for item in dep.unresolved:
                self.note(item["file"], item["reason"].split(":")[0], item["symbol"],
                          item["reason"].split(":", 1)[1].strip() if ":" in item["reason"] else "")

        self.M = gun_mod.export
        self.gun_mod = gun_mod
        self.id_map = {}
        self.obj_id = {}
        self._build_id_map()

        seeds = self._seed_states()
        states = self._expand_states(seeds)

        self._collect_predicates([gun_mod] + self.dep_closure(gun_mod))
        self.norm = ExprNormalizer(None, dict(NAMESPACE_ALIASES), self.predicates)
        state_nodes = []
        for st in states:
            state_nodes.append(self._state_node(st))

        self._finalize_guards(state_nodes)
        self.excluded_states = sorted(set(self.id_map) - {st["id"] for st in state_nodes})
        # inputs = 转移里实际出现的输入名（"*" 是条件驱动标记，不是输入名）
        inputs = sorted({tr["on"] for st in state_nodes for tr in st["transitions"]
                         if tr["on"] != "*"})
        declared = self._collect_inputs(gun_mod)
        self.inputs_unreferenced = sorted(set(declared) - set(inputs))
        self.on_distribution = {}
        for st in state_nodes:
            for tr in st["transitions"]:
                self.on_distribution[tr["on"]] = self.on_distribution.get(tr["on"], 0) + 1
        self.condition_driven = self.on_distribution.get("*", 0)
        tracks = sorted({t for s in state_nodes for e in s["entry"] if "track" in e
                         for t in [e["track"]]} | self.extra_tracks)
        transitions_total = sum(len(s["transitions"]) for s in state_nodes)

        ir = {
            "schema_version": "0.1.0",
            "gun": self.gun,
            "source_files": sorted({m.file_rel for m in self.dep_closure(gun_mod)} | {gun_mod.file_rel}),
            "inheritance": self._inheritance_chain(gun_mod),
            "tracks": tracks,
            "inputs": inputs,
            "guards": sorted(self.guards, key=lambda g: g["id"]),
            "states": state_nodes,
            "counts": {
                "states": len(state_nodes),
                "transitions": transitions_total,
                "inputs": len(inputs),
                "guards": len(self.guards),
            },
            "unresolved": sorted(self.unresolved, key=lambda u: (u["file"], u["symbol"], u["reason"])),
        }
        self._scan_runtime_globals(gun_mod)
        ir["unresolved"] = sorted(self.unresolved, key=lambda u: (u["file"], u["symbol"], u["reason"]))
        return ir

    def _finalize_guards(self, states: list[dict]) -> None:
        """只保留被引用的守卫，并按首次出现顺序重编号（g001..）。"""
        remap: dict[str, str] = {}
        for st in states:
            for tr in st["transitions"]:
                gid = tr["guard"]
                if gid and gid not in remap:
                    remap[gid] = f"g{len(remap) + 1:03d}"
        by_id = {g["id"]: g for g in self.guards}
        new_guards = []
        for old_id, new_id in remap.items():
            g = dict(by_id[old_id])
            g["id"] = new_id
            new_guards.append(g)
        for st in states:
            for tr in st["transitions"]:
                if tr["guard"]:
                    tr["guard"] = remap[tr["guard"]]
        self.guards = new_guards

    def empty_ir(self) -> dict:
        return {
            "schema_version": "0.1.0", "gun": self.gun, "source_files": [],
            "inheritance": [], "tracks": [], "inputs": [], "guards": [], "states": [],
            "counts": {"states": 0, "transitions": 0, "inputs": 0, "guards": 0},
            "unresolved": sorted(self.unresolved, key=lambda u: (u["file"], u["symbol"], u["reason"])),
        }

    # -- require 链 --
    def dep_closure(self, mod: Module) -> list[Module]:
        out: list[Module] = []
        seen: set[str] = set()

        def walk(m: Module) -> None:
            for rid in m.deps:
                if rid in seen:
                    continue
                dep = self.loader.cache.get(rid)
                if dep is None:
                    continue
                seen.add(rid)
                walk(dep)
                out.append(dep)

        walk(mod)
        return out

    def _inheritance_chain(self, gun_mod: Module) -> list[str]:
        chain = [m.require_id for m in self.dep_closure(gun_mod)]
        chain.append(gun_mod.require_id)
        return chain

    # -- 稳定 id --
    def _build_id_map(self) -> None:
        for ns in sorted(NAMESPACE_ALIASES):
            alias = NAMESPACE_ALIASES[ns]
            tbl = table_field(self.M, ns)
            if not isinstance(tbl, Table):
                continue
            for name in sorted(table_field_names(tbl)):
                val = table_field(tbl, name)
                if not isinstance(val, Table):
                    continue
                sid = "final" if _is_final(val) else f"{alias}.{name}"
                self.id_map.setdefault(sid, val)
                self.obj_id.setdefault(id(val), sid)
        for name in sorted(SINGLE_STATE_ALIASES):
            val = table_field(self.M, name)
            if isinstance(val, Table):
                sid = SINGLE_STATE_ALIASES[name]
                self.id_map.setdefault(sid, val)
                self.obj_id.setdefault(id(val), sid)

    def id_for(self, val) -> str | None:
        if isinstance(val, Table):
            return self.obj_id.get(id(val))
        return None

    def _collect_predicates(self, modules: list[Module]) -> None:
        """单 `return <expr>` 的本地谓词函数 -> 内联到守卫表达式里。"""
        for mod in modules:
            for stmt in mod.stmts:
                if stmt[0] != "local_function":
                    continue
                name, fn_node = stmt[1], stmt[2]
                body = fn_node[3]
                if len(body) == 1 and body[0][0] == "return" and len(body[0][1]) == 1:
                    self.predicates.setdefault(name, body[0][1][0])

    # -- states() 种子 --
    def _seed_states(self) -> list[Table]:
        fn = table_field(self.M, "states")
        if not isinstance(fn, Func):
            self.note(self.gun_mod.file_rel, R_TARGET, "M:states",
                      "states() not found on exported module")
            return []
        seeds: list[Table] = []
        for stmt in fn.body:
            if stmt[0] == "return":
                vals = [self._eval_with_self(expr) for expr in stmt[1]]
                if len(vals) == 1 and isinstance(vals[0], Table) and vals[0].items:
                    vals = list(vals[0].items)  # `return { a, b, c }`
                for val in vals:
                    if isinstance(val, Table):
                        seeds.append(val)
                    else:
                        self.note(self.gun_mod.file_rel, R_TARGET, _render_raw(val) if isinstance(val, tuple) else str(val),
                                  "states() entry is not a resolvable table")
        if not seeds:
            self.note(self.gun_mod.file_rel, R_TARGET, "M:states", "states() returned no tables")
        return seeds

    def _eval_with_self(self, node):
        """在 `self = M` 的作用域下求值仅涉及路径的表达式。"""
        ctx = _ModuleCtx(self.loader, self.gun_mod)
        ctx.vars = dict(self.gun_mod.bindings)
        ctx.vars["self"] = self.M
        return ctx.eval(node)

    # -- 可达状态展开 --
    def _expand_states(self, seeds: list[Table]) -> list[Table]:
        order: list[Table] = []
        seen: set[int] = set()
        queue = list(seeds)
        while queue:
            tbl = queue.pop(0)
            if id(tbl) in seen:
                continue
            seen.add(id(tbl))
            if self.id_for(tbl) is None:
                # 未安装进 M 的匿名表：用一个稳定 fallback，避免静默丢弃
                sid = tbl.path.replace("M.", "").replace(".", "_") or "anonymous"
                self.id_map.setdefault(sid, tbl)
                self.obj_id.setdefault(id(tbl), sid)
                self.note(tbl.module.file_rel if tbl.module else "<anon>", R_TARGET,
                          tbl.path, "state table is not reachable from the exported module tree")
            order.append(tbl)
            for target in self._targets_of(tbl):
                if id(target) not in seen:
                    queue.append(target)
        order.sort(key=lambda t: self.id_for(t) or t.path)
        return order

    def _targets_of(self, tbl: Table) -> list[Table]:
        out: list[Table] = []
        for fn, _owner in self._transition_funcs(tbl):
            for target in _scan_returns(fn.body):
                val = self._resolve_target_node(target)
                if isinstance(val, Table):
                    out.append(val)
        return out

    def _resolve_target_node(self, node):
        ctx = _ModuleCtx(self.loader, self.gun_mod)
        ctx.vars = dict(self.gun_mod.bindings)
        ctx.vars["self"] = self.M
        ctx.vars["this"] = self.M
        try:
            return ctx.eval(node)
        except Exception:  # 静态求值失败不致命，交给 unresolved 记录
            return None

    # -- 函数查找 --
    def _transition_funcs(self, tbl: Table) -> list[tuple[Func, Table]]:
        """返回 [(transition 函数, 定义它的表)]；含显式委托链，按优先级排序。"""
        out: list[tuple[Func, Table]] = []
        seen: set[tuple[int, int]] = set()
        stack = [(tbl, False)]
        while stack:
            cur, from_delegation = stack.pop(0)
            fn = table_field(cur, "transition")
            if not isinstance(fn, Func):
                continue
            key = (id(cur), id(fn))
            if key in seen:
                continue
            seen.add(key)
            out.append((fn, cur))
            for call in _scan_delegations(fn.body):
                target = self._resolve_target_node(call[1][1])
                if isinstance(target, Table):
                    stack.append((target, True))
                else:
                    self.note(fn.module.file_rel if fn.module else "<anon>", R_DELEGATION,
                              _render_raw(call[1][1]), "delegated transition target is not resolvable")
        return out

    # -- 单个状态 --
    def _state_node(self, tbl: Table) -> dict:
        sid = self.id_for(tbl)
        mod = tbl.module
        entry = self._entry_of(tbl)
        transitions = self._transitions_of(tbl, sid)
        node = {
            "id": sid,
            "origin": "gun" if mod is self.gun_mod else "base",
            "source": mod.file_rel if mod else "<anon>",
            "entry": entry,
            "transitions": transitions,
        }
        self.transitions_total += len(transitions)
        return node

    def _entry_of(self, tbl: Table) -> list[dict]:
        calls: list[dict] = []
        seen: set[tuple] = set()
        for fname in ("entry", "update"):
            fn = table_field(tbl, fname)
            if not isinstance(fn, Func):
                continue
            local_tracks = _collect_track_locals(fn.body)
            for call in _scan_calls(fn.body, "runAnimation"):
                info = self._animation_info(call, local_tracks, fn.module)
                if info is None:
                    continue
                key = (info["animation"], info.get("track"))
                if key in seen:
                    continue
                seen.add(key)
                calls.append(info)
        return calls

    def _animation_info(self, call, local_tracks: dict[str, str], mod: Module | None):
        args = call[3]
        if not args:
            return None
        name_node = args[0]
        if name_node[0] != "string":
            self.note(mod.file_rel if mod else "<anon>", R_DYNAMIC_ANIM,
                      _render_raw(name_node), "animation name is not a string literal")
            return None
        track = _resolve_track(args[1], local_tracks) if len(args) > 1 else None
        if len(args) > 1 and track is None:
            self.note(mod.file_rel if mod else "<anon>", R_TRACK,
                      _render_raw(args[1]), "animation track is not statically resolvable")
        loop = False
        if len(args) > 2 and args[2][0] == "true":
            loop = True
        if len(args) > 3 and args[3][0] == "name" and args[3][1] == "LOOP":
            loop = True
        fade = _literal_number(args[-1]) if len(args) >= 2 else None
        info = {"animation": name_node[1], "loop": loop}
        if track:
            info["track"] = track
            self.extra_tracks.add(track)
        info["fade"] = fade
        return info

    def _transitions_of(self, tbl: Table, sid: str) -> list[dict]:
        funcs = self._transition_funcs(tbl)
        if not funcs:
            return []
        out: list[dict] = []
        handled: set[str] = set()
        for idx, (fn, owner) in enumerate(funcs):
            local_tracks = _collect_track_locals(fn.body)
            found: list[dict] = []
            _TransitionWalker(self, found, local_tracks, fn.module, sid).walk_block(
                fn.body, _TCtx(), _TAcc()
            )
            for tr in found:
                if idx > 0 and tr["on"] != "*" and tr["on"] in handled:
                    self.delegated_fallbacks += 1  # 被子状态机同名输入遮蔽，基类实现不可达
                    continue
                out.append(tr)
                if tr["on"] != "*":
                    handled.add(tr["on"])
        return _dedupe_transitions(out)

    # -- 输入 / 轨道 / 全局符号 --
    def _collect_inputs(self, gun_mod: Module) -> list[str]:
        names: set[str] = set()
        for mod in self.dep_closure(gun_mod) + [gun_mod]:
            if not isinstance(mod.export, Table):
                continue
            for field in table_field_names(mod.export):
                if re.fullmatch(r"INPUT_[A-Z0-9_]+", field):
                    names.add(field)
            for stmt in mod.stmts:
                _scan_input_refs(stmt, names)
        return sorted(names)

    def _scan_runtime_globals(self, gun_mod: Module) -> None:
        known = set(LUA_STDLIB)
        for mod in self.dep_closure(gun_mod) + [gun_mod]:
            for name in _collect_free_names(mod.stmts, known):
                if re.fullmatch(r"INPUT_[A-Z0-9_]+", name):
                    self.note(mod.file_rel, R_RUNTIME_GLOBAL, name,
                              "TaCZ runtime input constant; symbolic name kept verbatim")
                elif re.fullmatch(r"(PLAY_ONCE_[A-Z]+|LOOP|SEMI|AUTO|BURST)", name):
                    self.note(mod.file_rel, R_RUNTIME_GLOBAL, name,
                              "TaCZ runtime enum constant; numeric value unknown statically")
                else:
                    self.note(mod.file_rel, R_RUNTIME_GLOBAL, name,
                              "free name not bound in the loaded scripts")

    # -- 守卫注册 --
    def register_guard(self, exprs: list[str], file_rel: str, symbol: str) -> str:
        expr = " && ".join(exprs)
        if expr in self.guard_index:
            return self.guard_index[expr]
        gid = f"g{len(self.guards) + 1:03d}"
        self.guard_index[expr] = gid
        self.guards.append({
            "id": gid,
            "expr": expr,
            "kind": guard_kind(expr),
            "source": f"{file_rel}:{symbol}",
        })
        return gid

    def resolve_target(self, node, file_rel: str):
        """返回 (target_id, deleg, table)。"""
        if node is None:
            return "self", False, None
        if node[0] == "nil":
            return "self", False, None
        if node[0] == "call":
            fn = node[1]
            if fn[0] == "index" and fn[2][0] == "name" and fn[2][1] == "transition":
                return None, True, fn[1]
        val = self._resolve_target_node(node)
        if isinstance(val, Table):
            sid = self.id_for(val)
            if sid:
                return sid, False, val
            self.note(file_rel, R_TARGET, _render_raw(node),
                      "returned table has no stable state id")
            return "self", False, val
        if isinstance(val, Scalar):
            return "self", False, None
        self.note(file_rel, R_TARGET, _render_raw(node),
                  "return value is not a resolvable state table")
        return "self", False, None


def _is_final(tbl: Table) -> bool:
    val = tbl.fields.get("isfinal")
    return isinstance(val, Scalar) and isinstance(val.value, (int, float))


def _literal_number(node):
    if node[0] == "number":
        try:
            val = float(node[1])
        except ValueError:
            return None
        return int(val) if val == int(val) else val
    if node[0] == "un" and node[1] == "-":
        inner = _literal_number(node[2])
        return -inner if inner is not None else None
    return None


def _resolve_track(node, local_tracks: dict[str, str]) -> str | None:
    if node is None:
        return None
    if node[0] == "name":
        if node[1] in local_tracks:
            return local_tracks[node[1]]
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", node[1]):
            return node[1]
        return None
    if node[0] == "methodcall" and node[2] in ("getTrack", "findIdleTrack") and len(node[3]) >= 2:
        return _track_arg(node[2], node[3])
    if node[0] == "string":
        return node[1]
    if node[0] == "number":
        return node[1]
    return None


def _track_arg(method: str, args) -> str:
    if method == "findIdleTrack":
        return ExprNormalizer._track_sym(args[0])
    return ExprNormalizer._track_sym(args[-1])


def _collect_track_locals(stmts) -> dict[str, str]:
    """`local track = context:getTrack(A, B)` -> {track: B}；浅扫，够用即可。"""
    out: dict[str, str] = {}

    def walk(block) -> None:
        for stmt in block:
            if stmt[0] == "local" and stmt[2]:
                first = stmt[2][0]
                if first[0] == "methodcall" and first[2] in ("getTrack", "findIdleTrack") \
                        and len(first[3]) >= 2:
                    out[stmt[1][0]] = _track_arg(first[2], first[3])
            elif stmt[0] == "if":
                for _cond, block in stmt[1]:
                    walk(block)
                if stmt[2]:
                    walk(stmt[2])
            elif stmt[0] == "do":
                walk(stmt[1])

    walk(stmts)
    return out


def _iter_nodes(node):
    """后序遍历 AST 子节点，产出所有 tuple 节点。"""
    if not isinstance(node, tuple):
        return
    for item in node:
        if isinstance(item, tuple):
            yield from _iter_nodes(item)
        elif isinstance(item, list):
            for sub in item:
                yield from _iter_nodes(sub)
    yield node


def _scan_calls(stmts, method: str):
    """产出统一形状的 ("methodcall", receiver, method, args)。"""
    for stmt in stmts:
        for node in _iter_nodes(stmt):
            if node[0] == "methodcall" and node[2] == method:
                yield node
            elif node[0] == "call" and node[1][0] == "index" \
                    and node[1][2][0] == "name" and node[1][2][1] == method:
                yield ("methodcall", node[1][1], method, node[2])


def _scan_returns(stmts):
    for stmt in stmts:
        if stmt[0] == "return":
            for expr in stmt[1]:
                yield expr
        elif stmt[0] == "if":
            for _cond, block in stmt[1]:
                yield from _scan_returns(block)
            if stmt[2]:
                yield from _scan_returns(stmt[2])
        elif stmt[0] == "do":
            yield from _scan_returns(stmt[1])
        elif stmt[0] == "while":
            yield from _scan_returns(stmt[2])
        elif stmt[0] == "repeat":
            yield from _scan_returns(stmt[1])
        elif stmt[0] in ("for_num", "for_in"):
            yield from _scan_returns(stmt[-1])


def _scan_delegations(stmts):
    for stmt in stmts:
        if stmt[0] == "return":
            for expr in stmt[1]:
                if expr[0] == "call" and expr[1][0] == "index" \
                        and expr[1][2][0] == "name" and expr[1][2][1] == "transition":
                    yield expr
        elif stmt[0] == "if":
            for _cond, block in stmt[1]:
                yield from _scan_delegations(block)
            if stmt[2]:
                yield from _scan_delegations(stmt[2])
        elif stmt[0] == "do":
            yield from _scan_delegations(stmt[1])


def _scan_input_refs(stmt, out: set[str]) -> None:
    for node in _iter_nodes(stmt):
        if node[0] == "name" and re.fullmatch(r"INPUT_[A-Z0-9_]+", node[1]):
            out.add(node[1])
        elif node[0] == "index" and node[2][0] == "name" \
                and re.fullmatch(r"INPUT_[A-Z0-9_]+", node[2][1]):
            out.add(node[2][1])


def _collect_free_names(stmts, known: set[str]) -> list[str]:
    """按作用域收集未绑定的自由名字（用于 runtime-global 记录）。"""
    found: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name not in seen:
            seen.add(name)
            found.append(name)

    def walk_block(block, scope: set[str]) -> None:
        local = set(scope)
        for stmt in block:
            walk_stmt(stmt, local)

    def walk_stmt(stmt, scope: set[str]) -> None:
        kind = stmt[0]
        if kind == "local":
            for expr in stmt[2]:
                walk_expr(expr, scope)
            for name in stmt[1]:
                scope.add(name)
        elif kind == "local_function":
            scope.add(stmt[1])
            fn = stmt[2]
            walk_block(fn[3], scope | set(fn[1]))
        elif kind == "function_def":
            fn = stmt[3]
            scope2 = scope | set(fn[1])
            if stmt[2]:
                scope2.add("self")
            walk_block(fn[3], scope2)
        elif kind == "assign":
            for target in stmt[1]:
                walk_expr(target, scope, as_target=True)
            for expr in stmt[2]:
                walk_expr(expr, scope)
        elif kind == "return":
            for expr in stmt[1]:
                walk_expr(expr, scope)
        elif kind == "call_stmt":
            walk_expr(stmt[1], scope)
        elif kind == "if":
            for cond, block in stmt[1]:
                walk_expr(cond, scope)
                walk_block(block, scope)
            if stmt[2]:
                walk_block(stmt[2], scope)
        elif kind == "while":
            walk_expr(stmt[1], scope)
            walk_block(stmt[2], scope)
        elif kind == "repeat":
            walk_block(stmt[1], scope)
            walk_expr(stmt[2], scope)
        elif kind == "for_num":
            walk_expr(stmt[2], scope)
            walk_expr(stmt[3], scope)
            if stmt[4]:
                walk_expr(stmt[4], scope)
            walk_block(stmt[5], scope | {stmt[1]})
        elif kind == "for_in":
            for expr in stmt[2]:
                walk_expr(expr, scope)
            walk_block(stmt[3], scope | set(stmt[1]))
        elif kind == "do":
            walk_block(stmt[1], scope)

    def walk_expr(node, scope: set[str], as_target: bool = False) -> None:
        if not isinstance(node, tuple):
            return
        kind = node[0]
        if kind == "name":
            if not as_target and node[1] not in scope and node[1] not in known:
                add(node[1])
            return
        if kind == "index":
            walk_expr(node[1], scope)
            if node[2][0] != "name":      # 字段名不是变量引用
                walk_expr(node[2], scope)
            return
        if kind == "methodcall":
            walk_expr(node[1], scope)
            for arg in node[3]:
                walk_expr(arg, scope)
            return
        for item in node[1:]:
            if isinstance(item, tuple):
                walk_expr(item, scope)
            elif isinstance(item, list):
                for sub in item:
                    if isinstance(sub, tuple):
                        walk_expr(sub, scope)

    walk_block(stmts, set())
    return found


def _uniq(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _mutates_machine_state(block) -> bool:
    for node in _iter_nodes(("do", block)):
        if node[0] != "assign":
            continue
        for target in node[1]:
            cur = target
            while isinstance(cur, tuple) and cur[0] == "index":
                cur = cur[1]
            if isinstance(cur, tuple) and cur[0] == "name" and cur[1] in ("this", "self"):
                return True
    return False


def _dedupe_transitions(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    for tr in items:
        key = (tr["on"], tr["guard"], tr["target"],
               tuple(tr["animations"]), tuple(tr.get("stop_animations", [])))
        if key in seen:
            continue
        seen.add(key)
        out.append(tr)
    return out


# ---------------------------------------------------------------------------
# transition 遍历
# ---------------------------------------------------------------------------

class _TCtx:
    __slots__ = ("on", "guards")

    def __init__(self, on: str | None = None, guards=None):
        self.on = on
        self.guards = list(guards or [])

    def clone(self):
        return _TCtx(self.on, self.guards)


class _TAcc:
    __slots__ = ("anims", "stops", "emitted")

    def __init__(self, anims=None, stops=None):
        self.anims = list(anims or [])
        self.stops = list(stops or [])
        self.emitted = False

    def clone(self):
        return _TAcc(self.anims, self.stops)


class _TransitionWalker:
    def __init__(self, analyzer: Analyzer, out: list[dict], local_tracks: dict[str, str],
                 mod: Module, state_id: str):
        self.a = analyzer
        self.out = out
        self.local_tracks = local_tracks
        self.mod = mod
        self.state_id = state_id
        self.file_rel = mod.file_rel if mod else "<anon>"

    def walk_block(self, block, ctx: _TCtx, acc: _TAcc) -> bool:
        """返回 True 表示该块已 return（后续语句不可达）。"""
        for stmt in block:
            if self.walk_stmt(stmt, ctx, acc):
                return True
        return False

    def walk_stmt(self, stmt, ctx: _TCtx, acc: _TAcc) -> bool:
        kind = stmt[0]
        if kind == "if":
            negations: list[tuple] = []
            for cond, block in stmt[1]:
                branch_ctx = self.derive(ctx, cond, negations, negate=False)
                branch_acc = acc.clone()
                terminated = self.walk_block(block, branch_ctx, branch_acc)
                if not terminated:
                    self.flush(branch_ctx, branch_acc)
                negations.append(cond)
            if stmt[2]:
                else_ctx = self.derive(ctx, None, negations, negate=True)
                else_acc = acc.clone()
                terminated = self.walk_block(stmt[2], else_ctx, else_acc)
                if not terminated:
                    self.flush(else_ctx, else_acc)
            return False
        if kind == "return":
            self.emit_return(ctx, acc, stmt[1])
            return True
        if kind == "call_stmt":
            self.handle_call(stmt[1], acc)
            return False
        if kind == "local":
            for expr in stmt[2]:
                self.handle_expr_call(expr, acc)
            return False
        if kind in ("while", "repeat", "for_num", "for_in"):
            self.a.note(self.file_rel, R_UNSUPPORTED_FLOW, kind,
                        "control flow inside a transition is not flattened")
            return False
        if kind == "do":
            self.walk_block(stmt[1], ctx, acc)
            return False
        if kind == "assign":
            for expr in stmt[2]:
                self.handle_expr_call(expr, acc)
            return False
        return False

    def derive(self, ctx: _TCtx, cond, negations, negate: bool) -> _TCtx:
        new = ctx.clone()
        if cond is None:
            for prev in negations:
                g = self.render(prev)
                if g:
                    new.guards.append(f"!({g})")
            return new
        node = _unwrap(cond)
        if not negate:
            conjs = _split_and(node)
            sym = next((s for s in (_input_symbol(c) for c in conjs) if s), None)
            if sym is not None:
                new.on = sym
                for conj in conjs:
                    if _input_symbol(conj) is not None:
                        continue  # 已提升为 on
                    text = self.render(conj)
                    if text:
                        new.guards.append(text)
                return new
            or_sym = _input_symbol_or(node)
            if or_sym is not None and node[0] == "bin" and node[1] == "or":
                new.on = or_sym
                rest = [self.render(d) for d in _split_or(node)
                        if _input_symbol(d) != or_sym]
                rest = [r for r in rest if r]
                if rest:
                    new.guards.append(" || ".join(rest))
                return new
        for conj in _split_and(node):
            if _input_symbol(conj) is not None:
                continue  # on 已经区分了输入，不再把 input 比较塞进守卫
            text = self.render(conj)
            if not text:
                continue
            new.guards.append(f"!({text})" if negate else text)
        if negate:
            for prev in negations:
                g = self.render(prev)
                if g and not _is_input_comparison(prev):
                    new.guards.append(f"!({g})")
        return new

    def render(self, node) -> str | None:
        norm = self.a.norm
        text = norm.norm(node)
        if not text or text == "input":
            return None
        return text

    def handle_call(self, call, acc: _TAcc) -> None:
        if call[0] == "methodcall":
            name = call[2]
            if name == "runAnimation":
                info = self.a._animation_info(call, self.local_tracks, self.mod)
                if info:
                    acc.anims.append(info["animation"])
                    if "track" in info:
                        self.a.extra_tracks.add(info["track"])
            elif name == "stopAnimation":
                sym = _stop_symbol(call[3])
                if sym:
                    acc.stops.append(sym)
                    self.a.extra_tracks.add(sym)
                else:
                    self.a.note(self.file_rel, R_TRACK, _render_raw(call),
                                "stopAnimation target is not statically resolvable")
        elif call[0] == "call":
            fn = call[1]
            if fn[0] == "index" and fn[2][0] == "name" and fn[2][1] in ("runAnimation", "stopAnimation"):
                self.handle_call(("methodcall", fn[1], fn[2][1], call[2]), acc)
            elif fn[0] == "name" and fn[1] not in LUA_STDLIB:
                self.inline_helper(fn[1], acc, depth=0)

    def inline_helper(self, name: str, acc: _TAcc, depth: int) -> None:
        """本地 helper 内联一层：把它的 runAnimation/stopAnimation 记为候选。"""
        helper = self.mod.bindings.get(name) if self.mod else None
        if not isinstance(helper, Func) or not helper.body or depth > 2:
            self.a.note(self.file_rel, R_LOCAL_HELPER, name,
                        "local helper called in transition; its state effects are not modeled")
            return
        tracks = _collect_track_locals(helper.body)
        merged = dict(self.local_tracks)
        merged.update(tracks)
        for node in _iter_nodes(("do", helper.body)):
            if node[0] == "methodcall" and node[2] in ("runAnimation", "stopAnimation"):
                info = self.a._animation_info(node, merged, helper.module) \
                    if node[2] == "runAnimation" else None
                if node[2] == "runAnimation":
                    if info:
                        acc.anims.append(info["animation"])
                else:
                    sym = _stop_symbol(node[3])
                    if sym:
                        acc.stops.append(sym)
                        self.a.extra_tracks.add(sym)
            elif node[0] == "call" and node[1][0] == "name" and node[1][1] not in LUA_STDLIB:
                sub = helper.module.bindings.get(node[1][1]) if helper.module else None
                if isinstance(sub, Func):
                    self.inline_helper(node[1][1], acc, depth + 1)
        if _mutates_machine_state(helper.body):
            self.a.note(self.file_rel, R_LOCAL_HELPER, name,
                        "local helper mutates machine state; mutation not modeled in IR")

    def handle_expr_call(self, expr, acc: _TAcc) -> None:
        for node in _iter_nodes(expr):
            if node[0] == "methodcall" and node[2] in ("runAnimation", "stopAnimation"):
                self.handle_call(node, acc)
            elif node[0] == "call" and node[1][0] == "name" and node[1][1] not in LUA_STDLIB:
                self.inline_helper(node[1][1], acc, depth=0)

    def emit_return(self, ctx: _TCtx, acc: _TAcc, exprs) -> None:
        if not exprs:
            self.emit(ctx, acc, "self")
            return
        node = exprs[0]
        target, deleg, tbl = self.a.resolve_target(node, self.file_rel)
        if deleg:
            return
        self.emit(ctx, acc, target or "self")

    def emit(self, ctx: _TCtx, acc: _TAcc, target: str) -> None:
        if target == "self" and not ctx.on and not ctx.guards and not acc.anims and not acc.stops:
            return  # 无输入、无守卫、无动画的 return self 不是一次转移
        guard = None
        if ctx.guards:
            guard = self.a.register_guard(ctx.guards, self.file_rel, self.state_id)
        on = ctx.on or "*"
        tr = {
            "on": on,
            "guard": guard,
            "target": target,
            "animations": _uniq(acc.anims),
        }
        if acc.stops:
            tr["stop_animations"] = _uniq(acc.stops)
        self.out.append(tr)
        acc.emitted = True
        acc.anims = []
        acc.stops = []

    def flush(self, ctx: _TCtx, acc: _TAcc) -> None:
        if acc.emitted or not (acc.anims or acc.stops):
            return
        self.emit(ctx, acc, "self")


def _unwrap(node):
    while node[0] == "paren":
        node = node[1]
    return node


def _split_and(node) -> list:
    node = _unwrap(node)
    if node[0] == "bin" and node[1] == "and":
        return _split_and(node[2]) + _split_and(node[3])
    return [node]


def _split_or(node) -> list:
    node = _unwrap(node)
    if node[0] == "bin" and node[1] == "or":
        return _split_or(node[2]) + _split_or(node[3])
    return [node]


def _is_input_comparison(node) -> bool:
    return _input_symbol(node) is not None


def _input_symbol(node):
    """`input == INPUT_X` / `input == this.INPUT_X` -> INPUT_X；否则 None。"""
    node = _unwrap(node)
    if node[0] != "bin" or node[1] != "==":
        return None
    left, right = node[2], node[3]
    if left[0] == "name" and left[1] == "input":
        return _input_like(right)
    if right[0] == "name" and right[1] == "input":
        return _input_like(left)
    return None


def _input_symbol_or(node):
    node = _unwrap(node)
    if node[0] == "bin" and node[1] == "or":
        return _input_symbol_or(node[2]) or _input_symbol_or(node[3])
    return _input_symbol(node)


def _input_like(node):
    if node[0] == "name" and re.fullmatch(r"INPUT_[A-Z0-9_]+", node[1]):
        return node[1]
    if node[0] == "index" and node[2][0] == "name" \
            and re.fullmatch(r"INPUT_[A-Z0-9_]+", node[2][1]):
        return node[2][1]
    return None


def _stop_symbol(args) -> str | None:
    if not args:
        return None
    node = args[0]
    if node[0] == "methodcall" and node[2] in ("getTrack", "findIdleTrack") and len(node[3]) >= 2:
        return _track_arg(node[2], node[3])
    if node[0] == "name":
        return node[1]
    if node[0] == "string":
        return node[1]
    return None


# ---------------------------------------------------------------------------
# schema 校验（自己实现 draft-2020-12 的子集，不依赖 jsonschema）
# ---------------------------------------------------------------------------

def validate_schema(instance, schema, path: str = "$", errors: list[str] | None = None) -> list[str]:
    if errors is None:
        errors = []
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(instance, t) for t in types):
            errors.append(f"{path}: expected type {expected}, got {type(instance).__name__}")
            return errors
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    if "minimum" in schema and isinstance(instance, (int, float)) and instance < schema["minimum"]:
        errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        props = schema.get("properties", {})
        extra_allowed = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                validate_schema(value, props[key], f"{path}.{key}", errors)
            elif extra_allowed is False:
                errors.append(f"{path}: additional property {key!r} not allowed")
            elif isinstance(extra_allowed, dict):
                validate_schema(value, extra_allowed, f"{path}.{key}", errors)
    if isinstance(instance, list) and "items" in schema:
        for idx, item in enumerate(instance):
            validate_schema(item, schema["items"], f"{path}[{idx}]", errors)
    return errors


def _type_ok(value, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def validate_ir(ir: dict, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = validate_schema(ir, schema)
    # 附加语义断言（schema 表达不了的）
    ids = [s["id"] for s in ir.get("states", [])]
    if len(ids) != len(set(ids)):
        errors.append("$.states: duplicate state id")
    counts = ir.get("counts", {})
    if counts.get("states") != len(ids):
        errors.append("$.counts.states does not match len(states)")
    transitions = sum(len(s["transitions"]) for s in ir.get("states", []))
    if counts.get("transitions") != transitions:
        errors.append("$.counts.transitions does not match sum(len(transitions))")
    if counts.get("inputs") != len(ir.get("inputs", [])):
        errors.append("$.counts.inputs does not match len(inputs)")
    if counts.get("guards") != len(ir.get("guards", [])):
        errors.append("$.counts.guards does not match len(guards)")
    guard_ids = {g["id"] for g in ir.get("guards", [])}
    for st in ir.get("states", []):
        for tr in st["transitions"]:
            if tr["guard"] is not None and tr["guard"] not in guard_ids:
                errors.append(f"$.states[{st['id']}]: guard {tr['guard']} not declared")
            if tr["guard"] is None and tr["on"] == "*" and not tr["animations"]:
                errors.append(f"$.states[{st['id']}]: unconditional polled transition without effect")
    for item in ir.get("unresolved", []):
        for key in ("file", "symbol", "reason"):
            if not item.get(key):
                errors.append(f"$.unresolved: item missing {key}")
    return errors


# ---------------------------------------------------------------------------
# 覆盖率：scripts 下所有 *state_machine*.lua 的语法级解析
# ---------------------------------------------------------------------------

def coverage_scan(scripts_dir: Path, flattened: set[str]) -> dict:
    files = sorted(p.name for p in scripts_dir.glob("*state_machine*.lua"))
    parsed: list[str] = []
    failed: list[dict] = []
    for name in files:
        path = scripts_dir / name
        try:
            parse_lua(path.read_text(encoding="utf-8", errors="replace"))
            parsed.append(name)
        except LuaSyntaxError as exc:
            failed.append({"file": name, "reason": f"{R_PARSE}: {exc}"})
        except OSError as exc:
            failed.append({"file": name, "reason": f"{R_PARSE}: read error: {exc}"})
    not_flattened = [n for n in parsed if n not in flattened]
    return {
        "discovered": len(files),
        "parsed": len(parsed),
        "failed": len(failed),
        "not_flattened": len(not_flattened),
        "flattened": sorted(flattened),
        "parsed_files": parsed,
        "failed_files": failed,
        "not_flattened_files": not_flattened,
        "note": ("parsed 仅表示语法级解析通过；只有 flattened 里的文件做了完整状态/转移展开，"
                 "其余文件未展开、未验证语义"),
    }


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rel_to_root(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def resolve_scripts_dir(slice_obj: dict, override: str | None) -> Path:
    if override:
        p = Path(override)
        return p if p.is_absolute() else (ROOT / p)
    src = slice_obj.get("source", {})
    mod_root = src.get("mod_root", "")
    lua_rel = src.get("lua", "")
    scripts_rel = str(Path(lua_rel).parent) if lua_rel else "assets/tacz/scripts"
    candidates = []
    if mod_root:
        mr = Path(mod_root)
        candidates.append(ROOT / mr)
        candidates.append(ROOT.parent / mr)
        if mr.parts and mr.parts[0] == ROOT.name:
            candidates.append(ROOT.parent / mr)
    for base in candidates:
        cand = base / scripts_rel
        if cand.is_dir():
            return cand
    return ROOT / mod_root / scripts_rel


def derive_gun(slice_obj: dict, override: str | None) -> str:
    if override:
        return override
    lua = slice_obj.get("source", {}).get("lua", "")
    name = Path(lua).name
    m = re.match(r"(.+?)_state_machine\.lua$", name)
    if m:
        return m.group(1)
    sid = slice_obj.get("slice_id", "")
    m2 = re.match(r"m\d+-(.+)$", sid)
    return m2.group(1) if m2 else "unknown"


def build_report(ir: dict, slice_obj: dict, out_path: Path, coverage: dict,
                 idempotent: bool, ir_text: str, extra: dict) -> dict:
    unresolved = ir["unresolved"]
    by_reason: dict[str, int] = {}
    for item in unresolved:
        prefix = item["reason"].split(":", 1)[0]
        by_reason[prefix] = by_reason.get(prefix, 0) + 1
    origins = {"base": 0, "gun": 0}
    for st in ir["states"]:
        origins[st["origin"]] = origins.get(st["origin"], 0) + 1
    enumerated = {st["id"] for st in ir["states"]}
    dangling = sorted({tr["target"] for st in ir["states"] for tr in st["transitions"]
                       if tr["target"] != "self" and tr["target"] not in enumerated})
    return {
        "schema_version": "0.1.0",
        "task": "m5-state-ir",
        "slice_id": slice_obj.get("slice_id"),
        "slice_version": slice_obj.get("version"),
        "gun": ir["gun"],
        "state_ir": rel_to_root(out_path),
        "state_ir_sha256": sha256_text(ir_text),
        "state_ir_bytes": len(ir_text.encode("utf-8")),
        "states": ir["counts"]["states"],
        "transitions": ir["counts"]["transitions"],
        "inputs": ir["counts"]["inputs"],
        "guards": ir["counts"]["guards"],
        "origins": origins,
        "inheritance": ir["inheritance"],
        "source_files": ir["source_files"],
        "tracks": ir["tracks"],
        "inputs_list": ir["inputs"],
        "guard_kinds": _count_kinds(ir["guards"]),
        "coverage": coverage,
        "unresolved": {
            "count": len(unresolved),
            "by_reason": dict(sorted(by_reason.items())),
            "items": unresolved,
        },
        "dangling_targets": dangling,
        "on_distribution": dict(sorted(extra.get("on_distribution", {}).items())),
        "condition_driven": extra.get("condition_driven", 0),
        "delegated_fallbacks": extra.get("delegated_fallbacks", 0),
        "delegated_fallbacks_note": "委托展开后被子状态机同名输入遮蔽、运行时不可达而丢弃的基类转移条数",
        "declared_inputs_not_referenced": extra.get("inputs_unreferenced", []),
        "excluded_states": extra.get("excluded_states", []),
        "excluded_note": "这些表存在于模块树中但不在 states() 种子的可达闭包里，未进入 IR（如未启用的过热轨道、只存数值的 charge 表）",
        "idempotent": idempotent,
        "scripts_dir": rel_to_root(Path(extra["scripts_dir"])),
        "acceptance": {
            "schema_valid": extra["schema_valid"],
            "schema_errors": extra["schema_errors"],
            "states_ge_6": ir["counts"]["states"] >= 6,
            "transitions_ge_8": ir["counts"]["transitions"] >= 8,
            "inheritance_has_base": "tacz_default_state_machine_v2" in ir["inheritance"],
            "unresolved_complete": all(all(u.get(k) for k in ("file", "symbol", "reason"))
                                       for u in unresolved),
            "no_unconditional_wildcard": all(
                not (tr["on"] == "*" and tr["guard"] is None)
                for st in ir["states"] for tr in st["transitions"]),
            "inputs_equal_referenced": set(ir["inputs"]) == {
                tr["on"] for st in ir["states"] for tr in st["transitions"] if tr["on"] != "*"},
        },
        "limitations": [
            "只做静态解析：未运行 Lua，未验证真实运行时的状态转移序列",
            "requires 只展开到 scripts 目录内可解析的文件，语法级解析不计入语义展开",
            "entry 把 entry() 与 update() 里的 runAnimation 都算候选，未判断分支可达性",
            "elseif 分支只保留自身条件，不叠加前序条件取反（上游若写出可同时成立的分支，IR 不补互斥性）",
            "loop 由 (第三个参数为 true) 或 (第四个参数为 LOOP) 推出，不模拟挂起/播放模式",
            "fade 只取字面数值，表达式（如 put_away_time * 0.75）记为 null",
            "stop_animations 记录的是轨道符号（TaCZ 以轨道句柄停止动画），不是动画名",
            "runtime 注入的 INPUT_* / PLAY_ONCE_* 常量值未知，只保留符号名",
        ],
    }


def _count_kinds(guards: list[dict]) -> dict:
    out: dict[str, int] = {}
    for g in guards:
        out[g["kind"]] = out.get(g["kind"], 0) + 1
    return dict(sorted(out.items()))


def analyze(slice_obj: dict, scripts_dir: Path, gun: str) -> tuple[dict, dict]:
    a = Analyzer(scripts_dir, gun)
    ir = a.run()
    loader = a.loader
    cluster = {m.file_rel for m in a.dep_closure(loader.cache.get(f"{gun}_state_machine"))
               if m is not None} if loader.cache.get(f"{gun}_state_machine") else set()
    gun_mod = loader.cache.get(f"{gun}_state_machine")
    if gun_mod is not None:
        cluster.add(gun_mod.file_rel)
    coverage = coverage_scan(scripts_dir, cluster)
    return ir, {
        "coverage": coverage,
        "scripts_dir": str(scripts_dir),
        "excluded_states": getattr(a, "excluded_states", []),
        "on_distribution": getattr(a, "on_distribution", {}),
        "condition_driven": getattr(a, "condition_driven", 0),
        "delegated_fallbacks": getattr(a, "delegated_fallbacks", 0),
        "inputs_unreferenced": getattr(a, "inputs_unreferenced", []),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TaCZ Lua 状态机 -> 平台无关 IR")
    ap.add_argument("--slice", required=True, type=Path, help="orchestration/m5-slice.json")
    ap.add_argument("--out", type=Path, help="IR 输出路径")
    ap.add_argument("--report", type=Path, help="报告输出路径")
    ap.add_argument("--scripts-dir", help="覆盖 slice 里的脚本目录")
    ap.add_argument("--gun", help="枪械 id，默认从 slice 的 source.lua 推导")
    ap.add_argument("--self-test", action="store_true", help="校验 schema + 幂等，不写文件")
    a = ap.parse_args(argv)

    slice_path = a.slice if a.slice.is_absolute() else (ROOT / a.slice)
    if not slice_path.is_file():
        print(f"FAIL slice not found: {a.slice}", file=sys.stderr)
        return 2
    slice_obj = json.loads(slice_path.read_text(encoding="utf-8"))

    scripts_dir = resolve_scripts_dir(slice_obj, a.scripts_dir)
    if not scripts_dir.is_dir():
        print(f"FAIL scripts dir not found: {scripts_dir}", file=sys.stderr)
        return 2
    gun = derive_gun(slice_obj, a.gun)

    ir, meta = analyze(slice_obj, scripts_dir, gun)
    ir_text = dumps(ir)
    schema_path = ROOT / "schemas" / "state-machine-ir.schema.json"
    schema_errors = validate_ir(ir, schema_path)

    if a.self_test:
        ir2, _ = analyze(slice_obj, scripts_dir, gun)
        ir2_text = dumps(ir2)
        idempotent = ir_text == ir2_text
        print(f"gun={gun} states={ir['counts']['states']} "
              f"transitions={ir['counts']['transitions']} inputs={ir['counts']['inputs']} "
              f"guards={ir['counts']['guards']}")
        print(f"sha256={sha256_text(ir_text)} bytes={len(ir_text.encode('utf-8'))}")
        print(f"schema={'OK' if not schema_errors else 'FAIL'}")
        for err in schema_errors:
            print(f"  - {err}")
        print(f"idempotent={'OK' if idempotent else 'FAIL'} "
              f"(second sha256={sha256_text(ir2_text)})")
        cov = meta["coverage"]
        print(f"coverage discovered={cov['discovered']} parsed={cov['parsed']} "
              f"failed={cov['failed']} not_flattened={cov['not_flattened']}")
        if a.out and Path(a.out).is_file():
            existing = Path(a.out).read_bytes()
            same = existing == ir_text.encode("utf-8")
            print(f"on-disk-match={'OK' if same else 'FAIL'} ({a.out})")
            if not same:
                return 1
        ok = not schema_errors and idempotent
        print("SELF-TEST " + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1

    if not a.out or not a.report:
        print("FAIL --out 与 --report 在非 --self-test 模式下必填", file=sys.stderr)
        return 2
    if schema_errors:
        for err in schema_errors:
            print(f"SCHEMA FAIL {err}", file=sys.stderr)
        return 1

    out_path = a.out if a.out.is_absolute() else (ROOT / a.out)
    report_path = a.report if a.report.is_absolute() else (ROOT / a.report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(ir_text, encoding="utf-8", newline="\n")

    # 幂等：写完再算一遍，与落盘字节比对
    ir2, _ = analyze(slice_obj, scripts_dir, gun)
    idempotent = dumps(ir2).encode("utf-8") == out_path.read_bytes()

    report = build_report(ir, slice_obj, out_path, meta["coverage"], idempotent, ir_text, {
        "schema_valid": not schema_errors,
        "schema_errors": schema_errors,
        "scripts_dir": meta["scripts_dir"],
        "excluded_states": meta.get("excluded_states", []),
        "on_distribution": meta.get("on_distribution", {}),
        "condition_driven": meta.get("condition_driven", 0),
        "delegated_fallbacks": meta.get("delegated_fallbacks", 0),
        "inputs_unreferenced": meta.get("inputs_unreferenced", []),
    })
    report_text = dumps(report)
    report_path.write_text(report_text, encoding="utf-8", newline="\n")

    print(f"OK gun={gun} states={ir['counts']['states']} "
          f"transitions={ir['counts']['transitions']} guards={ir['counts']['guards']} "
          f"unresolved={len(ir['unresolved'])}")
    print(f"   ir     {rel_to_root(out_path)}  sha256={sha256_text(ir_text)}")
    print(f"   report {rel_to_root(report_path)}  sha256={sha256_text(report_text)}")
    print(f"   idempotent={'OK' if idempotent else 'FAIL'}")
    return 0 if idempotent else 1


if __name__ == "__main__":
    raise SystemExit(main())
