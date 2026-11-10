"""A backup of Hermes holds the agent's memory, whole, whatever is going on.

``hermes backup`` asks the memory provider which files outside Hermes's folder
to take (``backup_paths``), archives its own folder, and only then copies those
files, as they stand. In a big home that is minutes later. Hermes puts them back
the same way: ``hermes import`` writes each one as a file.

Mnemos named the memory after folding SQLite's log into it, and its log if one
was there. That left three ways for a backup to go wrong, each with a
conversation open or one that ended badly:

- the conversation went on, and SQLite folded its log back into the memory's
  file whenever it liked, under the copy too;
- the conversation ended before the copy, its log went with it, and Hermes
  called the backup incomplete for a file it had been told to take;
- with no conversation open there was no log to take, and a memory restored
  beside the log of one that ended badly is read through that log.

Now the memory is kept as it was when it was named until the backup's process
ends (a read left open: in SQLite's write-ahead mode nothing is written back
into the file under one, and nobody waits on it), and its log always goes with
it, empty when everything is in the file.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.integrations.hermes import provider as provider_module


def _config(name: str = "kept") -> HermesMnemosConfig:
    # ~ is the test's own home (conftest): outside the Hermes folder, as a real memory is.
    return HermesMnemosConfig(
        db_path=str(Path.home() / ".mnemos" / f"{name}.db"), agent_id="a", person_id="user", project_scope="global",
    )


def _talking(tmp_path, config: HermesMnemosConfig) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore(config)
    provider.initialize("session-1", hermes_home=str(tmp_path / "hermes"), platform="cli")
    return provider


def _keep(provider: MnemosMemoryProviderCore, words: str) -> None:
    assert json.loads(provider.handle_tool_call("mnemos_capture", {"content": words}))["ok"]


def _memories(path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return [row[0] for row in conn.execute("SELECT content FROM engrams")]
    finally:
        conn.close()


def _digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _copied(named: list[str], into: Path) -> Path:
    """What Hermes does with what it was named: each file, as it stands."""
    into.mkdir()
    for path in named:
        shutil.copy(path, into / Path(path).name)
    return into / Path(named[0]).name


def test_a_memory_named_for_a_backup_stays_as_it_was_until_copied(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    config = _config()
    store = Path(config.db_path)
    talking = _talking(tmp_path, config)
    _keep(talking, "The spare key is under the blue pot.")

    named = MnemosMemoryProviderCore(config).backup_paths()
    assert [Path(path).name for path in named] == ["kept.db", "kept.db-wal"]
    as_named = _digest(store)

    # The conversation goes on, far past where SQLite folds its log back by
    # itself (a thousand pages), and then it ends.
    busy = sqlite3.connect(store)
    busy.execute("CREATE TABLE filler (words TEXT)")
    busy.executemany("INSERT INTO filler VALUES (?)", [("x" * 3000,) for _ in range(3000)])
    busy.commit()
    busy.close()
    _keep(talking, "The bell is rung at noon.")
    talking.shutdown()

    assert _digest(store) == as_named, "the memory's file changed under the backup"
    assert all(Path(path).is_file() for path in named), "a file the backup was told to take is gone"

    # Both files, copied as they stand, are the whole memory; and the memory's
    # file by itself is the memory as it was when it was named.
    both = _memories(_copied(named, tmp_path / "both"))
    assert any("blue pot" in words for words in both) and any("rung at noon" in words for words in both)
    alone = _memories(_copied(named[:1], tmp_path / "alone"))
    assert any("blue pot" in words for words in alone)

    # Let go of, the log is folded in and cleared away as ever.
    provider_module._let_go_of_backups()
    assert _digest(store) != as_named and not Path(named[1]).exists()
    assert any("rung at noon" in words for words in _memories(store))


def test_a_backup_carries_the_memorys_own_log_when_nothing_is_open(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    config = _config()
    talking = _talking(tmp_path, config)
    _keep(talking, "The spare key is under the blue pot.")
    talking.shutdown()
    assert not Path(config.db_path + "-wal").exists()  # ended well: everything is in the file

    named = MnemosMemoryProviderCore(config).backup_paths()
    assert [Path(path).name for path in named] == ["kept.db", "kept.db-wal"]
    assert Path(named[1]).stat().st_size == 0
    backup = tmp_path / "backup"
    _copied(named, backup)

    # Where it is restored, another memory's conversation ended badly: its
    # file is there, with a log that was never folded in and the log's index.
    other = _config("other")
    ended_badly = _talking(tmp_path, other)
    _keep(ended_badly, "A memory of somewhere else entirely.")
    target = tmp_path / "target"
    target.mkdir()
    for left_behind in ("", "-wal", "-shm"):
        shutil.copy(other.db_path + left_behind, target / f"kept.db{left_behind}")
    assert Path(other.db_path + "-wal").stat().st_size > 0
    ended_badly.shutdown()

    # Hermes's import: each file of the backup, put back as a file.
    for name in ("kept.db", "kept.db-wal"):
        shutil.copy(backup / name, target / name)
    restored = _memories(target / "kept.db")
    assert any("blue pot" in words for words in restored)
    assert not any("somewhere else" in words for words in restored)


def test_a_backup_holds_one_read_for_a_memory_and_lets_it_go(tmp_path, monkeypatch):
    """One read for each memory, however often it is asked for; and it is let
    go by itself, in a process that lives on (Hermes's dashboard), so the log
    isn't kept from folding in for good."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    config = _config()
    talking = _talking(tmp_path, config)
    _keep(talking, "The spare key is under the blue pot.")

    monkeypatch.setattr(provider_module, "_BACKUP_HOLD_SECONDS", 0.3)
    first = MnemosMemoryProviderCore(config).backup_paths()
    second = MnemosMemoryProviderCore(config).backup_paths()
    assert first == second and len(provider_module._backup_holds) == 1
    for _ in range(100):
        if not provider_module._backup_holds:
            break
        time.sleep(0.05)
    assert not provider_module._backup_holds, "the memory was never let go"

    # Nothing waits behind it, held or not: the conversation keeps what it's given.
    _keep(talking, "The bell is rung at noon.")
    talking.shutdown()
    assert any("rung at noon" in words for words in _memories(config.db_path))


def _a_profile(home: Path, words: str) -> None:
    """A profile that has had a conversation: its settings in its own folder,
    its memory in ~/.mnemos, as the first session leaves them."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("memory:\n  provider: mnemos\n")
    provider = MnemosMemoryProviderCore()
    provider.initialize("session-1", hermes_home=str(home), platform="cli")
    _keep(provider, words)
    provider.shutdown()


@pytest.mark.parametrize("asked_from", ["the root", "a profile"])
def test_a_backup_takes_every_profiles_memory(monkeypatch, asked_from):
    """``hermes backup`` archives the whole of Hermes's folder, every profile's
    part of it, and asks one provider what else to take: the one of the profile
    it was run from. Mnemos named that profile's memory. The other profiles'
    settings were in the backup, and their memories weren't."""
    root = Path.home() / ".hermes"
    _a_profile(root, "The default profile keeps the harbour log.")
    _a_profile(root / "profiles" / "work", "The work profile keeps the survey dates.")
    _a_profile(root / "profiles" / "twin", "The twin profile keeps the tide tables.")
    (root / "profiles" / "bare").mkdir()  # a profile Mnemos was never set up in

    here = root if asked_from == "the root" else root / "profiles" / "work"
    monkeypatch.setenv("HERMES_HOME", str(here))
    named = MnemosMemoryProviderCore().backup_paths()

    mine = "hermes.db" if asked_from == "the root" else "hermes-work.db"
    assert Path(named[0]).name == mine, "the profile the backup was run from comes first"
    assert sorted(Path(path).name for path in named) == [
        "hermes-twin.db", "hermes-twin.db-wal", "hermes-work.db", "hermes-work.db-wal", "hermes.db", "hermes.db-wal",
    ]
    assert len(provider_module._backup_holds) == 3
    kept = {Path(path).name: _memories(path) for path in named if path.endswith(".db")}
    assert any("survey dates" in words for words in kept["hermes-work.db"])
    assert any("tide tables" in words for words in kept["hermes-twin.db"])
    assert any("harbour log" in words for words in kept["hermes.db"])


def test_a_backup_names_no_memory_twice_and_none_inside_hermess_folder(monkeypatch):
    """Two profiles pointed at one memory name it once. A memory kept inside
    Hermes's folder, as it was before it moved to ~/.mnemos, is in the backup
    already, whichever profile's folder it is in."""
    root = Path.home() / ".hermes"
    _a_profile(root, "The default profile keeps the harbour log.")
    shared_with = root / "profiles" / "echo"
    shared_with.mkdir(parents=True)
    (shared_with / "mnemos.json").write_text(json.dumps({
        "db_path": str(Path.home() / ".mnemos" / "hermes.db"), "agent_id": "hermes", "hermes_home": str(shared_with),
    }))
    inside = root / "profiles" / "old"
    (inside / "mnemos").mkdir(parents=True)
    shutil.copy(Path.home() / ".mnemos" / "hermes.db", inside / "mnemos" / "mnemos.db")
    (inside / "mnemos.json").write_text(json.dumps({
        "db_path": "$HERMES_HOME/mnemos/mnemos.db", "agent_id": "hermes-old", "hermes_home": str(inside),
    }))

    monkeypatch.setenv("HERMES_HOME", str(root))
    named = MnemosMemoryProviderCore().backup_paths()
    assert [Path(path).name for path in named] == ["hermes.db", "hermes.db-wal"]


def _waits() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == "mnemos-backup-hold"]


def test_asked_again_a_backup_leaves_no_wait_behind(tmp_path, monkeypatch):
    """Each read is let go by a wait of its own, an hour long. Asked for again
    (a backup every night from a process that stays up), the read was replaced
    and its wait stayed: a thread for each time, for the hour."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    config = _config()
    talking = _talking(tmp_path, config)
    _keep(talking, "The spare key is under the blue pot.")

    for _ in range(4):
        MnemosMemoryProviderCore(config).backup_paths()
    for _ in range(100):
        if len(_waits()) <= 1:
            break
        time.sleep(0.02)
    assert len(_waits()) == 1 and len(provider_module._backup_holds) == 1

    provider_module._let_go_of_backups()
    for _ in range(100):
        if not _waits():
            break
        time.sleep(0.02)
    assert not _waits()
    talking.shutdown()


def test_a_memory_that_isnt_in_write_ahead_mode_is_named_and_not_held(tmp_path, monkeypatch):
    """Where SQLite keeps no log (a filesystem that can't), a read left open
    would keep every save waiting. The memory is named, and nothing is held."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    config = _config()
    talking = _talking(tmp_path, config)
    _keep(talking, "The spare key is under the blue pot.")
    talking.shutdown()
    plain = sqlite3.connect(config.db_path)
    assert plain.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    plain.close()

    named = MnemosMemoryProviderCore(config).backup_paths()
    assert [Path(path).name for path in named] == ["kept.db"]
    assert not provider_module._backup_holds

    writer = sqlite3.connect(config.db_path, timeout=0.2)
    writer.execute("CREATE TABLE filler (words TEXT)")
    writer.commit()
    writer.close()
