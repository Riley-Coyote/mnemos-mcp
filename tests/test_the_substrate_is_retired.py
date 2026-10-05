"""The substrate is retired.

The cognitive substrate (`mnemos substrate-tick` and mnemos/substrate) had a
model write dreams, wanderings, insights and reflections into the agent's
memory. A memory is the agent's own or it is nothing to build an identity on,
so the command, the package, and what the wheel ships of it are gone.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from mnemos import cli

ROOT = Path(__file__).resolve().parent.parent


def test_the_command_is_gone(capsys):
    with pytest.raises(SystemExit) as exited:
        cli.main(["substrate-tick"])
    assert exited.value.code == 2
    assert "invalid choice: 'substrate-tick'" in capsys.readouterr().err


def test_the_package_is_gone(monkeypatch):
    for name in [n for n in sys.modules if n == "mnemos.substrate" or n.startswith("mnemos.substrate.")]:
        monkeypatch.delitem(sys.modules, name)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mnemos.substrate")


def _wheel_files() -> list[str]:
    """The wheel's file list as pyproject.toml's packaging gives it: every
    file under each package (less what .gitignore keeps out of a build), and
    every force-include at its destination."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        tomllib = pytest.importorskip("tomli")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        wheel = tomllib.load(handle)["tool"]["hatch"]["build"]["targets"]["wheel"]
    files = []
    for package in wheel["packages"]:
        for path in (ROOT / package).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files.append(path.relative_to(ROOT).as_posix())
    for source, destination in wheel.get("force-include", {}).items():
        source_path = ROOT / source
        if source_path.is_file():
            files.append(destination)
        for path in source_path.rglob("*"):
            if path.is_file():
                files.append(f"{destination}/{path.relative_to(source_path).as_posix()}")
    return files


def test_the_wheel_ships_nothing_of_it():
    files = _wheel_files()
    assert "mnemos/cli.py" in files, "premise: the list holds the package's files"
    assert [f for f in files if f.startswith("mnemos/substrate/")] == []


def test_a_setup_saved_on_the_retired_question_moves_on():
    """Advanced setup's step 6 asked whether the substrate should run. A setup
    saved waiting on that answer goes on to the provider question, as step 5
    now does, instead of claiming setup is complete."""
    pytest.importorskip("mcp.server.fastmcp")
    from mnemos import mcp_server
    from mnemos.config.loader import load_config, save_config

    save_config({"setup_step": 6, "agent_id": "nova"})
    mcp_server._config_invalidate()
    try:
        said = mcp_server.mnemos_setup("yes")
    finally:
        mcp_server._config_invalidate()

    assert said == mcp_server.ONBOARDING_PROMPTS[8]
    assert load_config()["setup_step"] == 7
