"""Drift detection between scanned code and documentation.

Three detectors:

- ``missing_symbol``: a documented symbol no longer exists (fuzzy rename
  suggestions are offered).
- ``signature_drift``: a signature changed but the docstring was not updated
  (documented params vs. actual params).
- ``stale_example``: a documentation code example calls a stale name.

All matching is heuristic: dotted references are only checked when their
first component is a module from the scanned tree (external references such
as ``json.dumps`` are ignored), and Python builtins/keywords are skipped.
"""

from __future__ import annotations

import difflib
import keyword
import re
from dataclasses import dataclass, field
from pathlib import Path

from .scan import SymbolIndex

__all__ = [
    "Finding",
    "DocEvent",
    "KIND_MISSING",
    "KIND_SIGNATURE",
    "KIND_STALE",
    "iter_doc_events",
    "detect_drift",
    "detect_missing_symbols",
    "detect_signature_drift",
    "detect_stale_examples",
    "documented_params",
]

KIND_MISSING = "missing_symbol"
KIND_SIGNATURE = "signature_drift"
KIND_STALE = "stale_example"

_BUILTINS = set(dir(__builtins__)) | set(keyword.kwlist) | {"self", "cls"}

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\.]*(?:\(\))?")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_FENCE_RE = re.compile(r"^\s*```(\w*)\s*$")
_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_\.]*)\s*\(")
_PARAM_LINE_RE = re.compile(r"^\s*(\*{0,2}[A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:")


@dataclass
class Finding:
    """One detected drift instance."""

    file: str
    line: int  # 1-based
    kind: str  # KIND_MISSING | KIND_SIGNATURE | KIND_STALE
    symbol: str = ""  # related symbol qualname or reference text
    evidence: str = ""
    suggestions: list[str] = field(default_factory=list)
    old_text: str = ""  # text to replace when proposing a fix
    new_text: str = ""  # replacement text ("" when no fix can be proposed)
    meta: dict = field(default_factory=dict)  # detector-specific details


@dataclass
class DocEvent:
    """One documentation reference site: heading, code span, or code line."""

    file: str
    line: int  # 1-based
    kind: str  # "heading" | "codespan" | "code"
    text: str


def iter_doc_events(docs_root: str | Path) -> list[DocEvent]:
    """Yield reference events from Markdown docs (headings, code spans, code)."""
    events: list[DocEvent] = []
    for path in sorted(Path(docs_root).rglob("*.md")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        in_fence = False
        lang = ""
        for lineno, raw in enumerate(lines, 1):
            fence = _FENCE_RE.match(raw)
            if fence:
                if not in_fence:
                    in_fence, lang = True, fence.group(1).lower()
                else:
                    in_fence, lang = False, ""
                continue
            if in_fence:
                if lang in ("", "python", "py"):
                    events.append(DocEvent(str(path), lineno, "code", raw))
                continue
            heading = _HEADING_RE.match(raw)
            if heading:
                events.append(DocEvent(str(path), lineno, "heading", heading.group(1)))
            for span in _CODE_SPAN_RE.finditer(raw):
                events.append(DocEvent(str(path), lineno, "codespan", span.group(1)))
    return events


def _ref_tokens(text: str, loose: bool) -> list[str]:
    """Extract candidate symbol references from text.

    Strict mode (code spans): only dotted names or call-like ``name()``.
    Loose mode (headings): also bare snake_case names.
    """
    tokens: list[str] = []
    for match in _IDENT_RE.finditer(text):
        tok = match.group(0)
        core = tok[:-2] if tok.endswith("()") else tok
        if "." in core or tok.endswith("()") or (loose and "_" in core):
            tokens.append(tok)
    return tokens


def _resolve_reference(token: str, index: SymbolIndex):
    """Resolve a reference token. Returns (symbol_or_None, dotted_name).

    Returns ("", ...) for external references (dotted names whose head is not
    a scanned module) so callers can skip them.
    """
    core = token[:-2] if token.endswith("()") else token
    if "." in core:
        head = core.split(".")[0]
        if head not in index.modules:
            return None, ""  # external reference, e.g. json.dumps
        sym = index.by_qualname.get(core) or index.resolve(core.split(".")[-1])
        return sym, core
    return index.resolve(core), core


def _suggest(name: str, index: SymbolIndex, cutoff: float = 0.6) -> list[str]:
    matches = difflib.get_close_matches(name, index.all_names(), n=3, cutoff=cutoff)
    out: list[str] = []
    for match in matches:
        sym = index.resolve(match)
        out.append(sym.qualname if sym else match)
    return out


def detect_missing_symbols(
    index: SymbolIndex, events: list[DocEvent]
) -> list[Finding]:
    """Detector (a): documented symbols that no longer exist."""
    findings: list[Finding] = []
    for ev in events:
        if ev.kind == "heading":
            tokens = _ref_tokens(ev.text, loose=True)
        elif ev.kind == "codespan":
            tokens = _ref_tokens(ev.text, loose=False)
        else:
            continue
        for tok in tokens:
            sym, core = _resolve_reference(tok, index)
            if sym is not None or not core:
                continue
            name = core.split(".")[-1]
            suggestions = _suggest(name, index)
            new_text = ""
            if suggestions:
                new_text = suggestions[0]
                if tok.endswith("()"):
                    new_text += "()"
            findings.append(
                Finding(
                    file=ev.file,
                    line=ev.line,
                    kind=KIND_MISSING,
                    symbol=core,
                    evidence=f"documented reference `{tok}` matches no symbol in the scanned code",
                    suggestions=suggestions,
                    old_text=tok,
                    new_text=new_text,
                )
            )
    return findings


def documented_params(docstring: str) -> list[str]:
    """Extract documented parameter names (Google, Sphinx, and NumPy styles)."""
    params: list[str] = []
    lines = docstring.splitlines()
    for i, line in enumerate(lines):  # Google style: "Args:" section
        if re.match(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", line):
            base = len(line) - len(line.lstrip())
            for sub in lines[i + 1 :]:
                if not sub.strip():
                    break
                if len(sub) - len(sub.lstrip()) <= base:
                    break
                m = _PARAM_LINE_RE.match(sub)
                if m:
                    params.append(m.group(1).lstrip("*"))
            break
    params.extend(re.findall(r":param\s+(\w+)\s*:", docstring))  # Sphinx style
    for i, line in enumerate(lines):  # NumPy style: "Parameters" + dashes
        if re.match(r"^\s*Parameters\s*$", line) and i + 1 < len(lines):
            if re.match(r"^\s*-{3,}\s*$", lines[i + 1]):
                for sub in lines[i + 2 :]:
                    if not sub.strip():
                        break
                    m = re.match(r"\s*(\w+)\s*:", sub)
                    if m:
                        params.append(m.group(1))
                    elif sub and not sub[0].isspace():
                        break
                break
    seen: set[str] = set()
    ordered: list[str] = []
    for param in params:
        if param not in seen:
            seen.add(param)
            ordered.append(param)
    return ordered


def detect_signature_drift(index: SymbolIndex) -> list[Finding]:
    """Detector (b): docstring documents params that differ from the signature.

    Only symbols whose docstring documents at least one parameter are
    checked; a docstring that never documented params is not drift evidence.
    """
    findings: list[Finding] = []
    for sym in index.by_qualname.values():
        if sym.kind == "class" or not sym.docstring:
            continue
        documented = documented_params(sym.docstring)
        if not documented:
            continue
        actual = sym.param_names
        removed = [p for p in documented if p not in actual]
        added = [p for p in actual if p not in documented]
        if not removed and not added:
            continue
        renames: list[tuple[str, str]] = []
        for old in removed:
            match = difflib.get_close_matches(old, added, n=1, cutoff=0.6)
            if match:
                renames.append((old, match[0]))
        renamed_old = {old for old, _ in renames}
        renamed_new = {new for _, new in renames}
        removed_only = sorted(set(removed) - renamed_old)
        added_only = sorted(set(added) - renamed_new)
        evidence = (
            f"docstring documents params {documented} but the signature is {actual}"
        )
        if removed_only:
            evidence += f"; documented but gone from signature: {removed_only}"
        if added_only:
            evidence += f"; in signature but undocumented: {added_only}"
        if renames:
            evidence += "; likely renames: " + ", ".join(
                f"{old} -> {new}" for old, new in renames
            )
        findings.append(
            Finding(
                file=sym.file,
                line=sym.doc_start or sym.line,
                kind=KIND_SIGNATURE,
                symbol=sym.qualname,
                evidence=evidence,
                suggestions=[new for _, new in renames],
                meta={
                    "documented": documented,
                    "actual": actual,
                    "removed": removed_only,
                    "added": added_only,
                    "renames": renames,
                    "doc_start": sym.doc_start,
                    "doc_end": sym.doc_end,
                },
            )
        )
    return findings


def detect_stale_examples(
    index: SymbolIndex, events: list[DocEvent]
) -> list[Finding]:
    """Detector (c): doc code examples calling names that no longer exist."""
    findings: list[Finding] = []
    for ev in events:
        if ev.kind != "code":
            continue
        for match in _CALL_RE.finditer(ev.text):
            dotted = match.group(1)
            parts = dotted.split(".")
            head, called = parts[0], parts[-1]
            if called in _BUILTINS or called.startswith("__"):
                continue
            if index.resolve(called):
                continue
            if head in index.modules:
                reason = (
                    f"example calls `{dotted}()` but `{called}` is not in module `{head}`"
                )
                suggestions = _suggest(called, index)
            elif head == called:
                # Bare call to an unknown name: only flag on a strong rename
                # signal, otherwise it is probably a placeholder variable.
                suggestions = _suggest(called, index, cutoff=0.7)
                if not suggestions:
                    continue
                reason = (
                    f"example calls `{called}()` which matches no symbol "
                    f"(possible rename of `{suggestions[0]}`)"
                )
            else:
                continue  # external receiver, e.g. pd.read_csv
            new_text = suggestions[0] if suggestions else ""
            if "." in dotted and new_text and "." not in new_text:
                new_text = f"{head}.{new_text}"
            findings.append(
                Finding(
                    file=ev.file,
                    line=ev.line,
                    kind=KIND_STALE,
                    symbol=dotted,
                    evidence=reason,
                    suggestions=suggestions,
                    old_text=dotted,
                    new_text=new_text,
                )
            )
    return findings


def detect_drift(index: SymbolIndex, events: list[DocEvent]) -> list[Finding]:
    """Run all detectors and deduplicate findings."""
    findings = (
        detect_missing_symbols(index, events)
        + detect_signature_drift(index)
        + detect_stale_examples(index, events)
    )
    seen: set[tuple] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (finding.file, finding.line, finding.kind, finding.symbol)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return sorted(unique, key=lambda f: (f.file, f.line, f.kind))
