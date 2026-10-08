"""Tests for the three drift detectors."""

from self_healing_docs.drift import (
    detect_drift,
    detect_missing_symbols,
    detect_signature_drift,
    detect_stale_examples,
    documented_params,
    iter_doc_events,
)
from self_healing_docs.scan import scan_source_tree


def test_missing_symbol_with_rename_suggestion(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": 'def new_name():\n    """New."""\n    pass\n',
            "docs/api.md": "## old_name\n\nSee `old_name` for details.\n",
        }
    )
    index = scan_source_tree(root)
    findings = detect_missing_symbols(index, iter_doc_events(root / "docs"))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind == "missing_symbol"
    assert finding.symbol == "old_name"
    assert finding.suggestions == ["pkg.mod.new_name"]
    assert finding.old_text == "old_name"
    assert finding.new_text == "pkg.mod.new_name"


def test_external_references_are_ignored(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": "def ok():\n    pass\n",
            "docs/api.md": "Uses `json.dumps()` and `os.path.join()` internally.\n",
        }
    )
    index = scan_source_tree(root)
    findings = detect_missing_symbols(index, iter_doc_events(root / "docs"))
    assert findings == []


def test_signature_drift_detects_rename(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": (
                "def transform(alpha, beta_new=None):\n"
                '    """Transform.\n\n    Args:\n'
                "        alpha (int): a.\n"
                "        beta_old (int): b.\n"
                '    """\n    pass\n'
            ),
        }
    )
    index = scan_source_tree(root)
    findings = detect_signature_drift(index)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind == "signature_drift"
    assert finding.meta["renames"] == [("beta_old", "beta_new")]
    assert "beta_old -> beta_new" in finding.evidence


def test_signature_drift_detects_added_param(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": (
                "def f(a, b=1):\n"
                '    """F.\n\n    Args:\n'
                "        a (int): a.\n"
                '    """\n    pass\n'
            ),
        }
    )
    index = scan_source_tree(root)
    findings = detect_signature_drift(index)
    assert len(findings) == 1
    assert findings[0].meta["added"] == ["b"]
    assert findings[0].meta["removed"] == []


def test_no_drift_when_docstring_matches(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": (
                "def f(a):\n"
                '    """F.\n\n    Args:\n'
                "        a (int): a.\n"
                '    """\n    return a\n'
            ),
        }
    )
    index = scan_source_tree(root)
    assert detect_signature_drift(index) == []


def test_stale_example_in_fenced_block(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": "def new_func():\n    pass\n",
            "docs/guide.md": "# Guide\n\n```python\nresult = pkg.old_func(1)\nprint(result)\n```\n",
        }
    )
    index = scan_source_tree(root)
    findings = detect_stale_examples(index, iter_doc_events(root / "docs"))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind == "stale_example"
    assert finding.suggestions == ["pkg.mod.new_func"]
    assert finding.new_text == "pkg.mod.new_func"


def test_external_calls_in_examples_are_ignored(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": "def ok():\n    pass\n",
            "docs/guide.md": "```python\ndf = pd.read_csv('x.csv')\nprint(len(df))\n```\n",
        }
    )
    index = scan_source_tree(root)
    findings = detect_stale_examples(index, iter_doc_events(root / "docs"))
    assert findings == []


def test_clean_docs_have_no_findings(tree):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": (
                "def ok(a):\n"
                '    """Ok.\n\n    Args:\n'
                "        a (int): a.\n"
                '    """\n    return a\n'
            ),
            "docs/api.md": (
                "## pkg.mod.ok\n\nUse `pkg.mod.ok()` like:\n\n```python\nok(1)\n```\n"
            ),
        }
    )
    index = scan_source_tree(root)
    assert detect_drift(index, iter_doc_events(root / "docs")) == []


def test_documented_params_styles():
    google = "Do.\n\nArgs:\n    a (int): x.\n    b: y.\n"
    assert documented_params(google) == ["a", "b"]
    sphinx = "Do.\n\n:param a: x.\n:param b: y.\n"
    assert documented_params(sphinx) == ["a", "b"]
    numpy = "Do.\n\nParameters\n----------\na : int\n    x.\nb : str\n    y.\n"
    assert documented_params(numpy) == ["a", "b"]
    assert documented_params("No params here.") == []
