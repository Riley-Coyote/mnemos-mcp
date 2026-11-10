"""A line Hermes's own memory tool adds twice is kept once, and its removal removes it.

Hermes answers a repeated ``add`` of a line MEMORY.md already holds with
success ("Entry already exists (no duplicate added)"), and the plugin mirrors
every success, so Mnemos held the line twice. A later ``remove`` or ``replace``
then found two matches and, taking them for two different entries, retired
neither: the removed line kept coming up as memory.

Now an ``add`` whose words a mirrored entry of that target already holds keeps
nothing new, and several mirrored entries with the same words are one entry:
a ``remove`` retires them all, and a ``replace`` puts one new entry in their
place. A memory the old code already doubled is healed by its next ``remove``
or ``replace``. Entries with different words that both match are still left
alone (``test_an_ambiguous_replace_retires_nothing``).
"""

from __future__ import annotations

import sqlite3

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.integrations.hermes.provider import _MIRROR_MARK

LINE = "The landlord's new number is 555-0142."


def _provider(tmp_path) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user", project_scope="global",
    ))
    provider.initialize("s-1", hermes_home=str(tmp_path), platform="cli")
    return provider


def _in_use(tmp_path) -> list[str]:
    conn = sqlite3.connect(tmp_path / "a.db")
    try:
        found = conn.execute("SELECT content FROM engrams WHERE state != 'archived'").fetchall()
    finally:
        conn.close()
    return sorted(content.split("\n\nContext:")[0] for (content,) in found)


def _doubled_by_the_old_code(provider: MnemosMemoryProviderCore) -> None:
    """What 0.6.6 kept for an add Hermes answered twice: the line, twice."""
    context = f"{_MIRROR_MARK} memory memory. Metadata: {{}}"
    provider._capture(LINE, context=context)
    provider._capture(LINE, context=context)


def test_a_line_added_twice_is_kept_once(tmp_path):
    provider = _provider(tmp_path)
    try:
        provider.on_memory_write("add", "memory", LINE, metadata={"write_origin": "assistant_tool"})
        provider.on_memory_write("add", "memory", f"  {LINE} ", metadata={})  # Hermes trims the ends
    finally:
        provider.shutdown()

    assert _in_use(tmp_path) == [LINE]


def test_the_same_line_in_the_other_target_is_its_own_entry(tmp_path):
    provider = _provider(tmp_path)
    try:
        provider.on_memory_write("add", "memory", LINE, metadata={})
        provider.on_memory_write("add", "user", LINE, metadata={})
    finally:
        provider.shutdown()

    assert _in_use(tmp_path) == [LINE, LINE]


def test_removing_a_line_added_twice_removes_it(tmp_path):
    provider = _provider(tmp_path)
    try:
        provider.on_memory_write("add", "memory", LINE, metadata={})
        provider.on_memory_write("add", "memory", LINE, metadata={})
        provider.on_memory_write("remove", "memory", "",
                                 metadata={"old_text": "landlord's new number", "previous_content": LINE})
        brought = provider.prefetch("what is the landlord's number?", session_id="s-1")
    finally:
        provider.shutdown()

    assert _in_use(tmp_path) == []
    assert "555-0142" not in brought


def test_a_memory_already_doubled_is_healed_by_its_removal(tmp_path):
    provider = _provider(tmp_path)
    try:
        _doubled_by_the_old_code(provider)
        provider.on_memory_write("remove", "memory", "", metadata={"old_text": "landlord's new number"})
    finally:
        provider.shutdown()

    assert _in_use(tmp_path) == []


def test_a_memory_already_doubled_is_healed_by_its_replacement(tmp_path):
    provider = _provider(tmp_path)
    try:
        _doubled_by_the_old_code(provider)
        provider.on_memory_write("replace", "memory", "The landlord's number is 555-0199 now.",
                                 metadata={"old_text": "landlord's new number", "previous_content": LINE})
        provider.on_memory_write("replace", "memory", "The landlord's number is 555-0100.",
                                 metadata={"old_text": "555-0199"})
    finally:
        provider.shutdown()

    assert _in_use(tmp_path) == ["The landlord's number is 555-0100."]


def test_lines_hermes_holds_apart_are_kept_apart(tmp_path):
    """Hermes's "already exists" is exact: "Ann takes…" and "ann takes…" are two
    entries there. Mnemos took them for one, and removing one removed both."""
    provider = _provider(tmp_path)
    try:
        provider.on_memory_write("add", "user", "Ann takes her tea black", metadata={})
        provider.on_memory_write("add", "user", "ann takes her tea black", metadata={})
        provider.on_memory_write("add", "user", "Bo  parks on level 3", metadata={})
        provider.on_memory_write("add", "user", "Bo parks on level 3", metadata={})
        assert _in_use(tmp_path) == [
            "Ann takes her tea black", "Bo  parks on level 3", "Bo parks on level 3", "ann takes her tea black",
        ]
        provider.on_memory_write("remove", "user", "", metadata={"old_text": "ann takes her tea black"})
        provider.on_memory_write("remove", "user", "", metadata={"old_text": "Bo parks on level 3"})
    finally:
        provider.shutdown()

    assert _in_use(tmp_path) == ["Ann takes her tea black", "Bo  parks on level 3"]


def test_the_entry_hermes_names_is_still_found_whatever_its_case_and_spacing(tmp_path):
    provider = _provider(tmp_path)
    try:
        provider.on_memory_write("add", "memory", LINE, metadata={})
        provider.on_memory_write("remove", "memory", "", metadata={"old_text": "LANDLORD'S  new number"})
    finally:
        provider.shutdown()

    assert _in_use(tmp_path) == []
