"""A provider started again is the conversation it was.

Hermes can start a provider twice, and a call can reach one after its
``shutdown()`` (0.6.7 starts it again with what Hermes said the first time).
Three things didn't come back with it:

- who signs. The provider remembered the model Hermes had named and told only
  a *change* of model to its runtime; the new runtime was never told, and
  everything kept from then on was unsigned.
- which conversation. On the command line a compression goes on as the same
  conversation under a new session id; started again, it was taken for a new
  one, and its handoff for another conversation's.
- what had been recalled. A recall kept from before the restart was served
  again by the store's revision, which a new connection counts from the start:
  a memory another process had forgotten meanwhile came back with a message.

And a start the store was too busy for (another process writing) was told who
signs only after the store opened, so never: it went on working at the next
call, unsigned.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.simple_runtime import MnemosRuntime


def _provider(tmp_path) -> MnemosMemoryProviderCore:
    return MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user", project_scope="global",
    ))


def _call(provider: MnemosMemoryProviderCore, tool: str, **args) -> str:
    reply = json.loads(provider.handle_tool_call(tool, args))
    assert reply["ok"], reply
    return reply["result"]


def _signed(tmp_path, words: str) -> str:
    conn = sqlite3.connect(tmp_path / "a.db")
    try:
        return conn.execute("SELECT author_model FROM engrams WHERE content = ?", (words,)).fetchone()[0] or ""
    finally:
        conn.close()


def test_what_is_kept_after_a_second_start_is_still_signed(tmp_path):
    provider = _provider(tmp_path)
    try:
        provider.initialize("cli-1", hermes_home=str(tmp_path), platform="cli")
        provider.on_turn_start(1, "hello", model="some/model-1")
        _call(provider, "mnemos_capture", content="Kept in the first start.")

        provider.initialize("cli-1", hermes_home=str(tmp_path), platform="cli")  # started twice; no model named
        _call(provider, "mnemos_capture", content="Kept after the second start.")

        provider.shutdown()
        _call(provider, "mnemos_capture", content="Kept by a call that came after shutdown.")

        provider.on_turn_start(4, "hello again", model="some/model-2")  # a switch still signs from then on
        _call(provider, "mnemos_capture", content="Kept after the model changed.")
    finally:
        provider.shutdown()

    assert _signed(tmp_path, "Kept in the first start.") == "some/model-1"
    assert _signed(tmp_path, "Kept after the second start.") == "some/model-1"
    assert _signed(tmp_path, "Kept by a call that came after shutdown.") == "some/model-1"
    assert _signed(tmp_path, "Kept after the model changed.") == "some/model-2"


def test_a_start_the_store_was_too_busy_for_still_signs(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("model:\n  default: some/model-1\n")
    opens = MnemosRuntime._ensure_init
    busy = [True]

    def too_busy_once(self):
        if busy.pop() if busy else False:
            raise sqlite3.OperationalError("database is locked")
        return opens(self)

    monkeypatch.setattr(MnemosRuntime, "_ensure_init", too_busy_once)
    provider = _provider(tmp_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            provider.initialize("cli-1", hermes_home=str(tmp_path), platform="cli")
        _call(provider, "mnemos_capture", content="Kept once the store was free.")
    finally:
        provider.shutdown()

    assert _signed(tmp_path, "Kept once the store was free.") == "some/model-1"


def test_a_compressed_conversation_started_again_is_the_same_one(tmp_path):
    provider = _provider(tmp_path)
    try:
        provider.initialize("cli-1", hermes_home=str(tmp_path), platform="cli")
        began = provider.scope.conversation
        _call(provider, "mnemos_handoff", text="We were sorting the tide tables by harbour.")
        provider.on_session_switch("cli-2", parent_session_id="cli-1", reason="compression")
        assert provider.scope.conversation == began

        provider.shutdown()
        wake = provider.system_prompt_block()  # a call after shutdown
        assert provider.scope.conversation == began, "taken for a new conversation"
        assert "sorting the tide tables" in wake

        # And a new session on the same provider is a new conversation, as before.
        provider.on_session_switch("cli-3", parent_session_id="cli-2", reset=True)
        assert provider.scope.conversation != began
        provider.shutdown()
        provider.system_prompt_block()
        assert provider.scope.conversation != began
    finally:
        provider.shutdown()


def test_a_second_start_serves_nothing_recalled_before_it(tmp_path):
    asked = "where is the spare key kept"
    first = _provider(tmp_path)
    first.initialize("cli-1", hermes_home=str(tmp_path), platform="cli")
    _call(first, "mnemos_capture", content="The spare key is kept under the blue pot.")
    first.shutdown()

    job = _provider(tmp_path)
    try:
        job.initialize("cron-9", hermes_home=str(tmp_path), platform="cron", agent_context="cron")
        assert "blue pot" in job.prefetch(asked, session_id="cron-9")

        # Meanwhile a conversation, in another process, lets the memory go.
        other = _provider(tmp_path)
        other.initialize("cli-2", hermes_home=str(tmp_path), platform="cli")
        conn = sqlite3.connect(tmp_path / "a.db")
        (memory_id,) = conn.execute("SELECT id FROM engrams WHERE content LIKE 'The spare key%'").fetchone()
        conn.close()
        _call(other, "mnemos_correct", target_id=memory_id, action="forget")
        other.shutdown()

        job.initialize("cron-9", hermes_home=str(tmp_path), platform="cron", agent_context="cron")
        assert "blue pot" not in job.prefetch(asked, session_id="cron-9"), "a forgotten memory came back"
    finally:
        job.shutdown()
