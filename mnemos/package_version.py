"""Mnemos's own version, with nothing from Mnemos imported to find it."""

from __future__ import annotations


def mnemos_version() -> str:
    """Mnemos's own version, for ``serverInfo``: the installed package's,
    else ``pyproject.toml``'s when the package metadata isn't there. Left
    unset, the MCP SDK reports its own version as the server's."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("mnemos-continuity")
    except (ImportError, PackageNotFoundError):
        pass
    import re
    from pathlib import Path

    try:
        text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    except OSError:
        return "0.0.0+unknown"
    found = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return found.group(1) if found else "0.0.0+unknown"
