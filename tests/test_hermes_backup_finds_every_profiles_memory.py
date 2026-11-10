"""A backup names every profile's memory, however the profile names it.

``hermes backup`` asks the provider of one profile what to take, and Mnemos
names every profile's memory, since the backup is of every profile. The other
profiles' memories were found only through their ``mnemos.json``. A profile
that names its memory with ``MNEMOS_DB_PATH`` in its own ``.env`` has none
there (the first session settles nothing for it), so a backup taken from
another profile left that memory out, without a word.

Now there is one answer to "which memory does this home open", the one the
provider opens it by (``memory_file``), and the backup asks it for each
profile's home, with Hermes's answers for that profile: Hermes builds the
profile's own reader (``build_profile_secret_scope``) and is asked through it
for ``MNEMOS_DB_PATH`` alone. The plugin opens no ``.env`` itself (Nous's rule
11); Hermes reads it.
"""

from __future__ import annotations

import contextvars
import io
import json
import sys
import types
from pathlib import Path

import pytest

from mnemos.integrations.hermes import MnemosMemoryProviderCore
from mnemos.integrations.hermes import provider as provider_module


def _env_file(home: Path) -> dict[str, str]:
    path = home / ".env"
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {name.strip(): value.strip() for name, value in pairs}


@pytest.fixture
def hermes(monkeypatch):
    """Hermes 0.23.0's ``agent.secret_scope`` as it behaves: a profile's reader
    built from its ``.env`` (``build_profile_secret_scope``), bound for a task
    (``set_secret_scope``), and ``get_secret`` answering from the bound one; for
    another profile than the process's own a name it doesn't hold is unset.
    Every ``.env`` the plugin opens itself is counted."""
    bound: contextvars.ContextVar = contextvars.ContextVar("bound", default=None)
    asked: list[tuple[str, str]] = []
    built: list[str] = []
    hermes_reads = contextvars.ContextVar("hermes_reads", default=False)
    opened_by_the_plugin: list[str] = []

    def build_profile_secret_scope(home):
        built.append(str(home))
        token = hermes_reads.set(True)
        try:
            return _env_file(Path(home))
        finally:
            hermes_reads.reset(token)

    def set_secret_scope(secrets, *, profile_home=None):
        return bound.set(None if secrets is None else (secrets, profile_home))

    def reset_secret_scope(token):
        bound.reset(token)

    def get_secret(name, default=None):
        scope = bound.get()
        if scope is None:
            return _env_file(Path(provider_module.default_hermes_home())).get(name, default)
        asked.append((Path(scope[1]).name, name))
        return scope[0].get(name, default)

    module = types.ModuleType("agent.secret_scope")
    module.build_profile_secret_scope = build_profile_secret_scope
    module.set_secret_scope = set_secret_scope
    module.reset_secret_scope = reset_secret_scope
    module.get_secret = get_secret
    agent = types.ModuleType("agent")
    agent.secret_scope = module
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", module)

    real_open = io.open

    def counting_open(file, *args, **kwargs):
        if Path(str(file)).name == ".env" and not hermes_reads.get():
            opened_by_the_plugin.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", counting_open)
    yield types.SimpleNamespace(asked=asked, built=built, opened_by_the_plugin=opened_by_the_plugin)
    provider_module._let_go_of_backups()


def _a_memory(path: Path, home: Path, words: str) -> None:
    """A memory with something in it, opened as the provider opens it."""
    provider = MnemosMemoryProviderCore()
    provider.initialize("session-1", hermes_home=str(home), platform="cli")
    assert Path(provider.scope.db_path) == path
    assert json.loads(provider.handle_tool_call("mnemos_capture", {"content": words}))["ok"]
    provider.shutdown()


def test_a_backup_takes_the_memory_a_profile_names_in_its_own_env(hermes, monkeypatch):
    root = Path.home() / ".hermes"
    root.mkdir(parents=True)
    work = root / "profiles" / "work"
    work.mkdir(parents=True)
    by_env = Path.home() / ".mnemos" / "work-by-env.db"
    (work / ".env").write_text(f"MNEMOS_DB_PATH={by_env}\nSOME_PROVIDER_KEY=sk-not-for-mnemos\n")
    monkeypatch.setenv("HERMES_HOME", str(work))
    _a_memory(by_env, work, "The work profile keeps the survey dates.")
    assert not (work / "mnemos.json").exists() or "db_path" not in json.loads((work / "mnemos.json").read_text())
    monkeypatch.setenv("HERMES_HOME", str(root))
    _a_memory(Path.home() / ".mnemos" / "hermes.db", root, "The default profile keeps the harbour log.")
    hermes.asked.clear()
    hermes.opened_by_the_plugin.clear()

    named = MnemosMemoryProviderCore().backup_paths()  # as `hermes backup` asks, from the default profile

    assert sorted(Path(path).name for path in named) == [
        "hermes.db", "hermes.db-wal", "work-by-env.db", "work-by-env.db-wal",
    ]
    assert Path(named[0]).name == "hermes.db", "the profile the backup was run from comes first"
    assert ("work", "MNEMOS_DB_PATH") in hermes.asked
    assert {name for _, name in hermes.asked} == {"MNEMOS_DB_PATH"}, "only Mnemos's own name is asked for"
    assert hermes.opened_by_the_plugin == [], "the plugin opened a .env itself"


def test_a_profile_named_in_its_mnemos_json_is_still_found_so(hermes, monkeypatch):
    root = Path.home() / ".hermes"
    root.mkdir(parents=True)
    twin = root / "profiles" / "twin"
    twin.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(twin))
    _a_memory(Path.home() / ".mnemos" / "hermes-twin.db", twin, "The twin profile keeps the tide tables.")

    monkeypatch.setenv("HERMES_HOME", str(root))
    named = MnemosMemoryProviderCore().backup_paths()

    assert sorted(Path(path).name for path in named) == ["hermes-twin.db", "hermes-twin.db-wal"]


def test_a_profile_hermes_cant_answer_for_goes_by_its_mnemos_json(hermes, monkeypatch):
    """Hermes raising for one profile (an administrator's file it can't read, a
    secret source that failed) left that profile out of the backup."""
    root = Path.home() / ".hermes"
    root.mkdir(parents=True)
    twin = root / "profiles" / "twin"
    twin.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(twin))
    _a_memory(Path.home() / ".mnemos" / "hermes-twin.db", twin, "The twin profile keeps the tide tables.")

    def refuses(*args, **kwargs):
        raise RuntimeError("Hermes could not read this profile's secrets")

    monkeypatch.setattr(sys.modules["agent.secret_scope"], "build_profile_secret_scope", refuses)
    monkeypatch.setenv("HERMES_HOME", str(root))
    named = MnemosMemoryProviderCore().backup_paths()

    assert sorted(Path(path).name for path in named) == ["hermes-twin.db", "hermes-twin.db-wal"]
