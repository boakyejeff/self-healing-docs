"""Command-line interface for docwatch.

- ``docwatch scan --src ./src --docs ./docs --out reviews/``
  scans code and docs, prints findings, and writes proposals to the review
  queue (``<out>/pending/``).
- ``docwatch apply --proposal <file> --i-reviewed``
  applies one reviewed proposal. Without ``--i-reviewed`` it refuses.
- ``docwatch apply --list [--out reviews/]``
  lists pending proposals.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .drift import detect_drift, iter_doc_events
from .propose import (
    DocWatchSafetyError,
    apply_proposal,
    build_proposals,
    list_pending,
    write_proposals,
)
from .scan import scan_source_tree


def cmd_scan(args: argparse.Namespace) -> int:
    index = scan_source_tree(args.src)
    events = iter_doc_events(args.docs)
    findings = detect_drift(index, events)
    pending = Path(args.out) / "pending"
    proposals = build_proposals(findings)
    paths = write_proposals(proposals, pending)

    n_symbols = len(index.by_qualname)
    print(f"scanned {n_symbols} public symbols from {args.src}")
    print(f"checked {args.docs} for references")
    if not findings:
        print("no drift detected")
    else:
        kinds: dict[str, int] = {}
        for finding in findings:
            kinds[finding.kind] = kinds.get(finding.kind, 0) + 1
            print(f"{finding.file}:{finding.line} [{finding.kind}] {finding.evidence}")
            if finding.suggestions:
                print(f"    suggestions: {', '.join(finding.suggestions)}")
        summary = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
        print(f"\n{len(findings)} findings ({summary})")
    if paths:
        print(f"\n{len(paths)} proposals written to {pending}/ for human review")
        for path in paths:
            print(f"  {path}")
    else:
        print("\nno proposals generated (findings had no safe automatic fix)")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    if args.list:
        pending = list_pending(Path(args.out) / "pending")
        if not pending:
            print("review queue is empty")
        for path in pending:
            print(path)
        return 0
    if not args.proposal:
        print(
            "error: --proposal <file> is required (or --list to see the queue)",
            file=sys.stderr,
        )
        return 2
    if not args.i_reviewed:
        print(
            "refusing to apply: this proposal has not been marked as reviewed.\n"
            "Read the proposal file, and if you agree with the diff, re-run with "
            "--i-reviewed.",
            file=sys.stderr,
        )
        return 2
    try:
        destination = apply_proposal(args.proposal, i_reviewed=True)
    except (DocWatchSafetyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"applied; proposal archived at {destination}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docwatch",
        description="Detect doc/code drift and propose fixes for human review.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="scan code and docs, write proposals")
    scan.add_argument("--src", required=True, help="source tree to scan")
    scan.add_argument("--docs", required=True, help="documentation directory")
    scan.add_argument(
        "--out", default="reviews", help="review queue directory (default: reviews)"
    )
    scan.set_defaults(func=cmd_scan)

    apply = sub.add_parser("apply", help="apply a reviewed proposal")
    apply.add_argument("--proposal", help="proposal file from the review queue")
    apply.add_argument(
        "--i-reviewed",
        action="store_true",
        help="confirm you reviewed the proposal diff",
    )
    apply.add_argument(
        "--list", action="store_true", help="list pending proposals and exit"
    )
    apply.add_argument(
        "--out", default="reviews", help="review queue directory (default: reviews)"
    )
    apply.set_defaults(func=cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
