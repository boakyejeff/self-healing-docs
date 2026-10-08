"""Tests for proposal generation and applying proposals."""

from self_healing_docs.drift import detect_drift, detect_signature_drift, iter_doc_events
from self_healing_docs.propose import (
    apply_edits,
    apply_proposal,
    build_proposals,
    write_proposals,
)
from self_healing_docs.scan import scan_source_tree


def _renamed_symbol_tree(tree):
    return tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": "def new_name():\n    pass\n",
            "docs/api.md": "## old_name\n",
        }
    )


def test_reference_proposal_diff_and_apply(tree):
    root = _renamed_symbol_tree(tree)
    index = scan_source_tree(root)
    findings = detect_drift(index, iter_doc_events(root / "docs"))
    proposals = build_proposals(findings)
    assert len(proposals) == 1
    paths = write_proposals(proposals, root / "reviews" / "pending")
    text = paths[0].read_text(encoding="utf-8")
    assert "```diff" in text
    assert "-## old_name" in text
    assert "+## pkg.mod.new_name" in text
    assert "--i-reviewed" in text
    assert "<!--docwatch" in text

    applied = apply_proposal(paths[0], i_reviewed=True)
    assert (root / "docs" / "api.md").read_text(encoding="utf-8") == "## pkg.mod.new_name\n"
    assert applied.parent.name == "applied"
    assert not paths[0].exists()


def test_signature_proposal_fixes_docstring(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": (
                "def f(alpha, beta_new=None, gamma=1):\n"
                '    """F.\n\n    Args:\n'
                "        alpha (int): a.\n"
                "        beta_old (int): b.\n"
                '    """\n    pass\n'
            ),
        }
    )
    index = scan_source_tree(root)
    findings = detect_signature_drift(index)
    assert len(findings) == 1
    proposals = build_proposals(findings)
    assert len(proposals) == 1
    paths = write_proposals(proposals, root / "reviews" / "pending")
    apply_proposal(paths[0], i_reviewed=True)
    text = (root / "pkg" / "mod.py").read_text(encoding="utf-8")
    assert "beta_new (int): b." in text
    assert "beta_old" not in text
    assert "gamma: TODO: document." in text


def test_signature_proposal_deletes_removed_param(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": (
                "def f(alpha, gamma=1):\n"
                '    """F.\n\n    Args:\n'
                "        alpha (int): a.\n"
                "        gone (int): removed.\n"
                '    """\n    pass\n'
            ),
        }
    )
    index = scan_source_tree(root)
    findings = detect_signature_drift(index)
    assert len(findings) == 1
    assert findings[0].meta["removed"] == ["gone"]
    assert findings[0].meta["added"] == ["gamma"]
    proposals = build_proposals(findings)
    paths = write_proposals(proposals, root / "reviews" / "pending")
    apply_proposal(paths[0], i_reviewed=True)
    text = (root / "pkg" / "mod.py").read_text(encoding="utf-8")
    assert "gone" not in text
    assert "gamma: TODO: document." in text


def test_apply_refuses_when_file_changed_underneath(tree):
    root = _renamed_symbol_tree(tree)
    index = scan_source_tree(root)
    findings = detect_drift(index, iter_doc_events(root / "docs"))
    proposals = build_proposals(findings)
    paths = write_proposals(proposals, root / "reviews" / "pending")
    # Simulate an external edit after the proposal was generated.
    (root / "docs" / "api.md").write_text("## something else\n", encoding="utf-8")
    try:
        apply_proposal(paths[0], i_reviewed=True)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for changed file")
    assert (root / "docs" / "api.md").read_text(encoding="utf-8") == "## something else\n"


def test_apply_edits_replace_and_insert():
    lines = ["a\n", "b\n", "c\n"]
    edits = [
        {"op": "replace", "line": 2, "old": "b\n", "new": "B\n"},
        {"op": "insert_after", "line": 2, "new": "b2\n"},
    ]
    assert apply_edits(lines, edits) == ["a\n", "B\n", "b2\n", "c\n"]


def test_apply_edits_delete_then_insert():
    lines = ["a\n", "gone\n", "c\n"]
    edits = [
        {"op": "delete", "line": 2, "old": "gone\n"},
        {"op": "insert_after", "line": 1, "new": "b\n"},
    ]
    assert apply_edits(lines, edits) == ["a\n", "b\n", "c\n"]
