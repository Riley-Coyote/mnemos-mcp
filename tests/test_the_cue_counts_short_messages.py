"""The cue counts the messages too short to look at.

A message with fewer than ``CUE_MIN_WORDS`` meaningful words gets nothing:
on so few words a match is mostly chance (on ten days of real use, lifting the
minimum offered lines for 224 of 397 short messages, about one in twelve of
them bearing on it), and most are "yes" or "go ahead". But the skip left no
trace, so the health card couldn't say why a message got nothing, and the lab
had to infer the cue's silence from the prompts themselves (L18). Now each
skip is counted in the session's file, apart from the messages the cue looked
at, and the card's cue line says how many there were. A store that doesn't
exist still gets nothing written for it.
"""

from __future__ import annotations

from mnemos.simple_runtime import MnemosRuntime, format_health_card
from tests.test_the_cue import (  # noqa: F401  (meaning and home are fixtures)
    MESSAGE,
    SCOPE,
    _gate_memories,
    _hook,
    _seen,
    _store,
    cue,
    home,
    meaning,
)

SHORT = "yes, do it"


def _card(db) -> tuple[dict, str]:
    rt = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    try:
        data = rt.health()
        return data, format_health_card(data)
    finally:
        rt.close()


def test_a_short_message_gets_nothing_and_is_counted(tmp_path, meaning, home):
    db = _store(tmp_path / "memory.db", *_gate_memories().values())

    assert _hook(db, SHORT) == ""
    assert _hook(db, "go ahead") == ""

    seen = _seen("session-one", db)
    assert seen["short"] == 2, seen
    assert (seen["silences"], seen["failures"], sum(seen["answers"].values())) == (0, 0, 0), seen


def test_the_card_counts_short_messages_apart_from_those_it_looked_at(tmp_path, meaning, home):
    db = _store(tmp_path / "memory.db", *_gate_memories().values())
    _hook(db, MESSAGE)
    _hook(db, SHORT)
    _hook(db, SHORT)

    data, card = _card(db)

    check = data["watchdog"]["checks"]["cue"]
    assert check["messages"] == 1 and check["short"] == 2, check
    assert "2 too short to look at (under 4 meaningful words)" in check["seen"], check["seen"]
    assert check["stalled"] is False, check


def test_a_week_of_only_short_messages_says_so(tmp_path, meaning, home):
    db = _store(tmp_path / "memory.db", *_gate_memories().values())
    _hook(db, SHORT)

    data, _card_text = _card(db)

    seen = data["watchdog"]["checks"]["cue"]["seen"]
    assert "answered no message here" in seen and "1 too short to look at" in seen, seen


def test_a_store_that_does_not_exist_gets_no_record(tmp_path, home):
    missing = tmp_path / "no-such.db"

    assert _hook(missing, SHORT) == ""
    assert _hook(missing, MESSAGE) == ""

    assert not missing.exists()
    run = cue.run_dir()
    assert not run.exists() or not any(run.glob("shown-*")), list(run.glob("*"))
