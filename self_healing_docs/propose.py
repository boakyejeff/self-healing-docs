"""Proposal generation and the human review queue.

Findings become *proposals*: unified diffs plus rationale, written to
``reviews/pending/*.md``. A human reviews each proposal file; nothing is
changed until ``apply`` runs with an explicit ``--i-reviewed`` flag.

Proposal files carry a machine-readable edit list in an HTML comment so
``apply`` can verify and replay the exact change the human reviewed.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .drift import (
    KIND_MISSING,
    KIND_SIGNATURE,
    KIND_STALE,
    Finding,
    _PARAM_LINE_RE,
)

__all__ = [
    "Proposal",
    "DocWatchSafetyError",
    "apply_edits",
    "build_proposals",
    "write_proposals",
    "apply_proposal",
    "list_pending",
]

_PROPOSAL_JSON_RE = re.compile(r"<!--docwatch\s*\n(.*?)\n-->", re.DOTALL)
_ARGS_LINE_RE = re.compile(r"^\s*(Args|Arguments|Parameters)\s*:\s*$")


class DocWatchSafetyError(RuntimeError):
    """Raised when apply is attempted without explicit human review."""


@dataclass
class Proposal:
    id: str
    kind: str
    file: str
    line: int
    symbol: str
    rationale: str
    diff: str
    edits: list[dict]


def apply_edits(lines: list[str], edits: list[dict]) -> list[str]:
    """Apply edits to file lines.

    Edit ops (line numbers are 1-based, referring to the original file):
      - {"op": "replace", "line": N, "old": str, "new": str}
      - {"op": "delete", "line": N, "old": str}
      - {"op": "insert_after", "line": N, "new": str}  (N=0 inserts at top)

    Every replace/delete verifies ``old`` still matches the current line and
    raises ValueError otherwise, so a proposal can never apply to a file that
    changed underneath it.
    """
    out = list(lines)
    point_ops = [e for e in edits if e["op"] in ("replace", "delete")]
    for edit in sorted(point_ops, key=lambda e: -e["line"]):
        idx = edit["line"] - 1
        if not 0 <= idx < len(out):
            raise ValueError(f"line {edit['line']} is out of range")
        if out[idx] != edit["old"]:
            raise ValueError(
                f"line {edit['line']} changed since the proposal was made; refusing"
            )
        if edit["op"] == "replace":
            out[idx] = edit["new"]
        else:
            del out[idx]
    # Adjust insert positions for deletions above them.
    deleted_lines = sorted(e["line"] for e in point_ops if e["op"] == "delete")
    inserts = sorted(
        (e for e in edits if e["op"] == "insert_after"), key=lambda e: e["line"]
    )
    offset = 0
    new_inserts: list[tuple[int, str]] = []
    for edit in inserts:
        shift = sum(1 for d in deleted_lines if d <= edit["line"])
        new_inserts.append((edit["line"] - shift + offset, edit["new"]))
        offset += 1
    for position, new_line in sorted(new_inserts):
        out.insert(position, new_line)
    return out


def _read_lines(path: str | Path) -> list[str]:
    return Path(path).read_text(encoding="utf-8").splitlines(keepends=True)


def _unified_diff(path: str, old: list[str], new: list[str]) -> str:
    old_s = [line.rstrip("\n") for line in old]
    new_s = [line.rstrip("\n") for line in new]
    diff = "\n".join(
        difflib.unified_diff(old_s, new_s, fromfile=f"a/{path}", tofile=f"b/{path}")
    )
    return diff + "\n" if diff else ""


def _proposal_for_reference(finding: Finding) -> Proposal | None:
    """Proposals for missing_symbol / stale_example: rename the reference."""
    if not finding.new_text:
        return None  # no confident suggestion; report only
    lines = _read_lines(finding.file)
    idx = finding.line - 1
    if not 0 <= idx < len(lines):
        return None
    old_line = lines[idx]
    if finding.old_text not in old_line:
        return None
    new_line = old_line.replace(finding.old_text, finding.new_text, 1)
    edits = [{"op": "replace", "line": finding.line, "old": old_line, "new": new_line}]
    new_lines = apply_edits(lines, edits)
    rationale = (
        f"{finding.evidence}. "
        f"Suggested replacement `{finding.new_text}` was the closest match "
        f"in the scanned code ({', '.join(finding.suggestions)})."
        if finding.suggestions
        else finding.evidence
    )
    return Proposal(
        id="",
        kind=finding.kind,
        file=finding.file,
        line=finding.line,
        symbol=finding.symbol,
        rationale=rationale,
        diff=_unified_diff(finding.file, lines, new_lines),
        edits=edits,
    )


def _find_param_line(lines: list[str], start: int, end: int, name: str) -> int | None:
    """1-based line of a documented param within [start, end]; None if absent."""
    for i in range(max(start - 1, 0), min(end, len(lines))):
        match = _PARAM_LINE_RE.match(lines[i])
        if match and match.group(1).lstrip("*") == name:
            return i + 1
    return None


def _args_insert_line(lines: list[str], start: int, end: int) -> int | None:
    """1-based line after which new documented params should be inserted."""
    args_line = None
    last_param = None
    for i in range(max(start - 1, 0), min(end, len(lines))):
        if _ARGS_LINE_RE.match(lines[i]):
            args_line = i + 1
        elif args_line is not None and _PARAM_LINE_RE.match(lines[i]):
            last_param = i + 1
    return last_param or args_line


def _proposal_for_signature(finding: Finding) -> Proposal | None:
    """Proposals for signature_drift: fix the docstring param docs."""
    meta = finding.meta
    doc_start, doc_end = meta.get("doc_start", 0), meta.get("doc_end", 0)
    if not doc_start or not doc_end:
        return None
    lines = _read_lines(finding.file)
    edits: list[dict] = []
    notes: list[str] = []
    for old, new in meta.get("renames", []):
        lineno = _find_param_line(lines, doc_start, doc_end, old)
        if lineno is None:
            continue
        old_line = lines[lineno - 1]
        new_line = re.sub(rf"\b{re.escape(old)}\b", new, old_line, count=1)
        edits.append(
            {"op": "replace", "line": lineno, "old": old_line, "new": new_line}
        )
        notes.append(f"renamed documented param `{old}` to `{new}`")
    for old in meta.get("removed", []):
        lineno = _find_param_line(lines, doc_start, doc_end, old)
        if lineno is None:
            continue
        edits.append(
            {"op": "delete", "line": lineno, "old": lines[lineno - 1]}
        )
        notes.append(f"removed docs for deleted param `{old}`")
    added = meta.get("added", [])
    if added:
        insert_at = _args_insert_line(lines, doc_start, doc_end)
        if insert_at is not None:
            # All placeholders share one anchor: apply_edits stacks
            # same-line inserts in order after the anchor line.
            for name in added:
                edits.append(
                    {
                        "op": "insert_after",
                        "line": insert_at,
                        "new": f"    {name}: TODO: document.\n",
                    }
                )
            notes.append(
                f"added placeholder docs for new params: {', '.join(added)}"
            )
    if not edits:
        return None
    new_lines = apply_edits(lines, edits)
    rationale = finding.evidence + ". Proposed fix: " + "; ".join(notes) + "."
    return Proposal(
        id="",
        kind=finding.kind,
        file=finding.file,
        line=finding.line,
        symbol=finding.symbol,
        rationale=rationale,
        diff=_unified_diff(finding.file, lines, new_lines),
        edits=edits,
    )


def build_proposals(findings: list[Finding]) -> list[Proposal]:
    """Turn findings into proposals. Findings without a safe fix are skipped."""
    proposals: list[Proposal] = []
    counter = 0
    for finding in findings:
        if finding.kind in (KIND_MISSING, KIND_STALE):
            proposal = _proposal_for_reference(finding)
        elif finding.kind == KIND_SIGNATURE:
            proposal = _proposal_for_signature(finding)
        else:
            proposal = None
        if proposal is None:
            continue
        counter += 1
        proposal.id = f"{finding.kind}-{counter:03d}"
        proposals.append(proposal)
    return proposals


def _render_proposal(proposal: Proposal, pending_dir: Path) -> str:
    machine = json.dumps(
        {"id": proposal.id, "file": proposal.file, "edits": proposal.edits}
    )
    return f"""# Proposal {proposal.id}

- Kind: `{proposal.kind}`
- File: `{proposal.file}`
- Line: {proposal.line}
- Symbol: `{proposal.symbol}`

## Rationale

{proposal.rationale}

## Proposed diff

```diff
{proposal.diff}```

## Review instructions

- To ACCEPT: run `docwatch apply --proposal <path-to-this-file> --i-reviewed`
  (this file lives at `{pending_dir / (proposal.id + ".md")}`).
- To REJECT: delete this file. Nothing changes unless you explicitly apply.

<!--docwatch
{machine}
-->
"""


def write_proposals(proposals: list[Proposal], pending_dir: str | Path) -> list[Path]:
    """Write proposal files into the review queue. Returns written paths."""
    pending = Path(pending_dir)
    pending.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for proposal in proposals:
        path = pending / f"{proposal.id}.md"
        path.write_text(_render_proposal(proposal, pending), encoding="utf-8")
        paths.append(path)
    return paths


def _load_proposal(path: str | Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    match = _PROPOSAL_JSON_RE.search(text)
    if not match:
        raise ValueError(f"{path} is not a valid docwatch proposal file")
    return json.loads(match.group(1))


def apply_proposal(proposal_path: str | Path, *, i_reviewed: bool) -> Path:
    """Apply a reviewed proposal.

    Raises DocWatchSafetyError unless ``i_reviewed`` is True. Verifies every
    edit against the current file content, applies the change, and moves the
    proposal to ``reviews/applied/``.
    """
    if not i_reviewed:
        raise DocWatchSafetyError(
            "refusing to apply: pass --i-reviewed to confirm you reviewed "
            f"this proposal ({proposal_path})"
        )
    data = _load_proposal(proposal_path)
    target = Path(data["file"])
    lines = _read_lines(target)
    new_lines = apply_edits(lines, data["edits"])
    target.write_text("".join(new_lines), encoding="utf-8")
    proposal = Path(proposal_path)
    applied_dir = proposal.parent.parent / "applied"
    applied_dir.mkdir(parents=True, exist_ok=True)
    destination = applied_dir / proposal.name
    proposal.replace(destination)
    return destination


def list_pending(pending_dir: str | Path) -> list[Path]:
    pending = Path(pending_dir)
    if not pending.is_dir():
        return []
    return sorted(pending.glob("*.md"))
