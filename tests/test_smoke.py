"""Smoke test: the src-layout package installs and imports cleanly."""


def test_package_imports():
    import dagu_mcp

    assert dagu_mcp.__version__
