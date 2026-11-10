"""A backup names only Mnemos memories.

``backup_paths()`` named whatever file a profile's ``mnemos.json`` pointed
at: a key in ``~/.ssh``, another program's database. And it folded that
database's log into it and held a read open on it for the hour, as it does to
keep a memory still for the copy, though the program was no business of
Mnemos's.

Now a file is first opened read-only, and named only if it has Mnemos's own
tables. Anything else is left out and untouched, and the log says once which
file and why. The profile's own memory is checked the same way.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.integrations.hermes import provider as provider_module


@pytest.fixture(autouse=True)
def _let_go():
    yield
    provider_module._let_go_of_backups()


def _a_memory(path: Path) -> None:
    provider = MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(path), agent_id="a", person_id="user", project_scope="global",
    ))
    provider.initialize("session-1", hermes_home=str(Path.home() / "elsewhere"), platform="cli")
    assert json.loads(provider.handle_tool_call("mnemos_capture", {"content": "The kiln fires on Fridays."}))["ok"]
    provider.shutdown()


def _another_programs_database(path: Path) -> sqlite3.Connection:
    """A database in write-ahead mode, kept open by its program, its log full."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE cookies (host TEXT, value TEXT)")
    conn.execute("CREATE TABLE engrams (x)")  # a name alone doesn't make it a memory
    conn.executemany("INSERT INTO cookies VALUES (?, ?)", [("example.org", "x" * 200)] * 50)
    conn.commit()
    return conn


def _profile(name: str, db_path: str) -> Path:
    home = Path.home() / ".hermes" / "profiles" / name
    home.mkdir(parents=True)
    (home / "mnemos.json").write_text(json.dumps({"db_path": db_path, "agent_id": name, "hermes_home": str(home)}))
    return home


def test_a_backup_leaves_out_what_isnt_a_memory_and_leaves_it_untouched(monkeypatch, caplog):
    root = Path.home() / ".hermes"
    root.mkdir()
    memory = Path.home() / ".mnemos" / "hermes.db"
    _a_memory(memory)
    (root / "mnemos.json").write_text(json.dumps({"db_path": str(memory), "agent_id": "hermes", "hermes_home": str(root)}))
    key = Path.home() / ".ssh" / "id_ed25519"
    key.parent.mkdir()
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nnot a real one\n")
    cookies = Path.home() / "Library" / "browser" / "cookies.db"
    program = _another_programs_database(cookies)
    log = cookies.with_name("cookies.db-wal")
    log_before = log.stat().st_size
    _profile("guest", "~/.ssh/id_ed25519")
    _profile("browser", str(cookies))
    monkeypatch.setenv("HERMES_HOME", str(root))

    with caplog.at_level(logging.WARNING, logger=provider_module.logger.name):
        named = MnemosMemoryProviderCore().backup_paths()

    try:
        assert [Path(path).name for path in named] == ["hermes.db", "hermes.db-wal"]
        assert log.stat().st_size == log_before, "another program's log was folded in"
        assert str(cookies.resolve()) not in provider_module._backup_holds, "a read was held on it"
        assert key.read_text().startswith("-----BEGIN"), "the key was changed"
        said = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        assert sum(str(key.resolve()) in line for line in said) == 1
        assert sum(str(cookies.resolve()) in line for line in said) == 1
    finally:
        program.close()


def test_the_profiles_own_memory_is_checked_too(monkeypatch, caplog):
    root = Path.home() / ".hermes"
    root.mkdir()
    cookies = Path.home() / "Library" / "browser" / "cookies.db"
    program = _another_programs_database(cookies)
    log_before = cookies.with_name("cookies.db-wal").stat().st_size
    monkeypatch.setenv("HERMES_HOME", str(root))
    config = HermesMnemosConfig(db_path=str(cookies), agent_id="a", person_id="user", project_scope="global")

    with caplog.at_level(logging.WARNING, logger=provider_module.logger.name):
        named = MnemosMemoryProviderCore(config).backup_paths()

    try:
        assert named == []
        assert cookies.with_name("cookies.db-wal").stat().st_size == log_before
        assert not provider_module._backup_holds
        assert any(str(cookies.resolve()) in record.getMessage() for record in caplog.records)
    finally:
        program.close()
