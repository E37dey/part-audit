"""Minimal OData query evaluation for the simulators ($filter subset, $select, $orderby, paging)."""
from __future__ import annotations

import re

_TOK = re.compile(r"\s*(?:(\()|(\))|(,)|('(?:[^']|'')*')|(-?\d+(?:\.\d+)?)|(\w[\w/.]*)|(\S))")


class FilterError(ValueError):
    pass


def _tokens(s: str):
    pos = 0
    out = []
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        lp, rp, comma, string, num, word, other = m.groups()
        if lp:
            out.append(("(", "("))
        elif rp:
            out.append((")", ")"))
        elif comma:
            out.append((",", ","))
        elif string is not None:
            out.append(("str", string[1:-1].replace("''", "'")))
        elif num is not None:
            out.append(("num", float(num)))
        elif word is not None:
            out.append(("word", word))
        elif other:
            raise FilterError(f"unexpected character {other!r}")
    return out


class _Parser:
    FUNCS = {"contains", "startswith", "endswith", "substringof", "tolower", "toupper"}

    def __init__(self, text: str, allow_substringof: bool):
        self.t = _tokens(text)
        self.i = 0
        self.allow_substringof = allow_substringof

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        e = self.expr_or()
        if self.i != len(self.t):
            raise FilterError("trailing tokens in $filter")
        return e

    def expr_or(self):
        left = self.expr_and()
        while self.peek() == ("word", "or"):
            self.take()
            right = self.expr_and()
            left = ("or", left, right)
        return left

    def expr_and(self):
        left = self.expr_not()
        while self.peek() == ("word", "and"):
            self.take()
            right = self.expr_not()
            left = ("and", left, right)
        return left

    def expr_not(self):
        if self.peek() == ("word", "not"):
            self.take()
            return ("not", self.expr_not())
        return self.comparison()

    def comparison(self):
        left = self.value()
        k, v = self.peek()
        if k == "word" and v in ("eq", "ne", "gt", "ge", "lt", "le"):
            self.take()
            right = self.value()
            return (v, left, right)
        return ("truthy", left)

    def value(self):
        k, v = self.take()
        if k == "(":
            e = self.expr_or()
            if self.take()[0] != ")":
                raise FilterError("missing )")
            return e
        if k == "str":
            return ("lit", v)
        if k == "num":
            return ("lit", v)
        if k == "word":
            if v in ("true", "false"):
                return ("lit", v == "true")
            if v == "null":
                return ("lit", None)
            if self.peek()[0] == "(" and v in self.FUNCS:
                if v == "substringof" and not self.allow_substringof:
                    raise FilterError("substringof is not supported")
                self.take()
                args = [self.expr_or()]
                while self.peek()[0] == ",":
                    self.take()
                    args.append(self.expr_or())
                if self.take()[0] != ")":
                    raise FilterError("missing ) after function arguments")
                return ("fn", v, args)
            return ("field", v)
        raise FilterError(f"unexpected token {v!r}")


def _get(row: dict, path: str):
    cur = row
    for p in path.split("/"):
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def _eval(e, row):
    op = e[0]
    if op == "lit":
        return e[1]
    if op == "field":
        return _get(row, e[1])
    if op == "and":
        return bool(_eval(e[1], row)) and bool(_eval(e[2], row))
    if op == "or":
        return bool(_eval(e[1], row)) or bool(_eval(e[2], row))
    if op == "not":
        return not _eval(e[1], row)
    if op == "truthy":
        return bool(_eval(e[1], row))
    if op == "fn":
        name, args = e[1], [_eval(a, row) for a in e[2]]
        if name == "tolower":
            return str(args[0] or "").lower()
        if name == "toupper":
            return str(args[0] or "").upper()
        if name == "substringof":
            return str(args[0] or "") in str(args[1] or "")
        a, b = str(args[0] or ""), str(args[1] or "")
        return {"contains": b in a, "startswith": a.startswith(b), "endswith": a.endswith(b)}[name]
    a, b = _eval(e[1], row), _eval(e[2], row)
    if isinstance(a, (int, float)) and isinstance(b, str):
        try:
            b = float(b)
        except ValueError:
            pass
    if isinstance(b, (int, float)) and isinstance(a, str):
        try:
            a = float(a)
        except ValueError:
            pass
    try:
        return {"eq": a == b, "ne": a != b, "gt": a is not None and a > b, "ge": a is not None and a >= b,
                "lt": a is not None and a < b, "le": a is not None and a <= b}[op]
    except TypeError:
        return False


def apply_filter(rows: list[dict], text: str | None, allow_substringof: bool = True) -> list[dict]:
    if not text:
        return rows
    tree = _Parser(text, allow_substringof).parse()
    return [r for r in rows if _eval(tree, r)]


def apply_orderby(rows: list[dict], text: str | None) -> list[dict]:
    if not text:
        return rows
    for part in reversed([p.strip() for p in text.split(",") if p.strip()]):
        bits = part.split()
        key, desc = bits[0], len(bits) > 1 and bits[1].lower() == "desc"
        rows = sorted(rows, key=lambda r: (_get(r, key) is None, _get(r, key) if _get(r, key) is not None else ""),
                      reverse=desc)
    return rows


def apply_select(row: dict, text: str | None, keep: tuple = ()) -> dict:
    if not text:
        return dict(row)
    names = [s.strip() for s in text.split(",") if s.strip()]
    return {k: v for k, v in row.items() if k in names or k in keep}


def split_expand(text: str | None) -> dict[str, str]:
    """'A($select=x;$filter=y),B' -> {'A': '$select=x;$filter=y', 'B': ''}"""
    out: dict[str, str] = {}
    if not text:
        return out
    depth, cur, name, opts = 0, "", None, ""
    for ch in text + ",":
        if ch == "(" and depth == 0:
            name, cur, depth = cur.strip(), "", 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                opts = cur
                cur = ""
                continue
        if ch == "," and depth == 0:
            key = name if name is not None else cur.strip()
            if key:
                out[key] = opts if name is not None else ""
            cur, name, opts = "", None, ""
            continue
        cur += ch
    return out


def parse_inner_options(text: str) -> dict[str, str]:
    out = {}
    for part in re.split(r";|%3B", text or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out
