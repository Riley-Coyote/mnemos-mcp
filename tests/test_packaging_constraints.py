"""The declared dependencies must not let a fresh install resolve a broken one.

`pip install mnemos-continuity` resolves dependencies live from PyPI, ignoring
this project's lockfile. When `mcp` was declared as `>=1.0.0` with no ceiling,
a fresh install pulled mcp 2.0 — which removed `mcp.server.fastmcp`, the module
every server entrypoint imports — and produced a server that died on import.
Every CI check passed, because CI installs from the pinned lockfile.

Since mnemos/mcp_compat.py, Mnemos runs on 1.x and 2.x, and the ceiling sits
below 3, the first major nobody has tested. This test guards the
*declaration*, so removing the upper bound fails in the suite. The wheel smoke job in `.github/workflows/release-hardening.yml` guards
the other half — that the bounded range actually resolves to something that
imports when installed unlocked. One without the other is how this shipped.

The constraint is read from the installed distribution metadata rather than by
parsing pyproject.toml: it is exactly the string pip resolves against, and it
avoids `tomllib`, which is not in the standard library before Python 3.11 (one
of this project's supported versions — the first cut of this test skipped 3.10
straight into a red CI run, which is the lesson these files exist to teach).
"""

from __future__ import annotations

import importlib.metadata as metadata
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

DISTRIBUTION = "mnemos-continuity"
LOCKFILE = Path(__file__).resolve().parent.parent / "uv.lock"


def _locked_version(name: str) -> Version:
    """The version of ``name`` the lockfile pins: the one CI tests. Read with
    a pattern, not tomllib, for the reason above."""
    if not LOCKFILE.exists():
        pytest.skip("no uv.lock beside the tests")
    found = re.search(
        rf'^\[\[package\]\]\nname = "{re.escape(name)}"\nversion = "([^"]+)"',
        LOCKFILE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert found, f"{name} is not in uv.lock"
    return Version(found.group(1))


def _requirement(name: str) -> Requirement:
    try:
        declared = metadata.requires(DISTRIBUTION) or []
    except metadata.PackageNotFoundError:
        pytest.skip(f"{DISTRIBUTION} is not installed; nothing to check")

    for spec in declared:
        req = Requirement(spec)
        # Skip requirements gated behind an extra or an env marker: the mcp
        # runtime dependency is unconditional, and a marker'd duplicate would
        # otherwise mask a missing bound on the real one.
        if req.name == name and (req.marker is None or req.marker.evaluate()):
            return req
    raise AssertionError(f"{name} is not an unconditional dependency of {DISTRIBUTION}")


class TestMcpIsBoundedBelowAnUntestedMajor:
    def test_mcp_has_an_upper_bound(self):
        """An unbounded range is what let a fresh install pull the broken 2.0."""
        req = _requirement("mcp")
        upper = [s for s in req.specifier if s.operator in ("<", "<=", "==", "~=")]
        assert upper, (
            f"mcp is declared as '{req}', with no upper bound. A fresh "
            "`pip install` will resolve the latest major, which is exactly how "
            "the fastmcp import break shipped."
        )

    def test_the_bound_excludes_3_0(self):
        """3.0 is a major nobody has run Mnemos on: 2.0 renamed the server
        class out from under every entrypoint, and the next one may too."""
        req = _requirement("mcp")
        assert not req.specifier.contains(Version("3.0.0"), prereleases=True), (
            f"mcp constraint '{req.specifier}' admits 3.0.0, which no test has run on"
        )

    def test_both_tested_majors_are_allowed(self):
        """The bound must not forbid a version that works: the 1.x the
        lockfile pins, which every CI job but one installs, and the 2.x Hermes
        pins in its own environment, which the mcp2 job installs."""
        req = _requirement("mcp")
        for tested in (_locked_version("mcp"), Version(_hermes_mcp_pin())):
            assert req.specifier.contains(tested), (
                f"mcp constraint '{req.specifier}' excludes {tested}, a version CI tests"
            )


def _hermes_mcp_pin() -> str:
    """The mcp version the mcp2 CI job installs, as release-hardening.yml says."""
    workflow = LOCKFILE.parent / ".github" / "workflows" / "release-hardening.yml"
    if not workflow.exists():
        pytest.skip("no workflow beside the tests")
    found = re.search(r'"mcp\[cli\]==([0-9.]+)"', workflow.read_text(encoding="utf-8"))
    assert found, "release-hardening.yml installs no exact mcp for the mcp2 job"
    return found.group(1)


class TestTheImportThatBrokeStillWorks:
    def test_the_server_imports_in_this_environment(self):
        """The construction that failed under mcp 2.0 must succeed here,
        whichever major this environment has.

        Importing the module builds the server and registers every simple
        tool at module scope, so a clean import is a real check of the
        surface, not just of the dependency line.
        """
        pytest.importorskip("mcp", reason="mcp extra not installed")
        import asyncio

        from mnemos.simple_mcp import SIMPLE_TOOL_NAMES, simple_mcp

        tools = asyncio.run(simple_mcp.list_tools())
        registered = {t.name for t in tools}
        assert registered == set(SIMPLE_TOOL_NAMES), (
            f"registered tools {sorted(registered)} do not match the declared "
            f"simple surface {sorted(SIMPLE_TOOL_NAMES)}"
        )
