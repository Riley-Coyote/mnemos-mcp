"""What a brand-new user tripped on in their first hour with only the README
(Ready D1): Claude Code's own install line, the hooks installer honouring
CLAUDE_CONFIG_DIR, full ids from `search`, `export` making its folder,
`doctor` without jargon, the server's own version, a correction naming the
other notes it also matches, and `remember` warning about a near duplicate."""

from __future__ import annotations

import json
import re
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest

from mnemos import cli
from mnemos.cli import main
from mnemos.simple_runtime import MnemosRuntime

SCOPE = ["--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo"]


def _runtime(db: Path) -> MnemosRuntime:
    return MnemosRuntime(db_path=str(db), agent_id="nova", person_id="riley", project_scope="demo")


# ── D1.1 ──


def test_mcp_install_claude_code_prints_runs_or_says_claude_is_missing(monkeypatch, capsys):
    assert main(["mcp", "install", "claude-code"]) == 0
    line = capsys.readouterr().out.strip()
    command = cli._mnemos_command()
    assert line == f"claude mcp add --scope user mnemos -- {command} serve --mode simple", line

    ran: list = []

    def fake_run(argv, **kwargs):
        ran.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 3, stdout="Added stdio MCP server mnemos\n", stderr="")

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/fake/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert main(["mcp", "install", "claude-code", "--write"]) == 3, "exits with claude's code"
    assert "Added stdio MCP server mnemos" in capsys.readouterr().out
    [(argv, kwargs)] = ran
    assert argv == [
        "/fake/bin/claude", "mcp", "add", "--scope", "user", "mnemos", "--",
        command, "serve", "--mode", "simple",
    ]
    assert not kwargs.get("shell")

    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert main(["mcp", "install", "claude-code", "--write"]) == 1
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "Claude Code isn't on your PATH. Run this yourself once it is:",
        f"claude mcp add --scope user mnemos -- {command} serve --mode simple",
    ], out
    assert len(ran) == 1, "nothing ran without claude"


# ── D1.2 ──


def test_hooks_install_honours_claude_config_dir(tmp_path, monkeypatch, capsys):
    config = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    assert main(["hooks", "install", "claude-code", "--write"]) == 0
    assert "SessionStart" in json.loads((config / "settings.json").read_text())["hooks"]
    assert not (Path.home() / ".claude" / "settings.json").exists()

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")
    assert main(["hooks", "install", "claude-code", "--write"]) == 0
    assert "SessionStart" in json.loads((Path.home() / ".claude" / "settings.json").read_text())["hooks"]
    capsys.readouterr()


# ── D1.4 ──


def test_search_prints_a_full_id_that_inspect_takes(tmp_path, capsys):
    db = tmp_path / "memory.db"
    runtime = _runtime(db)
    runtime.capture("Sam keeps a sourdough starter named Gerald.")
    runtime.close()

    assert main(["--db-path", str(db), *SCOPE, "search", "sourdough"]) == 0
    out = capsys.readouterr().out
    [engram_id] = re.findall(r"id=(\S+)", out)
    assert not engram_id.endswith("..."), out

    assert main(["--db-path", str(db), *SCOPE, "inspect", engram_id]) == 0
    assert "Gerald" in capsys.readouterr().out


def test_export_creates_a_missing_folder(tmp_path, capsys):
    db = tmp_path / "memory.db"
    runtime = _runtime(db)
    runtime.capture("Sam keeps a sourdough starter named Gerald.")
    runtime.close()

    target = tmp_path / "not" / "there" / "memory-export"
    assert main(["--db-path", str(db), *SCOPE, "export", "--workspace", str(target)]) == 0
    assert (target / "MEMORY.md").exists()
    capsys.readouterr()


# ── D1.5 ──


def test_doctor_has_no_jev_line_without_a_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MNEMOS_JEV_KEY_FILE", raising=False)
    monkeypatch.delenv("MNEMOS_CUE_JUDGE", raising=False)
    db = tmp_path / "memory.db"
    runtime = _runtime(db)
    runtime.capture("Sam keeps a sourdough starter named Gerald.")
    runtime.close()

    assert main(["doctor", "--db-path", str(db), *SCOPE]) == 0
    out = capsys.readouterr().out
    assert "Cue judge" not in out and "api_key" not in out, out


def test_doctor_says_plainly_what_is_lost_without_embeddings(tmp_path, monkeypatch, capsys):
    db = tmp_path / "memory.db"
    runtime = _runtime(db)
    runtime.capture("Sam keeps a sourdough starter named Gerald.")
    runtime.close()
    monkeypatch.setattr(MnemosRuntime, "semantic_status", lambda self, verify=False: {
        "active": False,
        "reason": "no GEMINI_API_KEY is set, and sentence-transformers is not installed "
                  "(pip install 'mnemos-continuity[embeddings]')",
    })

    assert main(["doctor", "--db-path", str(db), *SCOPE]) == 0
    lines = capsys.readouterr().out.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("Semantic:     OFF"))
    assert lines[at + 1].strip() == (
        "Without it, recall matches words only, and ideas you keep returning to can't be "
        'noticed. Add it with: pip install "mnemos-continuity[embeddings]", then: mnemos embeddings download'
    ), lines[at + 1]


# ── D1.6 ──


@pytest.mark.parametrize("module", ["mnemos.simple_mcp", "mnemos.mcp_server"])
def test_server_reports_mnemos_own_version(module):
    import importlib

    mod = importlib.import_module(module)
    server = mod.simple_mcp if module == "mnemos.simple_mcp" else mod.mcp
    options = server._mcp_server.create_initialization_options()
    assert options.server_version == version("mnemos-continuity")


# ── D1.7 ──


def test_a_correction_by_query_names_the_other_note_that_says_the_same(tmp_path):
    runtime = _runtime(tmp_path / "memory.db")
    runtime.capture("Sam prefers tabs over spaces.")
    runtime.capture("Sam likes tabs for indentation in every file.")

    result = runtime.correct("Sam prefers spaces, two of them.", query="Sam tabs")
    replaced = re.search(r"Updated closest continuity note (\S+)\.", result).group(1)
    tail = result.split("Other notes this also names: if they say the same old thing, correct them too (target_id).\n", 1)
    assert len(tail) == 2, result
    [other] = tail[1].splitlines()
    other_id, words = re.fullmatch(r'- (\S+): "(.*)"', other).groups()
    assert other_id != replaced
    notes = {n["id"]: n["content"] for n in runtime._store.search_hypomnema(
        "Sam tabs", **runtime._scope_args(), limit=10, exclude_kinds=("handoff",), live_only=False,
    )}
    assert words == notes[other_id][:80] and "tabs" in words
    runtime.close()


def test_a_correction_with_nothing_else_named_adds_nothing(tmp_path):
    runtime = _runtime(tmp_path / "memory.db")
    runtime.capture("Sam prefers tabs over spaces.")
    runtime.capture("Sam keeps a sourdough starter named Gerald.")

    result = runtime.correct("Sam prefers spaces, two of them.", query="Sam tabs")
    assert "Updated closest continuity note" in result
    assert "Other notes this also names" not in result
    runtime.close()


# ── D1.8 ──


def test_remember_warns_about_a_near_duplicate_and_not_about_something_new(tmp_path, capsys):
    db = tmp_path / "memory.db"
    runtime = _runtime(db)
    runtime.capture("Sam prefers tabs over spaces and wants terse commit messages.")
    runtime.close()

    assert main(["remember", "Sam prefers tabs", "--db-path", str(db), *SCOPE]) == 0
    out = capsys.readouterr().out
    warning = re.search(r'A memory already says something close: "(.*)" \((\S+)\)\. Saved yours too\.', out)
    assert warning, out
    assert warning.group(1) == "Sam prefers tabs over spaces and wants terse commit messages."
    assert re.search(r"^Remembered, in your words: engram_\w+$", out, re.M), out

    assert main(["remember", "Gerald the sourdough starter lives on the fridge", "--db-path", str(db), *SCOPE]) == 0
    out = capsys.readouterr().out
    assert "already says something close" not in out, out
    assert re.fullmatch(r"Remembered, in your words: engram_\w+\n", out), out


def test_doctor_still_warns_when_the_judge_is_on_without_a_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MNEMOS_JEV_KEY_FILE", raising=False)
    monkeypatch.setenv("MNEMOS_CUE_JUDGE", "jev")
    db = tmp_path / "memory.db"
    runtime = _runtime(db)
    runtime.capture("Sam keeps a sourdough starter named Gerald.")
    runtime.close()

    assert main(["doctor", "--db-path", str(db), *SCOPE]) == 0
    assert "Cue judge:    switched on" in capsys.readouterr().out
