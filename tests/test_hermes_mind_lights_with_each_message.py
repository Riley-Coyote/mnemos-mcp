"""Inside Hermes, the notebook's mind lights on every message.

The notebook's mind page lights the memories that come to mind, as they come
(``pulse()`` in ``mnemos/companion/export.py``): what a call brought back,
read from ``memory_trace``, and what Claude Code's cue offered with a message.
Inside Hermes, what comes up by itself with a message is the provider's
prefetch, and it called the runtime's untraced recall: no row was written, so
in Hermes the page never lit on a message, which is what it is for.

Now a prefetch in a conversation leaves one row, as the cue: the ids it brought
and none of the message's words. A run nobody is in still only reads, a
message repeated at the same revision is still answered from the cache, and a
message arriving doesn't count the day as lived: that is the agent's own acts.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone

from mnemos.companion.export import Exporter, pulse
from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore

MESSAGE = "When is the kiln fired, and when is the glaze mixed?"


def _provider(tmp_path, session: str, **init) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore(HermesMnemosConfig(
        db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user", project_scope="global",
        deep_maintenance=False,
    ))
    provider.initialize(session, hermes_home=str(tmp_path), platform=init.pop("platform", "cli"), **init)
    return provider


def _kept(tmp_path) -> None:
    chat = _provider(tmp_path, "chat-0")
    try:
        for words in (
            "The kiln is fired on Tuesdays, and only when the shelves are full.",
            "The glaze is mixed the night before the kiln is fired.",
            "Mara keeps the ferry timetable on the studio door.",
        ):
            assert json.loads(chat.handle_tool_call("mnemos_capture", {"content": words}))["ok"]
        chat.system_prompt_block()
    finally:
        chat.shutdown()


def _events(tmp_path, since: str) -> list[dict]:
    exporter = Exporter.for_scope(db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user",
                                  project_scope="global")
    return pulse(exporter, since=since)["events"]


def _lived(tmp_path) -> list[str]:
    conn = sqlite3.connect(tmp_path / "a.db")
    try:
        return [day for (day,) in conn.execute("SELECT day FROM lived_days WHERE agent_id = 'a' ORDER BY day")]
    finally:
        conn.close()


def _forget_the_lived_days(tmp_path) -> None:
    conn = sqlite3.connect(tmp_path / "a.db")
    try:
        conn.execute("DELETE FROM lived_days")
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_a_message_in_a_conversation_lights_what_came_up(tmp_path):
    _kept(tmp_path)
    chat = _provider(tmp_path, "chat-1")
    try:
        chat.system_prompt_block()
        since = _now()
        came = chat.prefetch(MESSAGE, session_id="chat-1")
    finally:
        chat.shutdown()

    brought = set(re.findall(r"engram_[0-9A-Z]{26}", came))
    assert len(brought) >= 2, came
    events = _events(tmp_path, since)
    assert [e["kind"] for e in events] == ["cue"], events
    assert set(events[0]["ids"]) == brought
    # Ids only: none of the message's words is kept.
    conn = sqlite3.connect(tmp_path / "a.db")
    try:
        row = conn.execute("SELECT * FROM memory_trace WHERE tool = 'cue'").fetchone()
    finally:
        conn.close()
    assert "kiln" not in repr(row) and "glaze" not in repr(row)


def test_the_same_message_again_is_one_event(tmp_path):
    _kept(tmp_path)
    chat = _provider(tmp_path, "chat-1")
    try:
        chat.system_prompt_block()
        since = _now()
        first = chat.prefetch(MESSAGE, session_id="chat-1")
        again = chat.prefetch(MESSAGE, session_id="chat-1")  # the cache answers
    finally:
        chat.shutdown()

    assert again == first
    assert [e["kind"] for e in _events(tmp_path, since)] == ["cue"]


def test_a_run_nobody_is_in_lights_nothing(tmp_path):
    _kept(tmp_path)
    job = _provider(tmp_path, "cron-1", platform="cron", agent_context="cron")
    try:
        since = _now()
        came = job.prefetch(MESSAGE, session_id="cron-1")
    finally:
        job.shutdown()

    assert "kiln" in came  # it still reads
    assert _events(tmp_path, since) == []


def test_a_message_does_not_count_the_day_as_lived(tmp_path):
    _kept(tmp_path)
    chat = _provider(tmp_path, "chat-1")
    try:
        chat.system_prompt_block()
        _forget_the_lived_days(tmp_path)
        since = _now()
        chat.prefetch(MESSAGE, session_id="chat-1")
    finally:
        chat.shutdown()

    assert [e["kind"] for e in _events(tmp_path, since)] == ["cue"]
    assert _lived(tmp_path) == []
