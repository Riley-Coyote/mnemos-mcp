"""Two backups asked for at once leave nothing held.

A backup holds a read open on each memory until the copy is done, one read
for a memory: the last one's is let go before the next is taken. Asked for by
two threads at once (Hermes's dashboard taking two requests, a backup beside a
quick snapshot), both let go of the last one, both took a read, and the second
stored over the first. The first was never closed: a read held on the memory
for the hour, with its wait, so SQLite couldn't fold the memory's log back in
meanwhile and the log grew with every save.

Now a hold stored where one already is closes the one it displaces, under the
holds' lock.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.integrations.hermes import provider as provider_module


def _waits() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == "mnemos-backup-hold" and thread.is_alive()]


def test_a_second_backup_at_the_same_moment_leaves_no_read_behind(tmp_path, monkeypatch):
    store = Path.home() / ".mnemos" / "kept.db"
    config = HermesMnemosConfig(db_path=str(store), agent_id="a", person_id="user", project_scope="global")
    talking = MnemosMemoryProviderCore(config)
    talking.initialize("session-1", hermes_home=str(tmp_path / "hermes"), platform="cli")
    assert json.loads(talking.handle_tool_call("mnemos_capture", {"content": "The kiln fires on Fridays."}))["ok"]
    talking.shutdown()

    # The other backup gets in between this one's letting go and its storing:
    # its own hold is taken first, at the moment this one makes its wait.
    timer = threading.Timer
    the_other = []

    def at_the_same_moment(*args, **kwargs):
        if not the_other:
            the_other.append(True)
            provider_module._hold_still_for_a_backup(store.resolve())
        return timer(*args, **kwargs)

    monkeypatch.setattr(provider_module.threading, "Timer", at_the_same_moment)
    provider_module._hold_still_for_a_backup(store.resolve())
    monkeypatch.undo()

    assert the_other and len(provider_module._backup_holds) == 1
    provider_module._let_go_of_backups()
    for thread in _waits():
        thread.join(timeout=2)
    assert not _waits(), "a wait was left for the hour"

    writer = sqlite3.connect(store)
    try:
        writer.execute("CREATE TABLE filler (words TEXT)")
        writer.executemany("INSERT INTO filler VALUES (?)", [("x" * 1000,) for _ in range(200)])
        writer.commit()
        busy, in_log, folded = writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        writer.close()
    assert busy == 0, "a read is still held on the memory: its log can't be folded in"
