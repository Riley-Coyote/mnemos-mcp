"""An hour that's off says what it would be if turned on (November 2026,
from the walk): offline, because turning one on from off keeps it offline
unless the person asks. Before this, an off hour that had been online said
"online" in `mnemos hours`, `hours keep` and `--json` (``state.hours_now``,
which the page reads too). What's kept doesn't change.

Every scheduler here is the suite's fake (tests/conftest.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mnemos.cli import main
from mnemos.setup import scheduler, state

SCOPE = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]


@pytest.fixture
def launchd(monkeypatch, os_scheduler):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    return os_scheduler


@pytest.fixture
def claude(tmp_path, monkeypatch) -> Path:
    folder = tmp_path / "local-bin"
    folder.mkdir()
    binary = folder / "claude"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.delenv("MNEMOS_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(folder))
    return binary





def test_an_hour_that_is_off_says_offline(launchd, claude, capsys):
    assert main(["hours", "on", "ours", "--minutes", "20", "--online", *SCOPE, "--write"]) == 0
    assert main(["hours", "off", "all", *SCOPE, "--write"]) == 0
    capsys.readouterr()

    assert main(["hours", *SCOPE]) == 0
    out = capsys.readouterr().out
    assert "  our hour      off  would start at 19:00, up to 20 minutes, offline\n" in out
    assert main(["hours", "--json", *SCOPE]) == 0
    assert json.loads(capsys.readouterr().out)["hours"]["ours"]["online"] is False
    assert main(["hours", "keep", *SCOPE, "--write"]) == 0
    assert "  our hour      off  would start at 19:00, up to 20 minutes, offline\n" in capsys.readouterr().out
    assert state.hours_now("nova")["ours"]["online"] is False

    kept = json.loads((state.hours_dir("nova") / state.CHOICE_FILE).read_text())
    assert kept["hours"]["ours"]["online"] is True, "what's kept is left as it was"

    # And it is what turning it on again gives.
    assert main(["hours", "on", "ours", *SCOPE, "--write"]) == 0
    assert state.hours_now("nova")["ours"]["online"] is False


def test_an_hour_that_is_on_still_says_what_it_has(launchd, claude):
    assert main(["hours", "on", "ours", "--online", *SCOPE, "--write"]) == 0
    assert state.hours_now("nova")["ours"]["online"] is True
