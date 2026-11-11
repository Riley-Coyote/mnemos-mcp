"""Existing shared graphs upgrade before writes without inventing old origins."""
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from mnemos import shared_memory as shared
from mnemos.core.engram import Engram
from mnemos.store.sqlite_store import EngramStore, SCHEMA_VERSION


@pytest.fixture
def legacy_shared(tmp_path, monkeypatch):
    target = tmp_path / "shared-memory.db"
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(target))
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    memory = Engram(content="The telescope lenses are in the west cabinet.",
                    owner_agent_id="writer", author_kind="agent", author_model="original-model", visibility="shared")
    memory.id = shared.PREFIX + memory.id
    with closing(EngramStore(target)) as store:
        store.save_engram(memory)
    with sqlite3.connect(target) as conn:
        for table in ("engrams", "hypomnema_entries", "journal_entries", "notes"):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN origin_json")
        conn.execute("UPDATE meta SET value='19' WHERE key='schema_version'")
    return target, memory


def test_shared_correction_upgrades_and_is_recalled_in_another_process(legacy_shared):
    target, memory = legacy_shared
    correction = "The telescope lenses are now in the upstairs cabinet."
    result = shared.correct(memory.id, correction, action="update", agent_id="writer", model="new-model")
    assert result.startswith("Corrected shared memory."), result
    replacement_id = re.search(r"shared_engram_\w+", result)[0]
    recalled = subprocess.run(
        [sys.executable, "-c", "from mnemos.shared_memory import recall; "
         f"print(recall({replacement_id!r}, agent_id='reader'))"],
        env=os.environ.copy(), capture_output=True, text=True, check=True,
    ).stdout
    assert correction in recalled and "writer | new-model" in recalled
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == (str(SCHEMA_VERSION),)
        assert conn.execute("SELECT content, owner_agent_id, author_model, visibility, origin_json, state "
                            "FROM engrams WHERE id=?", (memory.id,)).fetchone() == (
                                memory.content, "writer", "original-model", "shared", "{}", "archived")
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    backups = list((target.parent / "backups").glob(f"shared-memory.pre-v{SCHEMA_VERSION}-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == ("19",)
        assert conn.execute("SELECT content, state FROM engrams WHERE id=?", (memory.id,)).fetchone() == (memory.content, "active")


def test_shared_recall_upgrades_before_reinforcing_a_dormant_memory(legacy_shared):
    target, memory = legacy_shared
    with sqlite3.connect(target) as conn:
        conn.execute("UPDATE engrams SET state='dormant', accessibility=.03 WHERE id=?", (memory.id,))
    assert memory.content in shared.recall("telescope lenses", agent_id="reader")
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT state, origin_json FROM engrams WHERE id=?", (memory.id,)).fetchone() == ("active", "{}")


def test_shared_upgrade_requires_a_recovery_backup(legacy_shared, monkeypatch):
    target, memory = legacy_shared

    def unavailable(*args, **kwargs):
        raise OSError("Recovery destination unavailable")

    monkeypatch.setattr("mnemos.backup.create_backup", unavailable)
    result = shared.correct(memory.id, "Changed words", action="update", agent_id="writer", model="new-model")
    assert result == "Shared memory unavailable. Nothing changed."
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == ("19",)
        assert "origin_json" not in {row[1] for row in conn.execute("PRAGMA table_info(engrams)")}
        assert conn.execute("SELECT content, state FROM engrams WHERE id=?", (memory.id,)).fetchone() == (memory.content, "active")


def test_notebook_does_not_migrate_legacy_shared_memory(legacy_shared):
    target, memory = legacy_shared
    before = target.read_bytes()
    result = shared.notebook()
    assert result["status"] == "ready"
    assert result["rows"][0]["content"] == memory.content
    assert target.read_bytes() == before
    assert not (target.parent / "backups").exists()
