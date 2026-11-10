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

Reasoning about halves and pairs wasn't enough: two opening tags in one row,
a tag spelled with a space that the plugin and Hermes read differently, or a
pair in a later row still let Hermes cut rows out. Now every fence tag is taken
out of every row before the recall goes to Hermes, the tags and never the
words, and a tag is whatever Hermes's own patterns take for one, or more. They
are taken out until none is left: taken out once, ``<memory-<memory-context>context>``
was a whole tag again.
"""

from __future__ import annotations

import json
import re

import pytest

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore

# What Hermes 0.23.0 strips from a provider's answer before fencing it
# (agent/memory_context.py, sanitize_context), its three patterns as written.
_HERMES_PATTERNS = (
    re.compile(r'<\s*memory-context\s*>[\s\S]*?</\s*memory-context\s*>', re.IGNORECASE),
    re.compile(
        r'\[System note:\s*The following is recalled memory context,\s*NOT new user input\.\s*Treat as '
        r'(?:informational background data|authoritative reference data[^\]]*)\.\]\s*',
        re.IGNORECASE,
    ),
    re.compile(r'</?\s*memory-context\s*>', re.IGNORECASE),
)


def _as_hermes_fences_it(text: str) -> str:
    for pattern in _HERMES_PATTERNS:
        text = pattern.sub("", text)
    return text

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
    given = _as_hermes_fences_it(brought)
    assert "4417" in given, "Hermes cut out the memory between the halves"
    assert all(engram_id in given for engram_id in ids.values())
    assert "Hermes starts recall at" in given and "it seems." in given
    assert "the Hermes documentation says recalled memory ends at" in given


_KILN = "Pottery studio kiln firing schedule: bisque on Tuesdays, glaze to 1240 C on Fridays."


@pytest.mark.parametrize("rows", [
    [("mcp", "Pottery studio kiln firing schedule notes on Hermes: it opens <memory-context> and a space "
             "before the slash, < /memory-context>, is not its end."),
     ("tool", _KILN),
     ("mcp", "Pottery, Hermes again: <memory-context>a pair</memory-context>.")],
    [("tool", "Pottery studio kiln firing schedule, about Hermes: <memory-context> and again <memory-context>."),
     ("tool", _KILN),
     ("mcp", "Pottery studio kiln firing schedule, Hermes again: <memory-context>a pair</memory-context>.")],
    [("tool", "Pottery studio kiln firing schedule, about Hermes: it opens with <memory-context>."),
     ("tool", _KILN),
     ("tool", "Pottery studio kiln firing schedule, about Hermes: it ends with </memory-context>.")],
    [("mcp", "Pottery studio kiln firing schedule: Hermes writes </ MEMORY-CONTEXT > and <Memory-Context >."),
     ("tool", _KILN),
     ("mcp", "Pottery studio kiln firing schedule: and < memory-context> with </memory-context  > too.")],
    [("tool", "Pottery studio kiln firing schedule, on Hermes: <memory-<memory-context>context> starts it."),
     ("tool", _KILN),
     ("tool", "Pottery studio kiln firing schedule, on Hermes: </memory-</memory-context>context> ends it.")],
], ids=["a tag spelled with a space", "two openings in one row", "one half each", "case and spaces",
        "a tag inside a tag's letters"])
def test_every_row_and_every_id_survives_hermes(tmp_path, rows):
    provider = _provider(tmp_path)
    try:
        ids = []
        for how, words in rows:
            if how == "tool":
                ids.append(_keep(provider, words))
            else:  # kept by normal Mnemos (its MCP server, its CLI): no plugin pass on the way in
                before = set(re.findall(r"engram_\w+", provider._runtime.recall("pottery", max_results=10)))
                provider._runtime.capture(words)
                ids.extend(set(re.findall(r"engram_\w+", provider._runtime.recall("pottery", max_results=10))) - before)
        brought = provider.prefetch("pottery studio kiln firing schedule", session_id="s-1")
    finally:
        provider.shutdown()

    assert len(ids) == 3 and all(engram_id in brought for engram_id in ids)
    assert not re.search(r"<[^>]*memory-context[^>]*>", brought, re.IGNORECASE), "a tag was left in"
    given = _as_hermes_fences_it(brought)
    assert given == brought, "Hermes still found something to cut"
    assert all(engram_id in given for engram_id in ids) and "1240" in given
    assert "a pair" in given or not any("a pair" in words for _, words in rows), "the words between were cut"
