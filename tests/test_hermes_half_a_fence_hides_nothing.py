"""Half of Hermes's fence in a memory hides nothing.

Hermes fences what a memory provider adds to a message in
``<memory-context>`` … ``</memory-context>``, and first strips from it
whatever it takes for a block already fenced: from an opening tag to the next
closing one (``agent/memory_context.py``). The plugin takes a whole fenced
span out of what it keeps, but one memory may hold the opening tag alone and
another the closing tag alone, as words about Hermes. Brought up together, the
two were taken for one fenced block, and Hermes cut out every memory between
them, and the end of the one before with the start of the one after: what was
left showed one memory's words under another's id.

Now a tag a row holds without its other half is taken out of that row before
the recall goes to Hermes, so nothing in one memory pairs with another. A row
that holds both halves is as it was.
"""

from __future__ import annotations

import json
import re

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore

# What Hermes 0.23.0 strips first from a provider's answer (agent/memory_context.py).
_HERMES_FENCED_BLOCK = re.compile(r"<\s*memory-context\s*>[\s\S]*?</\s*memory-context\s*>", re.IGNORECASE)

_NOTES = {
    "open": "Pottery studio door alarm keypad code: Hermes starts recall at <memory-context> it seems.",
    "code": "Pottery studio door alarm keypad: the number to press, as the landlord told Ann in March, is 4417.",
    "close": "Pottery studio door: the Hermes documentation says recalled memory ends at </memory-context> there.",
}


def _provider(tmp_path) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user", project_scope="global",
    ))
    provider.initialize("s-1", hermes_home=str(tmp_path), platform="cli")
    return provider


def _keep(provider: MnemosMemoryProviderCore, words: str) -> str:
    reply = json.loads(provider.handle_tool_call("mnemos_capture", {"content": words}))
    assert reply["ok"], reply
    return re.search(r"engram_\w+", reply["result"]).group(0)


def test_two_halves_in_two_memories_cut_out_nothing(tmp_path):
    provider = _provider(tmp_path)
    try:
        ids = {name: _keep(provider, words) for name, words in _NOTES.items()}
        brought = provider.prefetch("what is the pottery studio door alarm keypad code?", session_id="s-1")
    finally:
        provider.shutdown()

    assert all(engram_id in brought for engram_id in ids.values()), "a memory didn't come up"
    given = _HERMES_FENCED_BLOCK.sub("", brought)
    assert "4417" in given, "Hermes cut out the memory between the halves"
    assert all(engram_id in given for engram_id in ids.values())
    assert "Hermes starts recall at" in given and "it seems." in given
    assert "the Hermes documentation says recalled memory ends at" in given


def test_a_memory_that_holds_both_halves_is_as_it_was(tmp_path):
    provider = _provider(tmp_path)
    try:
        # Kept before the plugin took whole fenced spans out, or by another agent.
        provider._runtime.capture("The kiln log says <memory-context>a pasted block</memory-context> in it.")
        brought = provider.prefetch("what does the kiln log say?", session_id="s-1")
    finally:
        provider.shutdown()

    assert "<memory-context>a pasted block</memory-context>" in brought
