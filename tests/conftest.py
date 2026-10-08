"""Shared fixtures for the docwatch test suite."""

import pytest


@pytest.fixture
def tree(tmp_path):
    """Write {relative_path: content} into tmp_path; return tmp_path."""

    def _write(files: dict[str, str]):
        for rel, content in files.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return tmp_path

    return _write
