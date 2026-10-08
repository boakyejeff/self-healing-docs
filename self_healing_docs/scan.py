"""AST-based scanning of a Python source tree.

Extracts the public API surface (module-level functions, classes, and their
methods) including signatures and docstrings. Private names (leading
underscore) are skipped. Files that fail to parse are skipped.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Param", "Symbol", "SymbolIndex", "scan_source_tree"]


@dataclass
class Param:
    """A single parameter of a function signature."""

    name: str
    kind: str  # "positional", "kwonly", "vararg", or "kwarg"
    has_default: bool
    annotation: str = ""


@dataclass
class Symbol:
    """One public API symbol found in the source tree."""

    qualname: str  # e.g. "shopex.cart.checkout"
    name: str  # e.g. "checkout"
    kind: str  # "function", "class", or "method"
    file: str  # path of the defining file, as a string
    line: int  # 1-based line of the def/class statement
    params: list[Param] = field(default_factory=list)
    docstring: str = ""
    doc_start: int = 0  # 1-based first line of the docstring statement (0 if none)
    doc_end: int = 0  # 1-based last line of the docstring statement (0 if none)

    @property
    def param_names(self) -> list[str]:
        """Parameter names that callers/docs care about.

        Excludes the conventional first method argument (self/cls) and
        *args/**kwargs, which docstrings rarely document by name.
        """
        names = [
            p.name for p in self.params if p.kind in ("positional", "kwonly")
        ]
        if self.kind == "method" and names[:1] in (["self"], ["cls"]):
            names = names[1:]
        return names


class SymbolIndex:
    """Lookup structure over scanned symbols."""

    def __init__(self) -> None:
        self.by_qualname: dict[str, Symbol] = {}
        self.by_name: dict[str, list[Symbol]] = {}
        self.modules: set[str] = set()  # top-level package/module names

    def add(self, sym: Symbol) -> None:
        self.by_qualname[sym.qualname] = sym
        self.by_name.setdefault(sym.name, []).append(sym)

    def resolve(self, name: str) -> Symbol | None:
        """Resolve a simple (undotted) name to a symbol, or None."""
        matches = self.by_name.get(name)
        return matches[0] if matches else None

    def all_names(self) -> list[str]:
        return sorted(self.by_name)


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _annotation_str(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _params_of(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Param]:
    args = node.args
    params: list[Param] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults: list[ast.AST | None] = [None] * (len(positional) - len(args.defaults))
    defaults += list(args.defaults)
    for arg, default in zip(positional, defaults):
        params.append(
            Param(arg.arg, "positional", default is not None, _annotation_str(arg.annotation))
        )
    if args.vararg:
        params.append(
            Param(args.vararg.arg, "vararg", False, _annotation_str(args.vararg.annotation))
        )
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params.append(
            Param(arg.arg, "kwonly", default is not None, _annotation_str(arg.annotation))
        )
    if args.kwarg:
        params.append(
            Param(args.kwarg.arg, "kwarg", False, _annotation_str(args.kwarg.annotation))
        )
    return params


def _docstring_info(node: ast.AST) -> tuple[str, int, int]:
    """Return (docstring, 1-based start line, 1-based end line)."""
    doc = ast.get_docstring(node) or ""
    start = end = 0
    body = getattr(node, "body", [])
    if doc and body:
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            start = first.lineno
            end = first.end_lineno or first.lineno
    return doc, start, end


def _make_symbol(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    qualname: str,
    kind: str,
    file: str,
) -> Symbol | None:
    name = node.name
    if name.startswith("_"):
        return None
    doc, doc_start, doc_end = _docstring_info(node)
    params = _params_of(node) if kind != "class" else []
    return Symbol(
        qualname=qualname,
        name=name,
        kind=kind,
        file=file,
        line=node.lineno,
        params=params,
        docstring=doc,
        doc_start=doc_start,
        doc_end=doc_end,
    )


def scan_source_tree(src: str | Path) -> SymbolIndex:
    """Scan ``src`` for public Python API symbols.

    Returns a SymbolIndex. Files that cannot be parsed are skipped.
    """
    root = Path(src)
    index = SymbolIndex()
    for path in sorted(root.rglob("*.py")):
        module = _module_name(root, path)
        if not module:
            continue
        index.modules.add(module.split(".")[0])
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        file_str = str(path)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sym = _make_symbol(node, f"{module}.{node.name}", "function", file_str)
                if sym:
                    index.add(sym)
            elif isinstance(node, ast.ClassDef):
                sym = _make_symbol(node, f"{module}.{node.name}", "class", file_str)
                if sym:
                    index.add(sym)
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        msym = _make_symbol(
                            child, f"{module}.{node.name}.{child.name}", "method", file_str
                        )
                        if msym:
                            index.add(msym)
    return index
