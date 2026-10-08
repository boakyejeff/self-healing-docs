"""Tests for the AST scanner."""

from self_healing_docs.scan import scan_source_tree

PKG = {
    "pkg/__init__.py": "",
    "pkg/mod.py": '''"""Module doc."""

def public_fn(a, b=2, *args, mode="x", **kwargs):
    """Do things.

    Args:
        a (int): first.
        b (int): second.
    """
    return a


def _private():
    """Hidden."""
    pass


class Widget:
    """A widget."""

    def render(self, width, height=10):
        """Render it.

        Args:
            width (int): w.
        """
        return ""
''',
}


def test_extracts_public_symbols(tree):
    index = scan_source_tree(tree(PKG))
    assert set(index.by_qualname) == {
        "pkg.mod.public_fn",
        "pkg.mod.Widget",
        "pkg.mod.Widget.render",
    }


def test_private_names_are_skipped(tree):
    index = scan_source_tree(tree(PKG))
    assert "_private" not in index.all_names()


def test_signature_and_docstring(tree):
    index = scan_source_tree(tree(PKG))
    fn = index.by_qualname["pkg.mod.public_fn"]
    assert fn.kind == "function"
    assert fn.param_names == ["a", "b", "mode"]
    assert "Do things." in fn.docstring
    assert fn.doc_start > 0 and fn.doc_end >= fn.doc_start
    assert fn.line == 3


def test_method_drops_self(tree):
    index = scan_source_tree(tree(PKG))
    render = index.by_qualname["pkg.mod.Widget.render"]
    assert render.kind == "method"
    assert render.param_names == ["width", "height"]


def test_class_has_no_params(tree):
    index = scan_source_tree(tree(PKG))
    widget = index.by_qualname["pkg.mod.Widget"]
    assert widget.kind == "class"
    assert widget.param_names == []


def test_unparseable_file_is_skipped(tree):
    root = tree({"pkg/__init__.py": "", "pkg/broken.py": "def oops(:\n"})
    index = scan_source_tree(root)
    assert index.by_qualname == {}


def test_resolve_unknown_returns_none(tree):
    index = scan_source_tree(tree(PKG))
    assert index.resolve("nope") is None
