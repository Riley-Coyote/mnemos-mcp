"""`mnemos uninstall` takes Mnemos out as cleanly as setup put it in.

Setup writes hooks into Claude Code's settings and Codex's hooks, registers the
server with Claude Code, Codex or Claude Desktop, and schedules jobs. Until
2026-10-16 only the jobs could be removed: a person who wanted Mnemos gone had
to edit their harness's settings by hand. Now one command removes Mnemos's own
entries, and only those: anyone else's hooks and servers stay, and the memories
stay too, because they are the agent's. Without --write it only says what it
would do.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from mnemos import cli


def _mnemos_hooks(bin_path: str) -> dict:
    return {
        "SessionStart": [{"matcher": "*", "hooks": [
            {"type": "command", "command": f"{bin_path} hook session-start", "timeout": 15}]}],
        "UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": f"{bin_path} hook prompt || true", "timeout": 2}]}],
    }


FOREIGN = {"matcher": "*", "hooks": [{"type": "command", "command": "/usr/local/bin/other-tool start"}]}


@pytest.fixture
def setup_done(tmp_path, monkeypatch):
    """A machine where Mnemos was set up for Claude Code, Codex and Claude
    Desktop, beside another tool's hook and server, with a fake `claude` and
    `codex` that record what they were asked."""
    home = Path(os.environ["HOME"])
    config = tmp_path / "claude-config"
    config.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    hooks = _mnemos_hooks("/opt/bin/mnemos")
    hooks["SessionStart"].append(FOREIGN)
    (config / "settings.json").write_text(json.dumps({"model": "opus", "hooks": hooks}))
    codex = home / ".codex"
    codex.mkdir()
    (codex / "hooks.json").write_text(json.dumps({"hooks": {
        "SessionStart": [_mnemos_hooks("/opt/bin/mnemos")["SessionStart"][0], FOREIGN]}}))
    desktop = tmp_path / "claude_desktop_config.json"
    desktop.write_text(json.dumps({"mcpServers": {
        "mnemos": {"command": "/opt/bin/mnemos", "args": ["serve"]},
        "other": {"command": "/usr/local/bin/other-server"},
    }}))
    monkeypatch.setattr(cli, "_claude_desktop_config_path", lambda: desktop)
    memory = home / ".mnemos"
    memory.mkdir()
    (memory / "mnemos-agent.db").write_text("the agent's memories")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    asked = tmp_path / "asked.txt"
    for tool in ("claude", "codex"):
        script = bin_dir / tool
        script.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{asked}"\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    # No scheduler is touched here; the jobs' removal is its own test below.
    monkeypatch.setattr(cli, "_blueprint", lambda args: {"backend": "unsupported"})
    return {"config": config, "codex": codex, "desktop": desktop, "memory": memory, "asked": asked}


def _files(paths: dict) -> dict:
    return {
        "settings": (paths["config"] / "settings.json").read_text(),
        "codex": (paths["codex"] / "hooks.json").read_text(),
        "desktop": paths["desktop"].read_text(),
    }


@pytest.mark.skipif(os.name == "nt", reason="the fake claude and codex are shell scripts")
def test_without_write_it_says_what_it_would_remove_and_changes_nothing(setup_done, capsys):
    before = _files(setup_done)

    assert cli.main(["uninstall"]) == 0

    said = capsys.readouterr().out
    assert "Would remove:" in said
    assert "Claude Code: 2 Mnemos hooks in" in said
    assert "Codex: 1 Mnemos hook in" in said
    assert "Claude Desktop: the mnemos server in" in said
    assert "would run: claude mcp remove --scope user mnemos" in said
    assert "Re-run with --write" in said
    assert _files(setup_done) == before
    assert not setup_done["asked"].exists()


@pytest.mark.skipif(os.name == "nt", reason="the fake claude and codex are shell scripts")
def test_with_write_only_mnemos_goes_and_the_memories_stay(setup_done, capsys):
    assert cli.main(["uninstall", "--write"]) == 0

    said = capsys.readouterr().out
    settings = json.loads((setup_done["config"] / "settings.json").read_text())
    assert settings["model"] == "opus"
    assert settings["hooks"] == {"SessionStart": [FOREIGN]}
    codex = json.loads((setup_done["codex"] / "hooks.json").read_text())
    assert codex["hooks"] == {"SessionStart": [FOREIGN]}
    desktop = json.loads(setup_done["desktop"].read_text())
    assert desktop["mcpServers"] == {"other": {"command": "/usr/local/bin/other-server"}}
    assert setup_done["asked"].read_text().splitlines() == [
        "claude mcp remove --scope user mnemos",
        "codex mcp remove mnemos",
    ]
    assert (setup_done["memory"] / "mnemos-agent.db").read_text() == "the agent's memories"
    assert f"The memories stay, in {setup_done['memory']}" in said


def test_a_settings_file_it_cannot_read_is_left_alone(setup_done, capsys):
    broken = setup_done["config"] / "settings.json"
    broken.write_text("{ not json")

    cli.main(["uninstall", "--write"])

    assert broken.read_text() == "{ not json"
    assert "left " in capsys.readouterr().err


def test_the_jobs_are_unscheduled_with_the_rest(setup_done, monkeypatch):
    removed = []
    monkeypatch.setattr(cli, "_blueprint", lambda args: {"backend": "launchd", "agent_id": "mnemos-agent"})
    monkeypatch.setattr(cli, "_daemon_uninstall", lambda blueprint, write: removed.append(write) or 0)

    cli.main(["uninstall", "--write"])

    assert removed == [True]
