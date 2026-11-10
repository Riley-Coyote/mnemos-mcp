"""A session that starts while another process is writing still wakes.

A wake counts a session and spends what shows once, so it writes. With the
store's write lock held past the wait SQLite gives (another process deep in
one long write: a migration, a VACUUM, a stuck one), the wake raised, and
Hermes builds its prompt once: the whole session ran with no Mnemos in it,
no rules and no memory, though every read would have answered.

Upkeep itself is not such a writer: on 1,500 memories a whole cycle held the
lock 37 times, 25 ms at the longest.

Now that session starts on what a read gives, as a run nobody is in does:
who the agent is with and where it left off, nothing counted.

A scheduled run (cron) or a subagent's, which only reads at its start, had
no such fall-back: in a store that couldn't be opened to write, its read
raised too, and that run had no Mnemos in it. It now opens the store to read.
"""

from __future__ import annotations

import sqlite3

import pytest

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.simple_runtime import MnemosRuntime


def _provider(tmp_path) -> MnemosMemoryProviderCore:
    return MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user", project_scope="global",
    ))


def _a_memory_with_a_handoff(tmp_path) -> None:
    earlier = _provider(tmp_path)
    earlier.initialize("cli-0", hermes_home=str(tmp_path), platform="cli")
    earlier.handle_tool_call("mnemos_handoff", {"text": "We were sorting the tide tables by harbour."})
    earlier.shutdown()


def test_a_wake_that_cant_write_reads(tmp_path):
    _a_memory_with_a_handoff(tmp_path)
    provider = _provider(tmp_path)
    provider.initialize("cli-1", hermes_home=str(tmp_path), platform="cli")
    provider._runtime._store._get_conn().execute("PRAGMA busy_timeout=50")  # the store's own is 5 seconds
    writing = sqlite3.connect(tmp_path / "a.db", isolation_level=None)
    try:
        writing.execute("BEGIN IMMEDIATE")  # another process, deep in one long write

        block = provider.system_prompt_block()

        assert "mnemos_recall" in block, "the session got no rules"
        assert "sorting the tide tables" in block, "the session got none of its memory"
    finally:
        writing.execute("ROLLBACK")
        writing.close()
        provider.shutdown()


def test_a_wake_in_a_store_that_couldnt_be_opened_to_write_reads(tmp_path, monkeypatch):
    """A new conversation in that same while: opening a store to write records
    this code's version in it, so it waited too, and then every call raised."""
    _a_memory_with_a_handoff(tmp_path)
    opens = MnemosRuntime._ensure_init

    def no_room_for_a_writer(self):
        if not self._read_only:
            raise sqlite3.OperationalError("database is locked")
        return opens(self)

    monkeypatch.setattr(MnemosRuntime, "_ensure_init", no_room_for_a_writer)
    provider = _provider(tmp_path)
    try:
        try:
            provider.initialize("cli-1", hermes_home=str(tmp_path), platform="cli")
        except sqlite3.OperationalError:
            pass  # as Hermes does: it logs the failed start and goes on calling

        block = provider.system_prompt_block()

        assert "mnemos_recall" in block and "sorting the tide tables" in block
    finally:
        provider.shutdown()


@pytest.mark.parametrize("run", ["cron", "subagent"])
def test_a_run_nobody_is_in_reads_a_store_that_couldnt_be_opened_to_write(tmp_path, monkeypatch, run):
    _a_memory_with_a_handoff(tmp_path)
    opens = MnemosRuntime._ensure_init

    def no_room_for_a_writer(self):
        if not self._read_only:
            raise sqlite3.OperationalError("database is locked")
        return opens(self)

    monkeypatch.setattr(MnemosRuntime, "_ensure_init", no_room_for_a_writer)
    provider = _provider(tmp_path)
    try:
        try:
            provider.initialize("job-1", hermes_home=str(tmp_path), platform=run, agent_context=run)
        except sqlite3.OperationalError:
            pass  # as Hermes does: it logs the failed start and goes on calling

        block = provider.system_prompt_block()

        assert "# Mnemos Identity Continuity" in block
        assert "sorting the tide tables" in block, "the run got none of its memory"
    finally:
        provider.shutdown()


def test_a_wake_that_can_write_wakes_as_ever(tmp_path):
    _a_memory_with_a_handoff(tmp_path)
    provider = _provider(tmp_path)
    try:
        provider.initialize("cli-1", hermes_home=str(tmp_path), platform="cli")
        woke = []
        wake = provider._runtime.context
        provider._runtime.context = lambda **options: woke.append(options) or wake(**options)

        assert "sorting the tide tables" in provider.system_prompt_block()
        assert len(woke) == 1
    finally:
        provider.shutdown()
