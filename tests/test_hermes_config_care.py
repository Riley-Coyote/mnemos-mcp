"""Hermes' config is someone's. What Mnemos changes there it changes on purpose,
keeps a copy of, and can take back out, and it says when it leaves something alone.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mnemos.cli import main
from mnemos.integrations.hermes import installer
from mnemos.integrations.hermes.installer import (
    PROVIDER_MODE,
    SIDECAR_MODE,
    build_diagnostics,
    format_diagnostics,
    install_hermes_plugin,
    known_hermes_homes,
    quickstart_hermes,
    remove_from_hermes,
)

yaml = pytest.importorskip("yaml")

OWN_SERVER = {
    "command": "/opt/mnemos/bin/mnemos",
    "args": ["serve", "--mode", "simple", "--agent-id", "hermes", "--db-path", "/tmp/h.db"],
    "env": {"MNEMOS_HARNESS": "hermes"},
    "timeout": 120,
    "connect_timeout": 60,
}


@pytest.fixture
def home(monkeypatch) -> Path:
    hermes_home = Path.home() / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("yes", ""))
    return hermes_home


def _config(home: Path) -> dict:
    return yaml.safe_load((home / "config.yaml").read_text())


def _write_config(home: Path, config: dict) -> str:
    text = yaml.safe_dump(config, sort_keys=False)
    (home / "config.yaml").write_text(text)
    return text


def _plugin_files(home: Path) -> list[Path]:
    return [folder / "__init__.py" for folder in installer.provider_plugin_dirs(home)]


# ── A server's own settings ──


def test_what_someone_added_to_the_server_stays(home):
    _write_config(home, {"mcp_servers": {"mnemos": {
        "command": "mnemos",
        "args": ["serve"],
        "env": {"MY_PROXY": "http://proxy", "MNEMOS_HARNESS": "old"},
        "timeout": 5,
        "sampling": {"enabled": False},
    }}})
    install_hermes_plugin(hermes_home=home, mode=SIDECAR_MODE, agent_id="nova")
    server = _config(home)["mcp_servers"]["mnemos"]
    assert "--agent-id" in server["args"] and server["sampling"] == {"enabled": False}
    assert server["env"] == {"MY_PROXY": "http://proxy", "MNEMOS_HARNESS": "hermes"}
    assert server["timeout"] == 5


def test_agent_safe_leaves_a_server_of_the_same_name_that_is_something_else(home):
    other = {"command": "some-other-memory", "args": ["run"]}
    _write_config(home, {"mcp_servers": {"mnemos": other}})
    result = install_hermes_plugin(hermes_home=home, mode=SIDECAR_MODE, agent_safe=True)
    assert _config(home)["mcp_servers"]["mnemos"] == other
    assert not result.mcp_configured and "left it unchanged" in result.warnings[0]


# ── The copy it keeps ──


def test_a_run_of_several_changes_keeps_the_file_as_it_found_it(home):
    found = _write_config(home, {"model": {"provider": "x"}, "mcp_servers": {"mnemos": OWN_SERVER}})
    install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True)
    assert "mcp_servers" not in _config(home) and _config(home)["memory"]["provider"] == "mnemos"
    assert (home / "config.yaml.bak").read_text() == found


def test_a_linked_config_stays_linked(home, tmp_path):
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "hermes.yaml"
    real.write_text("model:\n  provider: x\n")
    (home / "config.yaml").symlink_to(real)

    install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True)

    assert (home / "config.yaml").is_symlink()
    assert yaml.safe_load(real.read_text())["memory"]["provider"] == "mnemos"
    assert yaml.safe_load(real.read_text())["model"]["provider"] == "x"


# ── The one provider slot ──


def test_the_slot_someone_else_holds_is_not_taken(home):
    found = _write_config(home, {"memory": {"provider": "honcho"}})
    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True)
    assert not result.activated and (home / "config.yaml").read_text() == found
    assert "honcho" in result.warnings[0] and "one slot" in result.warnings[0]


def test_quickstart_does_not_take_it_either(home):
    _write_config(home, {"memory": {"provider": "honcho"}})
    result = quickstart_hermes(hermes_home=home, provider=True)
    assert not result.ok and _config(home)["memory"]["provider"] == "honcho"
    assert "honcho" in result.summary()


def test_force_takes_it_on_purpose(home):
    _write_config(home, {"memory": {"provider": "honcho"}})
    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, force=True)
    assert result.activated and _config(home)["memory"]["provider"] == "mnemos"


def test_another_plugin_of_this_name_stops_it_being_made_the_provider(home):
    # Hermes would load theirs and call it Mnemos, and connect would call that done.
    theirs = installer.provider_plugin_dirs(home)[0]
    theirs.mkdir(parents=True)
    (theirs / "__init__.py").write_text("def register(ctx):\n    pass  # someone's own\n")
    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True)
    assert "someone's own" in (theirs / "__init__.py").read_text()
    assert not result.activated and result.warnings
    assert installer._read_active_provider(home / "config.yaml") == ""


def test_a_plugin_from_an_older_mnemos_is_replaced_without_asking(home):
    older = f'{installer._SHIM_OPENING}"""\n\n\ndef register(ctx):\n    import nothing_now\n'
    for path in _plugin_files(home):
        path.parent.mkdir(parents=True)
        path.write_text(older)
        (path.parent / "plugin.yaml").write_text("name: mnemos\nprovides_tools:\n  - mnemos_identity_capture\n")
    assert installer.connect_would_change(home)
    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True)
    assert result.activated and not result.warnings
    assert "nothing_now" not in _plugin_files(home)[0].read_text()
    assert "mnemos_capture" in (_plugin_files(home)[0].parent / "plugin.yaml").read_text()
    assert not installer.connect_would_change(home)


# ── One memory, one way in ──


def test_the_provider_retires_the_server_mnemos_wrote(home):
    _write_config(home, {"mcp_servers": {"mnemos": OWN_SERVER, "github": {"command": "gh-mcp"}}})
    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes")
    assert list(_config(home)["mcp_servers"]) == ["github"]
    assert any("mcp_servers.mnemos is gone" in note for note in result.notes)
    assert "gone" in result.summary()


def test_a_server_that_kept_another_memory_is_named_as_it_goes(home):
    # Only when someone names another memory: otherwise the provider takes on the server's.
    _write_config(home, {"mcp_servers": {"mnemos": OWN_SERVER}})
    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="nova", db_path="/tmp/nova.db")
    assert "mcp_servers" not in _config(home)
    assert any("/tmp/h.db" in note for note in result.notes)


def test_one_with_settings_of_its_own_stays_and_says_so(home):
    _write_config(home, {"mcp_servers": {"mnemos": {**OWN_SERVER, "tools": {"include": ["mnemos_recall"]}}}})
    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes")
    assert "mnemos" in _config(home)["mcp_servers"]
    assert any("settings of its own" in note for note in result.notes) and not result.warnings
    assert not installer.connect_would_change(home)


def test_if_hermes_cant_load_it_the_server_is_how_the_agent_has_tools(home, monkeypatch):
    monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("no", "it can't"))
    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes")
    assert result.mcp_configured and "mnemos" in _config(home)["mcp_servers"]
    assert result.warnings


def test_asking_for_the_tools_alone_is_a_clean_switch_on_the_same_memory(home):
    install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes", db_path="/tmp/h.db")
    assert (home / "hooks" / installer.PRELOAD_HOOK).exists()

    result = install_hermes_plugin(hermes_home=home, mode=SIDECAR_MODE)

    assert "memory" not in _config(home)
    assert not (home / "hooks" / installer.PRELOAD_HOOK).exists()
    scope = installer._sidecar_scope(_config(home)["mcp_servers"]["mnemos"])
    assert (scope.agent_id, scope.db_path) == ("hermes", "/tmp/h.db")
    assert any("no longer Hermes' memory provider" in note for note in result.notes)


def test_agent_safe_beside_its_own_provider_is_already_done(home):
    install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes")
    before = (home / "config.yaml").read_text()
    result = quickstart_hermes(hermes_home=home, agent_safe=True)
    assert result.ok and (home / "config.yaml").read_text() == before
    assert result.install_result.active_provider == "mnemos"


def test_an_older_memory_is_named_not_silently_left(home):
    older = home / "mnemos" / "mnemos.db"
    older.parent.mkdir()
    older.write_text("")
    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes", db_path="/tmp/h.db")
    assert str(older) in result.summary()


# ── The doctor ──


def test_a_damaged_memory_is_not_ready(home):
    install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes", db_path=str(home / "h.db"))
    conn = sqlite3.connect(home / "h.db")
    conn.execute("CREATE TABLE t(a)")
    conn.executemany("INSERT INTO t VALUES (?)", [("x" * 500,)] * 40)
    conn.commit()
    conn.close()
    assert build_diagnostics(home)["ready"] is True

    data = bytearray((home / "h.db").read_bytes())
    data[4096:8192] = b"\xff" * 4096
    (home / "h.db").write_bytes(bytes(data))

    report = build_diagnostics(home)
    assert report["ready"] is False and report["db_damage"]
    assert "damaged" in format_diagnostics(report)


def test_two_memories_are_named(home):
    install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes", db_path=str(home / "h.db"))
    config = _config(home)
    config["mcp_servers"] = {"mnemos": {**OWN_SERVER, "args": ["serve", "--db-path", str(home / "other.db")]}}
    _write_config(home, config)
    report = build_diagnostics(home)
    assert report["ready"] is False and report["tools_open_other_memory"] == str(home / "other.db")
    assert "Two memories" in format_diagnostics(report)


# ── Taking it out ──


def _connected(home: Path) -> None:
    install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes", db_path=str(home / "h.db"))
    config = _config(home)
    config["model"] = {"provider": "x"}
    config["mcp_servers"] = {"mnemos": OWN_SERVER, "github": {"command": "gh-mcp"}}
    _write_config(home, config)
    (home / "h.db").write_text("the memories")


def test_without_write_it_only_says(home):
    _connected(home)
    before = (home / "config.yaml").read_text()
    said, problems = remove_from_hermes(home, write=False)
    assert not problems and len(said) >= 4
    assert (home / "config.yaml").read_text() == before
    assert all(path.exists() for path in _plugin_files(home))


def test_it_takes_out_what_mnemos_put_in_and_only_that(home):
    _connected(home)
    said, problems = remove_from_hermes(home, write=True)
    assert not problems and said
    config = _config(home)
    assert "memory" not in config
    assert config["mcp_servers"] == {"github": {"command": "gh-mcp"}} and config["model"] == {"provider": "x"}
    assert not any(path.exists() for path in _plugin_files(home))
    assert not (home / "hooks" / installer.PRELOAD_HOOK).exists()
    # The memories are the agent's, and this is how connecting again finds them.
    assert (home / "h.db").read_text() == "the memories"
    assert json.loads((home / "mnemos.json").read_text())["agent_id"] == "hermes"
    assert remove_from_hermes(home, write=True) == ([], [])


def test_someone_elses_things_stay(home):
    _write_config(home, {"memory": {"provider": "honcho"}, "mcp_servers": {"mnemos": {"command": "other", "args": ["run"]}}})
    theirs = installer.provider_plugin_dirs(home)[0]
    theirs.mkdir(parents=True)
    (theirs / "__init__.py").write_text("def register(ctx):\n    pass\n")
    assert remove_from_hermes(home, write=True) == ([], [])
    assert _config(home)["memory"]["provider"] == "honcho"
    assert (theirs / "__init__.py").exists()


def test_every_home_on_this_machine_is_looked_at(home):
    work = home / "profiles" / "work"
    work.mkdir(parents=True)
    assert known_hermes_homes() == [home, work]


def test_uninstall_says_what_it_would_do_for_hermes(home, capsys, monkeypatch):
    monkeypatch.setenv("PATH", "")
    _connected(home)
    before = (home / "config.yaml").read_text()
    main(["uninstall"])
    said = capsys.readouterr().out
    assert "Hermes: memory.provider" in said and "Hermes: the mnemos server" in said
    assert (home / "config.yaml").read_text() == before


def test_a_server_added_because_hermes_cant_load_it_opens_the_memory_it_has(home, monkeypatch):
    # It came out as `serve --mode simple`: another memory altogether, with no word of it.
    (home / "mnemos.json").write_text(json.dumps({
        "agent_id": "nova", "db_path": "/tmp/n.db", "person_id": "riley", "project_scope": "work",
    }))
    monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("no", "it can't"))

    install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True)

    scope = installer._sidecar_scope(_config(home)["mcp_servers"]["mnemos"])
    assert (scope.agent_id, str(scope.db_path), scope.person_id, scope.project_scope) == (
        "nova", "/tmp/n.db", "riley", "work",
    )


def test_a_server_moved_to_this_memory_names_the_one_it_had(home, monkeypatch):
    _write_config(home, {"mcp_servers": {"mnemos": OWN_SERVER}})
    monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("no", "it can't"))

    result = install_hermes_plugin(
        hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes", db_path="/tmp/other.db",
    )

    assert "/tmp/other.db" in _config(home)["mcp_servers"]["mnemos"]["args"]
    assert any("/tmp/h.db" in note for note in result.notes)


def test_someone_elses_plugin_doesnt_cost_the_agent_its_tools(home):
    # The slot says mnemos, but the plugin under that name isn't Mnemos's, so the
    # provider isn't carrying anything and the server is what the agent has.
    _write_config(home, {"memory": {"provider": "mnemos"}, "mcp_servers": {"mnemos": OWN_SERVER}})
    plugin = installer.provider_plugin_dirs(home)[0]
    plugin.mkdir(parents=True)
    (plugin / "__init__.py").write_text("# someone else's plugin\n")

    result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True, agent_id="hermes")

    assert result.warnings
    assert _config(home)["mcp_servers"]["mnemos"] == OWN_SERVER
