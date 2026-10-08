"""End-to-end CLI tests."""

from self_healing_docs.cli import main


def test_cli_scan_end_to_end(tree, capsys):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": "def new_name():\n    pass\n",
            "docs/api.md": "## old_name\n",
        }
    )
    rc = main(
        [
            "scan",
            "--src",
            str(root),
            "--docs",
            str(root / "docs"),
            "--out",
            str(root / "reviews"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "missing_symbol" in out
    assert "proposals written" in out
    pending = list((root / "reviews" / "pending").glob("*.md"))
    assert len(pending) == 1


def test_cli_scan_clean_tree(tree, capsys):
    root = tree(
        {
            "pkg/__init__.py": "",
            "pkg/mod.py": "def ok():\n    pass\n",
            "docs/api.md": "## pkg.mod.ok\n",
        }
    )
    rc = main(
        [
            "scan",
            "--src",
            str(root),
            "--docs",
            str(root / "docs"),
            "--out",
            str(root / "reviews"),
        ]
    )
    assert rc == 0
    assert "no drift detected" in capsys.readouterr().out
