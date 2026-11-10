"""A Hermes agent takes its quiet hour with a tool of its own.

A Hermes agent that Hermes's plugin catalog installed had no quiet hours. They
were switched off there because the job Mnemos made ran a ``mnemos`` command
from a folder Hermes rebuilds at every update. Now Hermes's own scheduler wakes
the agent, and the agent asks Mnemos for its hour with ``mnemos_hour``: the hour
``mnemos life --hour <kind> --handoff`` hands over, from the same code, with a few
sentences true only inside Hermes after the fence. What these tests hold:

1. It is the same text the hand-off gives, for each kind, plus those sentences.
2. The same material isn't handed twice: with nothing new, the hour skips.
3. Nothing in the store changes.
4. A profile's hour reads that profile's memory and no other.
5. It works in a scheduled run (``agent_context="cron"``).
6. Where the hour can't be prepared (no ``fcntl``, as on Windows) it says so
   plainly and changes nothing, and the plugin still loads.

Temporary homes only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import types

import pytest

import mnemos
from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore
from mnemos.store.sqlite_store import EngramStore

OPUS = "claude-opus-5-5"
KINDS = ("mine", "ours", "dream")
GAP = "\n\n---\n\n"


class NoMeaning:
    """An index that can't search: what a machine without the model has."""

    available = False

    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def no_meaning(monkeypatch):
    import mnemos.store.embedding_index as index

    monkeypatch.setattr(index, "EmbeddingIndex", NoMeaning)
    monkeypatch.delenv("MNEMOS_HOUR_MODEL", raising=False)


def _provider(tmp_path, name: str = "a", **init) -> MnemosMemoryProviderCore:
    home = tmp_path / f"hermes-{name}"
    home.mkdir(exist_ok=True)
    provider = MnemosMemoryProviderCore(
        HermesMnemosConfig(
            db_path=str(tmp_path / f"{name}.db"),
            agent_id=name,
            person_id="user",
            project_scope="global",
            deep_maintenance=False,
        )
    )
    provider.initialize("session-1", hermes_home=str(home), **{"platform": "cli", **init})
    return provider


def _call(provider: MnemosMemoryProviderCore, tool: str, **args) -> str:
    reply = json.loads(provider.handle_tool_call(tool, args))
    assert reply["ok"], reply
    return reply["result"]


def _hours_before(agent: str) -> None:
    """An hour of each kind two days ago, so what is since then is the same for
    every read in a test, whatever minute it reads in."""
    folder = Path.home() / ".mnemos" / "hours" / agent
    folder.mkdir(parents=True, exist_ok=True)
    ended = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with (folder / "hours.jsonl").open("a") as out:
        for kind in KINDS:
            out.write(json.dumps({"id": f"before-{kind}", "kind": kind, "status": "done",
                                  "store": "live", "ended_at": ended}) + "\n")


def _work(provider: MnemosMemoryProviderCore, words: str = "The ferry timetable changed.") -> str:
    """A day's work, and a question waiting on it for a dream; the memory's id."""
    said = _call(provider, "mnemos_capture", content=words, signed_as=OPUS, impact="Read the new timetable.")
    _call(provider, "mnemos_handoff", text=f"Where I stopped: {words}", signed_as=OPUS)
    engram_id = said.split("Memory ID: ", 1)[1].split()[0]
    scope = provider.scope
    store = EngramStore(scope.db_path)
    try:
        store.enqueue_reflection("lesson", engram_id, "What did this teach you?", agent_id=scope.agent_id,
                                 person_id=scope.person_id, project_scope=scope.project_scope)
    finally:
        store.close()
    return engram_id


def _as_mnemos_hands_it(provider: MnemosMemoryProviderCore, kind: str) -> str:
    """What `mnemos life --hour <kind> --handoff` hands, read without recording it."""
    from mnemos.life import run_hour

    scope = provider.scope
    dry = run_hour(kind, db_path=scope.db_path, agent_id=scope.agent_id, person_id=scope.person_id,
                   project_scope=scope.project_scope, handoff=True, dry_run=True, out=io.StringIO())
    assert not dry["skip"], dry
    return dry["prompt"]


def _digest(db) -> str:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return hashlib.sha256("\n".join(conn.iterdump()).encode()).hexdigest()
    finally:
        conn.close()


def _as_on_windows(monkeypatch) -> None:
    """Make importing the hours' runner fail, as it fails without fcntl."""
    monkeypatch.setitem(sys.modules, "mnemos.life", None)
    monkeypatch.delattr(mnemos, "life", raising=False)


# ── The tool ──


def test_it_is_offered_and_says_when_to_take_it(tmp_path):
    provider = _provider(tmp_path)
    try:
        (tool,) = [t for t in provider.get_tool_schemas() if t["name"] == "mnemos_hour"]
    finally:
        provider.shutdown()
    assert tool["parameters"]["required"] == ["kind"]
    assert tool["parameters"]["properties"]["kind"]["enum"] == list(KINDS)
    said = " ".join(tool["description"].split())
    assert "quiet-hour job" in said and "when the person asks" in said
    assert "never on your own initiative" in said.lower()


@pytest.mark.parametrize("kind", KINDS)
def test_it_hands_the_hour_mnemos_hands_with_what_is_true_in_hermes(tmp_path, kind):
    provider = _provider(tmp_path)
    try:
        _work(provider)
        _hours_before("a")
        handed = _as_mnemos_hands_it(provider, kind)
        text = _call(provider, "mnemos_hour", kind=kind)
    finally:
        provider.shutdown()
    fence, _, prompt = handed.partition(GAP)
    # The fence, then the sentences true in Hermes, then the hour as it is handed anywhere.
    assert text.startswith(fence + "\n\n") and text.endswith(GAP + prompt), text
    here = text[len(fence) + 2:len(text) - len(GAP + prompt)]
    assert here and GAP not in here
    assert fence + GAP + prompt == handed
    # The fence names three tools; what Hermes adds reads as more of the same
    # thought, not as a second, whole list (the run in a real Hermes, W2).
    for tool in ("mnemos_reflect", "mnemos_capture", "mnemos_journal"):
        assert tool in fence and tool not in here, here
    assert here.startswith("Here, in Hermes, besides those, you also have mnemos_correct, for what "
                           "turns out wrong"), here
    assert "signed_as" in here
    if kind == "dream":
        # A dream leaves no note (HANDOFF_KEPT), and has no conversations to read.
        assert "mnemos_note" not in here and "session_search" not in here
    else:
        assert "mnemos_note" in here and "page" in here and "computer Hermes runs on" in here
    assert ("session_search" in here) == (kind == "ours")
    if kind == "ours":
        # Going back over the day's conversations is the heart of this hour, and
        # Hermes keeps session_search behind its tool search by default, in a
        # scheduled run as in a conversation (W4).
        said = " ".join(here.split())
        assert "read them with session_search" in said and "if you have session_search" not in said
        assert "behind its tool search" in said and "go by what the hour hands you" in said


def test_a_note_it_leaves_is_said_where_it_says(tmp_path):
    # The note waits on the page, and the next conversation wakes knowing it waits.
    hour = _provider(tmp_path, agent_context="cron")
    try:
        _call(hour, "mnemos_introduce", agent_model=OPUS)
        _call(hour, "mnemos_note", text="Should the timetable go on the wall?", kind="question", signed_as=OPUS)
    finally:
        hour.shutdown()
    talk = _provider(tmp_path)
    try:
        wake = talk.system_prompt_block()
    finally:
        talk.shutdown()
    assert "hasn't yet read" in wake and "my page shows it" in wake, wake


def test_the_same_material_is_not_handed_twice(tmp_path):
    provider = _provider(tmp_path)
    try:
        _work(provider)
        first = _call(provider, "mnemos_hour", kind="ours")
        again = _call(provider, "mnemos_hour", kind="ours")
    finally:
        provider.shutdown()
    assert "The ferry timetable changed." in first
    assert again.startswith("The hour would skip: No handoffs or captures since"), again
    assert "The ferry timetable changed." not in again


def test_with_nothing_waiting_the_hour_skips(tmp_path):
    provider = _provider(tmp_path)
    try:
        ours = _call(provider, "mnemos_hour", kind="ours")
        dream = _call(provider, "mnemos_hour", kind="dream")
    finally:
        provider.shutdown()
    assert ours.startswith("The hour would skip: No handoffs or captures since"), ours
    assert dream.startswith("The hour would skip: Nothing to dream over"), dream


def test_the_store_is_the_same_after_every_hour(tmp_path):
    provider = _provider(tmp_path)
    try:
        _work(provider)
        before = _digest(tmp_path / "a.db")
        for kind in KINDS:
            assert GAP in _call(provider, "mnemos_hour", kind=kind)
        after = _digest(tmp_path / "a.db")
    finally:
        provider.shutdown()
    assert after == before


def test_a_profiles_hour_is_of_its_own_memory(tmp_path):
    ferry = _provider(tmp_path, "a")
    bakery = _provider(tmp_path, "b")
    try:
        _work(ferry, "The ferry timetable changed.")
        _work(bakery, "The bakery opens at seven now.")
        theirs = {kind: _call(ferry, "mnemos_hour", kind=kind) for kind in KINDS}
        its = {kind: _call(bakery, "mnemos_hour", kind=kind) for kind in KINDS}
    finally:
        ferry.shutdown()
        bakery.shutdown()
    for kind in KINDS:
        assert "ferry" in theirs[kind] and "bakery" not in theirs[kind], theirs[kind]
        assert "bakery" in its[kind] and "ferry" not in its[kind], its[kind]
    assert (Path.home() / ".mnemos/hours/a/hours.jsonl").exists()
    assert (Path.home() / ".mnemos/hours/b/hours.jsonl").exists()


def test_it_works_in_a_scheduled_run(tmp_path):
    talk = _provider(tmp_path)
    try:
        _work(talk)
    finally:
        talk.shutdown()
    job = _provider(tmp_path, agent_context="cron")
    try:
        names = {t["name"] for t in job.get_tool_schemas()}
        text = _call(job, "mnemos_hour", kind="ours")
    finally:
        job.shutdown()
    assert "mnemos_hour" in names and "mnemos_page" not in names
    assert "The ferry timetable changed." in text and "session_search" in text


def test_a_kind_it_doesnt_know_is_refused(tmp_path):
    provider = _provider(tmp_path)
    try:
        reply = json.loads(provider.handle_tool_call("mnemos_hour", {"kind": "nap"}))
    finally:
        provider.shutdown()
    assert not reply["ok"] and "mine, ours or dream" in reply["error"]
    assert not (Path.home() / ".mnemos/hours/a").exists()


# ── Where the hour can't be prepared ──


def test_without_fcntl_it_says_so_and_changes_nothing(tmp_path, monkeypatch):
    provider = _provider(tmp_path)
    try:
        _work(provider)
        before = _digest(tmp_path / "a.db")
        _as_on_windows(monkeypatch)
        said = _call(provider, "mnemos_hour", kind="mine")
    finally:
        provider.shutdown()
    assert "can't be prepared on this system" in said and "macOS and Linux" in said, said
    assert "Nothing was handed" in said
    assert not (Path.home() / ".mnemos/hours/a").exists()
    assert _digest(tmp_path / "a.db") == before


def test_without_fcntl_the_plugin_still_loads_and_answers(tmp_path):
    code = (
        "import sys\n"
        "sys.modules['fcntl'] = None\n"
        "from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore as Core\n"
        "p = Core(HermesMnemosConfig(db_path=sys.argv[1], agent_id='a', person_id='user',\n"
        "         project_scope='global', deep_maintenance=False))\n"
        "p.initialize('s', hermes_home=sys.argv[2], platform='cli')\n"
        "print('mnemos_hour' in {t['name'] for t in p.get_tool_schemas()})\n"
        "print(p.handle_tool_call('mnemos_hour', {'kind': 'mine'}))\n"
        "p.shutdown()\n"
    )
    home = tmp_path / "hermes"
    home.mkdir()
    done = subprocess.run([sys.executable, "-c", code, str(tmp_path / "a.db"), str(home)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    offered, reply = done.stdout.strip().split("\n", 1)
    assert offered == "True"
    reply = json.loads(reply)
    assert reply["ok"] and "macOS and Linux" in reply["result"], reply


def test_what_is_said_about_handing_once_is_true(tmp_path):
    """The words said each hour's material is handed once; your own hour hands
    an open question again until it's answered (round seven, p09)."""
    provider = _provider(tmp_path)
    try:
        _work(provider)
        first = _call(provider, "mnemos_hour", kind="mine")
        again = _call(provider, "mnemos_hour", kind="mine")
        (tool,) = [t for t in provider.get_tool_schemas() if t["name"] == "mnemos_hour"]
    finally:
        provider.shutdown()
    assert "What did this teach you?" in first and "What did this teach you?" in again
    said = " ".join(tool["description"].split())
    assert "Each hour's material is handed once" not in said
    assert ("What waits for the day's work or a dream is handed once; your own hour hands an open "
            "question again, each time, until you answer it.") in said


@pytest.mark.parametrize("status", ["skipped", "failed"])
@pytest.mark.parametrize("reason, said", [
    ("The hand-off hit an error: OperationalError: database is locked",
     "The hand-off hit an error: OperationalError: database is locked."),
    ("Another hour is running.", "Another hour is running."),
    ("There is no memory store at /tmp/x.db ", "There is no memory store at /tmp/x.db."),
    ("The hand-off hit an error: ValueError: bad (see the log)", "The hand-off hit an error: ValueError: bad (see the log)."),
    ("Is the store there?", "Is the store there?"),
    ("It stopped…", "It stopped…."),
])
def test_a_reason_ends_its_sentence_before_the_next(tmp_path, monkeypatch, status, reason, said):
    """A locked or damaged store's reason ran into the next sentence:
    "…database is locked Nothing was handed." (round seven, p03)."""
    import mnemos.life as life

    monkeypatch.setattr(life, "run_hour", lambda *a, **k: {"status": status, "reason": reason})
    provider = _provider(tmp_path)
    try:
        text = _call(provider, "mnemos_hour", kind="mine")
    finally:
        provider.shutdown()
    assert text.endswith(f"{said} Nothing was handed."), text


def test_a_damaged_store_is_said_in_whole_sentences(tmp_path):
    provider = _provider(tmp_path)
    try:
        _work(provider)
    finally:
        provider.shutdown()
    (tmp_path / "a.db").write_bytes(b"not a database, not at all" * 200)
    for leftover in tmp_path.glob("a.db-*"):
        leftover.unlink()
    scope = types.SimpleNamespace(db_path=str(tmp_path / "a.db"), agent_id="a", person_id="user",
                                  project_scope="global")
    from mnemos.integrations.hermes.hours import take_hour

    said = take_hour("mine", scope)
    assert said.startswith("Your hour couldn't be handed: The hand-off hit an error: DatabaseError:"), said
    assert said.endswith("file is not a database. Nothing was handed."), said
