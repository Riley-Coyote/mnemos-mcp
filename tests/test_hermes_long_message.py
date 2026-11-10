"""What comes up with a message is memory, and none of the message.

Recall heads its answer with the query it was asked, and the provider cut
that heading off at its first line. A message of several lines came back from
its second line on, under "from memory", as if it had been remembered; a long
one filled the room there was and left none for what had been.

And a long message is looked up by its start and its end. Hermes hands over
the whole message each turn, however much was pasted into it, and every word
of it was searched before the turn began: on 1,500 memories, 18 ms for a
question, 1.3 seconds with 50,000 characters pasted in, 2.4 with 100,000.
With a provider chosen for meaning search, all of it went there too. The
recall tool takes 4,096 characters; what comes up by itself now searches no
more than that: the start of the message and its end, where the person's own
words are.
"""

from __future__ import annotations

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.simple_tools import MAX_QUERY_CHARS

_PASTED = "\n".join(f"row{n} value{n * 7} status{n % 13}" for n in range(6000))  # ~170,000 characters


def _provider(tmp_path) -> tuple[MnemosMemoryProviderCore, list[str]]:
    provider = MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user", project_scope="global",
    ))
    provider.initialize("cli-1", hermes_home=str(tmp_path), platform="cli")
    for fact in ("The kiln is fired on Tuesdays.", "The spare key is kept under the blue pot."):
        provider.handle_tool_call("mnemos_capture", {"content": fact})
    searched: list[str] = []
    recall = provider._runtime._recall_own

    def watched(query, **options):
        searched.append(query)
        return recall(query, **options)

    provider._runtime._recall_own = watched
    return provider, searched


def test_none_of_a_message_comes_back_as_memory(tmp_path):
    provider, _searched = _provider(tmp_path)
    try:
        brought = provider.prefetch(
            "When is the kiln fired?\nThe forecast says rain on Thursday.\nAnd where is the spare key kept?",
            session_id="cli-1",
        )
    finally:
        provider.shutdown()

    assert "fired on Tuesdays" in brought and "under the blue pot" in brought
    assert "forecast" not in brought and "where is the spare key kept" not in brought, brought


def test_a_long_message_is_looked_up_by_its_start_and_its_end(tmp_path):
    provider, searched = _provider(tmp_path)
    try:
        message = f"When is the kiln fired? Here is the log:\n{_PASTED}\nAnd where is the spare key kept?"
        brought = provider.prefetch(message, session_id="cli-1")
    finally:
        provider.shutdown()

    (query,) = searched
    assert len(query) <= MAX_QUERY_CHARS, len(query)
    assert query.startswith("When is the kiln fired?") and query.endswith("where is the spare key kept?")
    assert "fired on Tuesdays" in brought and "under the blue pot" in brought
    assert "row" not in brought and "value" not in brought, "what was pasted came back as memory"
    # Whole words: a word cut in two is another word, or none.
    assert set(query.split()) <= set(message.split())


def test_a_message_the_tool_would_take_is_looked_up_whole(tmp_path):
    provider, searched = _provider(tmp_path)
    try:
        message = "When is the kiln fired? " + _PASTED[: MAX_QUERY_CHARS - 100]
        provider.prefetch(message, session_id="cli-1")
        assert searched == [message]

        # One word with no end to it (a key, an image as text) is still cut.
        provider.prefetch("x" * 50_000, session_id="cli-1")
        assert len(searched[-1]) <= MAX_QUERY_CHARS
    finally:
        provider.shutdown()


def test_a_memory_that_quotes_the_empty_answer_still_comes_up(tmp_path):
    """Nothing found was told by its sentence being anywhere in the answer, so
    a memory holding that sentence silenced every answer it was part of."""
    provider, _searched = _provider(tmp_path)
    try:
        provider.handle_tool_call("mnemos_capture", {
            "content": 'The old search box answered "No relevant continuity found." to every question about the kiln.',
        })
        brought = provider.prefetch("What did the old search box answer about the kiln?", session_id="cli-1")
        assert "old search box answered" in brought

        assert provider.prefetch("zzyzx quuxing flibbertigibbet", session_id="cli-1") == ""
    finally:
        provider.shutdown()
