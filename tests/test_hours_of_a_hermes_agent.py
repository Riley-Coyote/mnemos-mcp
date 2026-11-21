"""`mnemos hours` for a memory a Hermes agent keeps (November 2026, from the
walk): the hours are Hermes's own scheduled jobs, so it shows them as Hermes
has them, only to read, and on/off/keep refuse. Its old words (all off,
"They run Claude Code ... on your Claude plan") were untrue there, and
following them would have scheduled a Claude Code job on a Hermes agent's
memory. Whose a memory is: ``hermes.scope.hermes_home_for_store``.

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



def _job(kind, *, toolsets, at="08:00", **more) -> dict:
    """A job as Hermes's own ``create_job`` stores it (the fields that matter here)."""
    from mnemos.integrations.hermes.hours import JOB_PROMPT

    hour, minute = at.split(":")
    expr = f"{int(minute)} {int(hour)} * * *"
    job = {
        "id": f"{kind}0123abcd"[:12], "name": f"mnemos-hour-{kind}",
        "prompt": JOB_PROMPT.format(kind=kind), "deliver": "local",
        "schedule": {"kind": "cron", "expr": expr, "display": expr},
        "enabled": True, "state": "scheduled", "paused_at": None, "enabled_toolsets": toolsets,
    }
    job.update(more)
    return job


def _profile(name: str, *, jobs: list | None, names_store: bool = True) -> tuple[Path, Path]:
    """A Hermes profile on this machine, its memory where connect puts it,
    and its jobs file (none when ``jobs`` is None)."""
    home = Path.home() / ".hermes" / "profiles" / name
    home.mkdir(parents=True)
    if names_store:
        store = Path.home() / ".mnemos" / f"hermes-{name}.db"
        (home / "mnemos.json").write_text(json.dumps({
            "agent_id": f"hermes-{name}", "db_path": str(store), "hermes_home": str(home),
        }))
    else:
        store = home / "mnemos" / "mnemos.db"
    if jobs is not None:
        (home / "cron").mkdir()
        (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": jobs}))
    return home, store


@pytest.fixture
def leo(launchd, claude, monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    # The active Hermes home has jobs of its own: they aren't leo's.
    active = Path.home() / ".hermes"
    (active / "cron").mkdir(parents=True)
    (active / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        _job("ours", toolsets=["memory", "session_search", "no_mcp"], at="21:00"),
    ]}))
    home, store = _profile("leo", jobs=[
        _job("mine", toolsets=["memory", "no_mcp", "web"], at="07:15"),
        _job("dream", toolsets=None, at="03:30", state="paused", enabled=False),
    ])
    return home, store


def test_a_hermes_agents_hours_are_shown_as_hermes_has_them(leo, capsys):
    home, store = leo
    assert main(["--agent-id", "hermes-leo", "--db-path", str(store), "hours"]) == 0
    out = capsys.readouterr().out
    assert out == (
        f"Quiet hours for hermes-leo, as Hermes has them ({home}):\n"
        "  its own hour  on   daily at 07:15, online\n"
        "  our hour      off  (no job for it)\n"
        "  the dream     off  daily at 03:30, online, not limited to its memory (its job is paused)\n"
        "\n"
        "Hermes runs these as its own scheduled jobs. To change them, ask the agent in Hermes.\n"
    )
    assert "Claude" not in out and "Anthropic" not in out

    assert main(["--agent-id", "hermes-leo", "--db-path", str(store), "hours", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["where"] == "hermes" and report["hermes_home"] == str(home)
    assert report["hours"]["mine"]["at"] == "07:15" and report["hours"]["ours"] is None


@pytest.mark.parametrize("words", [
    ("on", "mine", "--write"), ("on", "mine"), ("off", "all", "--write"), ("keep", "--write"),
])
def test_changing_a_hermes_agents_hours_here_is_refused(leo, launchd, capsys, words):
    _home, store = leo
    assert main(["--agent-id", "hermes-leo", "--db-path", str(store), "hours", *words]) == 1
    captured = capsys.readouterr()
    assert captured.err == (
        "Hermes runs these as its own scheduled jobs. To change them, ask the agent in Hermes.\n"
    )
    assert captured.out == ""
    assert launchd.calls == [] and not (Path.home() / "Library" / "LaunchAgents").exists()
    assert not state.hours_dir("hermes-leo").exists()


def test_when_hermes_jobs_cannot_be_read_it_says_so_never_off(launchd, claude, monkeypatch, capsys):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    _home, store = _profile("ava", jobs=None)
    assert main(["--agent-id", "hermes-ava", "--db-path", str(store), "hours"]) == 0
    out = capsys.readouterr().out
    assert out.count("can't tell: Hermes's scheduled jobs can't be read") == 3
    assert " off " not in out


def test_a_memory_kept_in_the_hermes_homes_own_folder_is_its_agents(launchd, claude, monkeypatch, capsys):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    _home, store = _profile("kit", jobs=[], names_store=False)
    assert main(["--agent-id", "kit", "--db-path", str(store), "hours"]) == 0
    assert "Hermes runs these as its own scheduled jobs" in capsys.readouterr().out


def test_a_memory_no_hermes_home_names_is_shown_as_this_machines(leo, capsys):
    assert main(["hours", *SCOPE]) == 0
    out = capsys.readouterr().out
    assert "They run Claude Code on its own" in out and "Hermes runs these" not in out


def test_a_memory_claude_code_wakes_too_is_shown_as_this_machines(leo, tmp_path, capsys):
    """One memory shared by Claude Code and a Hermes agent: Claude Code's hours
    are this machine's jobs, so they stay changeable here."""
    _home, store = leo
    assert main(["hooks", "install", "claude-code", "--agent-id", "hermes-leo", "--db-path", str(store),
                 "--write", "--no-upkeep"]) == 0
    capsys.readouterr()
    assert main(["--agent-id", "hermes-leo", "--db-path", str(store), "hours"]) == 0
    assert "They run Claude Code on its own" in capsys.readouterr().out


def test_the_store_test_is_one_function():
    from mnemos.integrations.hermes.scope import hermes_home_for_store

    assert hermes_home_for_store(Path.home() / ".mnemos" / "nobody.db") is None
