"""Mnemos as Hermes's plugin catalog installs it: hermes-plugin/ in this repo.

A catalog install copies that folder into $HERMES_HOME/plugins/mnemos and
installs mnemos-continuity into Hermes's own environment. No `mnemos connect
hermes` runs first, so the provider has to set up the memory connect would:
one agent, the profile's own, with one memory in every chat. Left to itself it
named the memory after each chat and the person writing, so a group's rename
or a private chat was another memory.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore
from mnemos.integrations.hermes.scope import in_own_mnemos, profile_agent_id, profile_store

PLUGIN = Path(__file__).resolve().parent.parent / "hermes-plugin"


def _gateway(home: Path, chat: str = "Leo's agent", user: str = "Leo") -> dict:
    return {
        "platform": "telegram", "hermes_home": str(home), "agent_context": "primary",
        "user_id": "42", "user_name": user, "chat_id": "-100123", "chat_name": chat,
        "chat_type": "group", "gateway_session_key": f"agent:main:telegram:group:-100123:{chat}",
        "agent_identity": "default", "agent_workspace": "hermes",
    }


def _start(home: Path, **kwargs) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize("20261107_210000_catalog", **(kwargs or _gateway(home)))
    return provider


def test_a_home_mnemos_was_never_connected_to_gets_one_memory(tmp_path):
    home = tmp_path / "hermes"
    home.mkdir()
    first = _start(home)
    renamed = _start(home, **_gateway(home, chat="Leo's agent, renamed", user="Sam"))
    try:
        for provider in (first, renamed):
            assert provider.scope.agent_id == profile_agent_id(home)
            assert provider.scope.db_path == profile_store(home)
        assert first.scope.person_id == renamed.scope.person_id
        assert first.scope.project_scope == renamed.scope.project_scope
        written = json.loads((home / "mnemos.json").read_text())
        assert written["db_path"] == in_own_mnemos(profile_store(home)) and written["agent_id"] == profile_agent_id(home)
    finally:
        first.shutdown()
        renamed.shutdown()


def test_a_home_with_a_memory_keeps_it(tmp_path):
    # One that names all of its memory, and one that has a memory where the
    # provider kept it, left to itself. (A home that names part of one:
    # tests/test_hermes_half_named_memory.py.)
    named = tmp_path / "named"
    named.mkdir()
    (named / "mnemos.json").write_text(json.dumps({
        "agent_id": "nova", "db_path": str(tmp_path / "nova.db"), "person_id": "sam", "project_scope": "the-boat",
    }))
    kept = tmp_path / "kept"
    (kept / "mnemos").mkdir(parents=True)
    (kept / "mnemos" / "mnemos.db").write_bytes(b"")  # where the provider kept it, left to itself
    for home in (named, kept):
        before = (home / "mnemos.json").read_text() if (home / "mnemos.json").exists() else None
        provider = _start(home)
        provider.shutdown()
        after = (home / "mnemos.json").read_text() if (home / "mnemos.json").exists() else None
        assert after == before, f"{home.name}: mnemos.json changed"
    provider = _start(kept)
    try:
        assert provider.scope.db_path == str(kept / "mnemos" / "mnemos.db")
    finally:
        provider.shutdown()


def test_hermes_memory_setup_makes_mnemos_the_provider_of_one_memory(tmp_path, monkeypatch, capsys):
    saved = []
    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli.config = types.ModuleType("hermes_cli.config")
    hermes_cli.config.save_config = lambda config, **options: saved.append((json.loads(json.dumps(config)), options))
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", hermes_cli.config)
    home = tmp_path / "hermes"
    home.mkdir()

    MnemosMemoryProviderCore().post_setup(str(home), {"memory": {}, "model": {"default": "kept"}})

    assert saved == [({"memory": {"provider": "mnemos"}, "model": {"default": "kept"}}, {"merge_existing": True})]
    assert json.loads((home / "mnemos.json").read_text())["db_path"] == in_own_mnemos(profile_store(home))
    said = capsys.readouterr().out
    assert profile_agent_id(home) in said and profile_store(home) in said


def _load_plugin(monkeypatch):
    """The plugin's __init__.py, loaded the way Hermes's loader and its
    validator load it, against a Hermes that is only its MemoryProvider."""
    agent = types.ModuleType("agent")
    agent.memory_provider = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    agent.memory_provider.MemoryProvider = MemoryProvider
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.memory_provider", agent.memory_provider)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # no __pycache__ in the plugin folder
    spec = importlib.util.spec_from_file_location(
        "hermes_catalog_mnemos", PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)],
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, MemoryProvider


def test_the_plugin_hands_hermes_a_new_provider_each_time(monkeypatch):
    module, base = _load_plugin(monkeypatch)
    registered = []
    ctx = types.SimpleNamespace(register_memory_provider=registered.append)
    module.register(ctx)
    module.register(ctx)
    assert len(registered) == 2 and registered[0] is not registered[1]  # one per profile, never shared
    assert all(isinstance(p, base) and p.name == "mnemos" for p in registered)


def test_a_catalog_install_offers_nothing_scheduled_outside_hermes(tmp_path, monkeypatch):
    """Hermes installs the catalog's Mnemos into an environment it rebuilds when
    it updates and deletes when the plugin is removed. The first session used to
    offer `mnemos connect hermes --write` (upkeep, an OS scheduler job) and quiet
    hours (Hermes cron jobs), each running the mnemos in that environment: a job
    that breaks at Hermes's next update and outlives a removal."""
    from mnemos.setup import connect
    from mnemos.setup import harnesses as hs

    module, _ = _load_plugin(monkeypatch)
    registered = []
    module.register(types.SimpleNamespace(register_memory_provider=registered.append))
    home = tmp_path / "hermes"
    home.mkdir()
    provider = registered[0]
    provider.initialize("20261107_210000_first", platform="cli", hermes_home=str(home), agent_context="primary")
    monkeypatch.setattr(connect, "status", lambda *a, **k: types.SimpleNamespace(wake="set", cue="set", upkeep=False))
    try:
        assert provider._runtime.host_manages_install is True
        settle, lines = provider._runtime._other_setup_part(hs.get("hermes"))
    finally:
        provider.shutdown()
    said = "\n".join(settle + [lines or ""])
    assert settle == [], said
    assert "connect hermes" not in said and "--hours" not in said, said
    assert "Quiet hours aren't offered" in said

    # Mnemos connected by `mnemos connect hermes` (its own install) is asked as before.
    other = MnemosMemoryProviderCore()
    other.initialize("20261107_210000_other", platform="cli", hermes_home=str(home), agent_context="primary")
    try:
        assert other._runtime.host_manages_install is False
    finally:
        other.shutdown()


def test_the_plugin_folder_holds_only_what_a_reviewer_can_read():
    """What the catalog scans at the pin: source and a picture, no compiled code."""
    files = sorted(
        p.relative_to(PLUGIN).as_posix() for p in PLUGIN.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts  # git ignores these; the pin has none
    )
    assert "plugin.yaml" in files and "__init__.py" in files and "pyproject.toml" in files
    allowed = (".py", ".yaml", ".toml", ".md", ".png")
    assert all(f.endswith(allowed) for f in files), files


def test_the_plugin_is_released_with_the_mnemos_it_installs():
    """The catalog shows plugin.yaml's version beside the pin and installs
    mnemos-continuity by the range in the plugin's pyproject. A release that
    moved one without the others would list one version and install another,
    or nothing at all."""
    import re

    import yaml
    from packaging.requirements import Requirement

    def version(text: str) -> str:
        return re.search(r'^version = "([^"]+)"$', text, re.M).group(1)

    released = version((PLUGIN.parent / "pyproject.toml").read_text(encoding="utf-8"))
    project = (PLUGIN / "pyproject.toml").read_text(encoding="utf-8")
    manifest = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
    assert manifest["version"] == version(project) == released
    (wanted,) = [Requirement(r) for r in re.findall(r'"(mnemos-continuity[^"]*)"', project)]
    assert wanted.specifier.contains(released), f"the plugin installs {wanted}, not {released}"
    assert re.fullmatch(r">=\d+\.\d+\.\d+", manifest["requires_hermes"])  # a SemVer floor (catalog rule 14)


def test_the_plugin_opens_as_connect_knows_it():
    from mnemos.integrations.hermes.installer import _CATALOG_OPENING

    assert (PLUGIN / "__init__.py").read_text(encoding="utf-8").startswith(_CATALOG_OPENING)


def test_connect_keeps_the_catalog_plugin_and_still_connects(tmp_path, monkeypatch):
    """`mnemos connect hermes` after a catalog install: the plugin stays as
    Hermes installed it (Hermes updates it), and the rest is connected. It used
    to call the folder someone else's, warn, and make nothing the provider."""
    import shutil

    import yaml

    from mnemos.integrations.hermes import installer

    monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("yes", ""))
    home = tmp_path / "hermes"
    folder = home / "plugins" / "mnemos"
    shutil.copytree(PLUGIN, folder)
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}

    result = installer.install_hermes_plugin(hermes_home=home, mode=installer.PROVIDER_MODE, activate=True)

    assert {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()} == before
    assert not [w for w in result.warnings if "differs" in w], result.warnings
    assert any("plugin catalog" in note for note in result.notes), result.notes
    assert yaml.safe_load((home / "config.yaml").read_text())["memory"]["provider"] == "mnemos"
    assert json.loads((home / "mnemos.json").read_text())["db_path"] == in_own_mnemos(profile_store(home))
    assert installer._holds_mnemos_plugin(folder)
    assert not installer.connect_would_change(home)
