"""Settings that can't be read stop the plugin; they don't start a new memory.

The README tells people they may edit ``$HERMES_HOME/mnemos.json``. A file
cut short, missing a comma, or not readable at all counted as no settings:
the next session settled a new, empty memory for the home and wrote it over
the file. One slip in an edit lost the memory, and the edit with it.

Now a profile's own ``mnemos.json`` that is there, isn't blank, and doesn't
read as an object of settings stops the plugin for that home, with one plain
error that names the file and what's wrong with it, and is never written
over. ``hermes memory setup`` says the same. A blank file is no settings, as
before. Met during a backup in another profile, such a file is left out with
a warning. Every write of the file goes beside it first and then replaces it,
so none leaves half a file.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import types
from pathlib import Path

import pytest

from mnemos.integrations.hermes import MnemosMemoryProviderCore
from mnemos.integrations.hermes import provider as provider_module
from mnemos.integrations.hermes.scope import SettingsUnreadable, save_hermes_mnemos_config

_KEPT = {"db_path": "~/.mnemos/custom.db", "agent_id": "sage", "person_id": "ann", "project_scope": "pottery"}


@pytest.fixture(autouse=True)
def _let_go():
    yield
    provider_module._let_go_of_backups()


def _a_home_with_a_memory(home: Path) -> Path:
    """A home that has had a session: its settings, and its memory with a line in it."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "mnemos.json").write_text(json.dumps({**_KEPT, "hermes_home": str(home)}))
    provider = MnemosMemoryProviderCore()
    provider.initialize("s-1", hermes_home=str(home), platform="cli")
    assert json.loads(provider.handle_tool_call("mnemos_capture", {"content": "The glaze kiln is Ann's."}))["ok"]
    provider.shutdown()
    return home / "mnemos.json"


def _start(home: Path) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize("s-2", hermes_home=str(home), platform="cli")
    return provider


@pytest.mark.parametrize(
    ("damage", "what"),
    [
        (json.dumps(_KEPT)[:40], "isn't valid JSON"),
        ('{"db_path": "~/.mnemos/custom.db" "agent_id": "sage"}', "isn't valid JSON"),
        ("[1, 2]", "not settings"),
        ('"text"', "not settings"),
        ("null", "not settings"),
    ],
    ids=["cut short", "a missing comma", "a list", "a string", "null"],
)
def test_settings_that_cant_be_read_stop_the_plugin_and_are_kept(damage, what):
    home = Path.home() / ".hermes"
    settings = _a_home_with_a_memory(home)
    settings.write_text(damage)
    memories_before = sorted(os.listdir(Path.home() / ".mnemos"))

    provider = MnemosMemoryProviderCore()
    with pytest.raises(SettingsUnreadable) as stopped:
        provider.initialize("s-2", hermes_home=str(home), platform="cli")
    said = str(stopped.value)
    assert str(settings) in said and what in said

    # Every later call is stopped the same way, and nothing is written anywhere.
    reply = json.loads(provider.handle_tool_call("mnemos_capture", {"content": "A line for nowhere."}))
    assert not reply["ok"] and str(settings) in reply["error"]
    with pytest.raises(SettingsUnreadable):
        provider.system_prompt_block()
    assert settings.read_text() == damage, "the settings were written over"
    assert sorted(os.listdir(Path.home() / ".mnemos")) == memories_before, "a new memory was started"


def test_settings_that_cant_be_opened_stop_the_plugin():
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads any file")
    home = Path.home() / ".hermes"
    settings = _a_home_with_a_memory(home)
    os.chmod(settings, 0)
    try:
        with pytest.raises(SettingsUnreadable, match="can't be read"):
            _start(home)
    finally:
        os.chmod(settings, 0o600)
    assert json.loads(settings.read_text())["agent_id"] == "sage"


def test_a_blank_file_is_no_settings_as_before():
    home = Path.home() / ".hermes"
    home.mkdir()
    (home / "mnemos.json").write_text("  \n")
    provider = _start(home)
    try:
        assert provider.scope.agent_id == "hermes"
    finally:
        provider.shutdown()


def test_the_home_goes_on_with_its_memory_once_mended():
    home = Path.home() / ".hermes"
    settings = _a_home_with_a_memory(home)
    settings.write_text(json.dumps(_KEPT)[:40])
    with pytest.raises(SettingsUnreadable):
        _start(home)
    settings.write_text(json.dumps(_KEPT))

    provider = _start(home)
    try:
        assert "glaze kiln" in json.loads(provider.handle_tool_call("mnemos_recall", {"query": "glaze kiln"}))["result"]
    finally:
        provider.shutdown()


def test_memory_setup_says_the_same_and_changes_nothing(monkeypatch, capsys):
    saved = []
    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli.config = types.ModuleType("hermes_cli.config")
    hermes_cli.config.save_config = lambda config, **options: saved.append(config)
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_cli.config)
    home = Path.home() / ".hermes"
    home.mkdir()
    settings = home / "mnemos.json"
    settings.write_text('{"agent_id": "sage",')

    MnemosMemoryProviderCore().post_setup(str(home), {"memory": {}})

    printed = capsys.readouterr().out
    assert str(settings) in printed and "isn't valid JSON" in printed
    assert saved == [], "Mnemos was made the provider"
    assert settings.read_text() == '{"agent_id": "sage",'


def test_a_backup_leaves_out_another_profile_whose_settings_cant_be_read(monkeypatch, caplog):
    root = Path.home() / ".hermes"
    _a_home_with_a_memory(root)
    work = root / "profiles" / "work"
    work.mkdir(parents=True)
    (work / "mnemos.json").write_text('{"db_path": "~/.mnemos/custom.db",')
    monkeypatch.setenv("HERMES_HOME", str(root))

    with caplog.at_level(logging.WARNING, logger=provider_module.logger.name):
        named = MnemosMemoryProviderCore().backup_paths()

    assert [Path(path).name for path in named] == ["custom.db", "custom.db-wal"]
    said = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert sum(str(work / "mnemos.json") in line for line in said) == 1


def test_a_write_that_fails_leaves_the_settings_whole(monkeypatch):
    home = Path.home() / ".hermes"
    home.mkdir()
    settings = home / "mnemos.json"
    settings.write_text(json.dumps(_KEPT))

    def cut_off(fd):
        raise OSError("the disk filled up")

    monkeypatch.setattr(os, "fsync", cut_off)
    with pytest.raises(OSError):
        save_hermes_mnemos_config(home, {"agent_id": "someone-else"})
    monkeypatch.undo()

    assert json.loads(settings.read_text()) == _KEPT
    assert [name for name in os.listdir(home) if name.endswith(".tmp")] == []



def test_a_backup_from_a_profile_whose_settings_cant_be_read_still_takes_the_others(monkeypatch, caplog):
    """It named nothing at all: every other profile's memory was left out with it."""
    root = Path.home() / ".hermes"
    _a_home_with_a_memory(root)
    work = root / "profiles" / "work"
    work.mkdir(parents=True)
    (work / "mnemos.json").write_text(json.dumps({"db_path": "~/.mnemos/work.db", "agent_id": "w", "hermes_home": str(work)}))
    provider = MnemosMemoryProviderCore()
    provider.initialize("s-1", hermes_home=str(work), platform="cli")
    assert json.loads(provider.handle_tool_call("mnemos_capture", {"content": "Work keeps the invoices."}))["ok"]
    provider.shutdown()
    (root / "mnemos.json").write_text('{"db_path": "~/.mnemos/custom.db" "agent_id": "sage"}')
    monkeypatch.setenv("HERMES_HOME", str(root))

    with caplog.at_level(logging.WARNING, logger=provider_module.logger.name):
        named = MnemosMemoryProviderCore().backup_paths()

    assert [Path(path).name for path in named] == ["work.db", "work.db-wal"]
    said = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert sum(str(root / "mnemos.json") in line for line in said) == 1


@pytest.mark.parametrize("command", [
    ["hermes", "install", "--db-path", "{home}/.mnemos/other.db"],
    ["hermes", "quickstart", "--provider"],
])
def test_mnemos_commands_say_the_same_and_write_nothing(capsys, command):
    """`mnemos hermes install --db-path` wrote the plugin's files and then ended
    in a traceback, the file of settings still unreadable."""
    from mnemos import cli

    home = Path.home() / ".hermes"
    home.mkdir()
    settings = home / "mnemos.json"
    settings.write_text('{"agent_id": "sage",')
    words = [word.replace("{home}", str(Path.home())) for word in command]

    code = cli.main([*words, "--hermes-home", str(home)])

    said = capsys.readouterr()
    assert code != 0
    assert str(settings) in said.err and "isn't valid JSON" in said.err
    assert "Traceback" not in said.err + said.out
    assert sorted(path.name for path in home.rglob("*")) == ["mnemos.json"], "something was written"
    assert settings.read_text() == '{"agent_id": "sage",'


def test_connect_hermes_says_the_same_and_writes_nothing(monkeypatch):
    from mnemos import connect_cmd

    home = Path.home() / ".hermes"
    home.mkdir()
    (home / "mnemos.json").write_text('{"agent_id": "sage",')
    monkeypatch.setenv("HERMES_HOME", str(home))
    scope = types.SimpleNamespace(agent_id="hermes", person_id="user", project_scope="global",
                                  db_path="~/.mnemos/hermes.db")
    status = types.SimpleNamespace(provider="")

    ok, said = connect_cmd._hermes(scope, status, types.SimpleNamespace(agent_safe=False))

    assert not ok and str(home / "mnemos.json") in said
    assert sorted(path.name for path in home.rglob("*")) == ["mnemos.json"]
