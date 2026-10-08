"""Tests for the safety gate: apply refuses without explicit review."""

import pytest

from self_healing_docs.cli import main
from self_healing_docs.drift import detect_drift, iter_doc_events
from self_healing_docs.propose import (
    DocWatchSafetyError,
    apply_proposal,
    build_proposals,
    write_proposals,
)
from self_healing_docs.scan import scan_source_tree


def _pending_proposal(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": "def new_name():\n    pass\n",
            "docs/api.md": "## old_name\n",
        }
    )
    index = scan_source_tree(root)
    findings = detect_drift(index, iter_doc_events(root / "docs"))
    proposals = build_proposals(findings)
    paths = write_proposals(proposals, root / "reviews" / "pending")
    return root, paths[0]


def test_apply_function_refuses_without_flag(tree):
    root, proposal = _pending_proposal(tree)
    with pytest.raises(DocWatchSafetyError):
        apply_proposal(proposal, i_reviewed=False)
    assert (root / "docs" / "api.md").read_text(encoding="utf-8") == "## old_name\n"
    assert proposal.exists()  # still in the queue


def test_apply_function_accepts_with_flag(tree):
    root, proposal = _pending_proposal(tree)
    apply_proposal(proposal, i_reviewed=True)
    assert (root / "docs" / "api.md").read_text(encoding="utf-8") == "## pkg.mod.new_name\n"


def test_cli_apply_refuses_without_flag(tree, capsys):
    root, proposal = _pending_proposal(tree)
    rc = main(["apply", "--proposal", str(proposal)])
    assert rc == 2
    assert (root / "docs" / "api.md").read_text(encoding="utf-8") == "## old_name\n"


def test_cli_apply_with_flag_applies(tree):
    root, proposal = _pending_proposal(tree)
    rc = main(["apply", "--proposal", str(proposal), "--i-reviewed"])
    assert rc == 0
    assert (root / "docs" / "api.md").read_text(encoding="utf-8") == "## pkg.mod.new_name\n"


def test_cli_apply_list_shows_queue(tree, capsys):
    root, proposal = _pending_proposal(tree)
    rc = main(["apply", "--list", "--out", str(root / "reviews")])
    assert rc == 0
    assert proposal.name in capsys.readouterr().out
