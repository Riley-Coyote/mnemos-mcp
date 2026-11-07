"""Many Hermes conversations at once each keep their own handoff.

Someone on X, Nov 6 2026: "I've taken to having many many parallel sessions
setup by topic in my telegram for my Hermes agent. How does it handle someone
who has many parallel sessions on different topics?" The memory itself did
fine: one memory across the topics. The handoff did not. Sessions are told
apart by ``CLAUDE_CODE_SESSION_ID``, which only Claude Code sets, so every
topic shared one note: the newest replaced the rest, and a topic that started
a fresh session woke to another topic's thread.

These tests hand the provider what Hermes hands it (``_init_kwargs`` in
Hermes's agent/agent_init.py, with ``chat_name`` as its Telegram adapter sets
it: the group's title, the same for every topic) and read through the defaults
an agent actually hits. Nothing passes a conversation to the writer and the
reader by hand.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Timer

import pytest

from mnemos.authorship import clean_session_id
from mnemos.integrations.hermes import MnemosMemoryProviderCore, installer
from mnemos.integrations.hermes import build_memory_provider_class as installer_build
from mnemos.integrations.hermes.installer import PROVIDER_MODE, SIDECAR_MODE, install_hermes_plugin
from mnemos.integrations.hermes.scope import derive_hermes_scope, save_hermes_mnemos_config
from mnemos.simple_runtime import MnemosRuntime
from mnemos.simple_scope import resolve_scope
from mnemos.store import sqlite_store

CHAT = "-1001234567890"
SCOPE = ("hermes", "user", "global")


@pytest.fixture(autouse=True)
def _not_inside_claude_code(monkeypatch):
    # Run from inside a Claude Code session, the environment would name a
    # session for every topic, which is the one thing Hermes doesn't get.
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


@pytest.fixture
def home(tmp_path) -> Path:
    # What `mnemos connect hermes --write` leaves in mnemos.json.
    hermes_home = tmp_path / "hermes"
    save_hermes_mnemos_config(hermes_home, {
        "db_path": str(tmp_path / "hermes.db"),
        "agent_id": SCOPE[0],
        "person_id": SCOPE[1],
        "project_scope": SCOPE[2],
    })
    return hermes_home


def _gateway_kwargs(home: Path, thread: object) -> dict:
    return {
        "platform": "telegram",
        "hermes_home": str(home),
        "agent_context": "primary",
        "user_id": "42",
        "user_name": "Leo",
        "chat_id": CHAT,
        "chat_name": "Leo's agent",
        "chat_type": "group",
        "thread_id": str(thread),
        "gateway_session_key": f"agent:main:telegram:group:{CHAT}:{thread}",
        "agent_identity": "default",
        "agent_workspace": "hermes",
    }


def _topic(home: Path, thread: object, session: str = "") -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize(session or f"20261106_140000_{thread}", **_gateway_kwargs(home, thread))
    return provider


def _cli(home: Path, session: str) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize(
        session, platform="cli", hermes_home=str(home), agent_context="primary",
        agent_identity="default", agent_workspace="hermes",
    )
    return provider


def _leave(provider: MnemosMemoryProviderCore, text: str) -> None:
    reply = json.loads(provider.handle_tool_call("mnemos_handoff", {"text": text}))
    assert reply.get("ok"), reply


def _active(provider: MnemosMemoryProviderCore) -> list[dict]:
    provider._runtime._ensure_init()
    rows = provider._runtime._store._get_conn().execute(
        """SELECT content, author_session FROM hypomnema_entries
           WHERE entry_kind = 'handoff' AND active = 1 ORDER BY created_at""",
    ).fetchall()
    return [dict(row) for row in rows]


def _where_i_was(wake: str) -> str:
    # "where things were left" when the reader can't call the note its own.
    left_off = re.split(r"### where (?:i was|things were left)\n", wake, maxsplit=1)[1]
    return left_off.split("\n\n### ", 1)[0]


HEALTH = "Health thread: the pre-op bloodwork is still to book."
WORK = "Work thread: waiting on the churn numbers from Sam."
GARDEN = "Garden thread: order the seed catalog."


class TestTheQuestionWeWereAsked:
    def test_every_topic_keeps_its_own_note(self, home):
        health, work, garden = _topic(home, 7), _topic(home, 9), _topic(home, 11)
        _leave(health, HEALTH)
        _leave(work, WORK)
        _leave(garden, GARDEN)

        notes = _active(garden)
        assert {note["content"] for note in notes} == {HEALTH, WORK, GARDEN}
        assert len({note["author_session"] for note in notes}) == 3
        assert all(note["author_session"] for note in notes)

    def test_a_topic_starting_a_fresh_session_wakes_to_its_own_thread(self, home):
        _leave(_topic(home, 7), HEALTH)
        _leave(_topic(home, 9), WORK)
        _leave(_topic(home, 11), GARDEN)  # the newest

        wake = _topic(home, 7, session="20261107_090000_fresh").system_prompt_block()
        left_off = _where_i_was(wake)
        assert re.match(r"[^\n]*, this session:\nHealth thread", left_off), left_off
        # The others follow as short lines, so it knows what else is going on.
        assert "Work thread" in wake and "Garden thread" in wake

    def test_it_reads_back_in_another_process(self, home):
        _leave(_topic(home, 7), HEALTH)
        _leave(_topic(home, 11), GARDEN)
        code = (
            "import json, sys\n"
            "from mnemos.integrations.hermes import MnemosMemoryProviderCore\n"
            "provider = MnemosMemoryProviderCore()\n"
            "provider.initialize('20261107_090000_other', **json.loads(sys.argv[1]))\n"
            "print(provider.system_prompt_block())\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code, json.dumps(_gateway_kwargs(home, 7))],
            capture_output=True, text=True, timeout=120,
            env={"PATH": "/usr/bin:/bin", "HOME": str(home), "MNEMOS_DISABLE_DOTENV": "1",
                 "PYTHONPATH": ":".join(sys.path), "SYSTEMROOT": ""},
        )
        assert proc.returncode == 0, proc.stderr
        assert re.match(r"[^\n]*, this session:\nHealth thread", _where_i_was(proc.stdout))

    def test_a_new_topic_wakes_to_the_newest_and_says_whose_it_is(self, home):
        _leave(_topic(home, 7), HEALTH)
        _leave(_topic(home, 11), GARDEN)

        left_off = _where_i_was(_topic(home, 99).system_prompt_block())
        assert re.match(r"[^\n]*, in another session:\nGarden thread", left_off), left_off

    def test_a_topic_replaces_only_its_own_note(self, home):
        health, work = _topic(home, 7), _topic(home, 9)
        _leave(health, "Health, first note.")
        _leave(work, WORK)
        _leave(health, HEALTH)
        assert {note["content"] for note in _active(work)} == {HEALTH, WORK}

    def test_many_topics_each_get_their_own_back(self, home):
        # More topics than the store keeps notes for: the one left longest
        # still wakes to its own thread, and can be told apart from the rest.
        topics = {thread: _topic(home, thread) for thread in range(100, 112)}
        for thread, topic in topics.items():
            _leave(topic, f"Thread {thread} is where it stands.")
        assert len(_active(topics[100])) == 8

        left_off = _where_i_was(_topic(home, 100, session="fresh-100").system_prompt_block())
        assert re.match(r"[^\n]*, this session:\nThread 100 ", left_off), left_off

    def test_a_note_it_forgot_stays_forgotten(self, home):
        health = _topic(home, 7)
        _leave(health, HEALTH)
        _leave(_topic(home, 9), WORK)
        target = health._runtime._store.get_latest_handoff(
            agent_id=SCOPE[0], person_id=SCOPE[1], project_scope=SCOPE[2],
        )
        assert target["content"] == WORK
        row = health._runtime._store._get_conn().execute(
            "SELECT id FROM hypomnema_entries WHERE content = ?", (HEALTH,),
        ).fetchone()
        health.handle_tool_call("mnemos_correct", {"target_id": row["id"], "action": "forget"})

        wake = _topic(home, 7, session="fresh-7").system_prompt_block()
        assert "pre-op bloodwork" not in wake


class TestForgettingACrowdedOutNote:
    def test_a_note_back_from_being_crowded_out_can_be_forgotten(self, home):
        health = _topic(home, 7)
        _leave(health, HEALTH)
        for thread in range(100, 112):
            _leave(_topic(home, thread), f"Thread {thread} note.")
        again = _topic(home, 7, session="fresh-7")
        assert "pre-op bloodwork" in again.system_prompt_block()
        row = again._runtime._store._get_conn().execute(
            "SELECT id FROM hypomnema_entries WHERE content = ?", (HEALTH,),
        ).fetchone()

        reply = again.handle_tool_call("mnemos_correct", {"target_id": row["id"], "action": "forget"})

        assert "no longer active" not in reply, reply
        assert "pre-op bloodwork" not in _topic(home, 7, session="fresh-7b").system_prompt_block()

    def test_one_replaced_on_purpose_is_still_not_archived_again(self, home):
        topic = _topic(home, 7)
        _leave(topic, "The first note.")
        _leave(topic, "The second note.")
        row = topic._runtime._store._get_conn().execute(
            "SELECT id FROM hypomnema_entries WHERE content = ?", ("The first note.",),
        ).fetchone()
        reply = topic.handle_tool_call("mnemos_correct", {"target_id": row["id"], "action": "forget"})
        assert "no longer active" in reply, reply


class TestOneConversationAcrossItsSessions:
    def test_new_in_a_topic_is_still_that_topic(self, home):
        topic = _topic(home, 7)
        _leave(topic, "Health, before /new.")
        topic.on_session_switch("20261106_150000_new", parent_session_id="old", reset=True, reason="new_session")
        _leave(topic, HEALTH)
        assert [note["content"] for note in _active(topic)] == [HEALTH]

    def test_compression_in_a_topic_is_still_that_topic(self, home):
        topic = _topic(home, 7)
        _leave(topic, "Health, before compression.")
        topic.on_session_switch("20261106_150000_cmp", parent_session_id="old", reason="compression")
        _leave(topic, HEALTH)
        assert [note["content"] for note in _active(topic)] == [HEALTH]

    def test_on_the_command_line_compression_continues_the_conversation(self, home):
        cli = _cli(home, "20261106_cli_one")
        _leave(cli, "CLI, before compression.")
        cli.on_session_switch("20261106_cli_two", parent_session_id="20261106_cli_one", reason="compression")
        _leave(cli, "CLI, after compression.")
        assert [note["content"] for note in _active(cli)] == ["CLI, after compression."]

    def test_on_the_command_line_new_starts_another_conversation(self, home):
        cli = _cli(home, "20261106_cli_one")
        _leave(cli, "CLI, the first conversation.")
        cli.on_session_switch("20261106_cli_two", parent_session_id="20261106_cli_one", reset=True, reason="new_session")
        _leave(cli, "CLI, the second conversation.")
        assert len(_active(cli)) == 2

    def test_on_the_command_line_resume_goes_back_to_that_conversation(self, home):
        cli = _cli(home, "20261106_cli_one")
        _leave(cli, "CLI, the first conversation.")
        cli.on_session_switch("20261106_cli_two", reset=True, reason="new_session")
        _leave(cli, "CLI, the second conversation.")
        cli.on_session_switch("20261106_cli_one", parent_session_id="20261106_cli_two", reason="resume")
        _leave(cli, "CLI, the first conversation, later.")
        assert {note["content"] for note in _active(cli)} == {
            "CLI, the first conversation, later.", "CLI, the second conversation.",
        }


class TestWhatTheIdIs:
    def test_it_reads_as_a_session_and_gives_nothing_away(self, home):
        topic = _topic(home, 7)
        _leave(topic, HEALTH)
        session = _active(topic)[0]["author_session"]
        assert clean_session_id(session) == session
        assert CHAT.lstrip("-") not in session

    def test_only_handoffs_go_by_it(self, home):
        # A conversation outlives many sessions. What counts once per session
        # (a recall's reinforcement, among others) must not become once per
        # conversation, or a long-lived topic would stop strengthening memories.
        topic = _topic(home, 7)
        topic.handle_tool_call("mnemos_capture", {"content": "The knee surgery is on March 3."})
        rows = topic._runtime._store._get_conn().execute("SELECT author_session FROM engrams").fetchall()
        assert rows and all(not row["author_session"] for row in rows)

        seen = []
        retriever = topic._runtime._retriever
        original = retriever.reinforce
        retriever.reinforce = lambda *args, **kwargs: (seen.append(kwargs.get("session")), original(*args, **kwargs))[1]
        assert "knee surgery" in topic.prefetch("when is the knee surgery", session_id=topic.scope.session_id)
        assert seen and all(session != topic.scope.conversation for session in seen), seen

    def test_the_note_is_stored_exactly_as_written(self, home):
        topic = _topic(home, 7)
        words = "First line,  two spaces.\n\n  Then an indented line.\n"
        _leave(topic, words)
        row = topic._runtime._store._get_conn().execute(
            "SELECT content FROM hypomnema_entries WHERE entry_kind = 'handoff'",
        ).fetchone()
        assert row["content"] == words

    def test_the_recall_list_knows_which_note_is_its_own(self, home):
        topic = _topic(home, 7)
        _leave(topic, "Pre-op bloodwork still to book, says this thread.")
        other = _topic(home, 9)
        _leave(other, "Pre-op bloodwork is another thread's worry here.")
        reply = json.loads(topic.handle_tool_call("mnemos_recall", {"query": "pre-op bloodwork"}))["result"]
        lines = reply.splitlines()
        own = next(index for index, line in enumerate(lines) if "says this thread" in line)
        theirs = next(index for index, line in enumerate(lines) if "another thread's" in line)
        assert "Yours, from this session" in lines[own + 1], reply
        assert "this session" not in lines[theirs + 1], reply

    def test_recall_by_id_says_the_note_is_its_own(self, home):
        topic = _topic(home, 7)
        _leave(topic, HEALTH)
        row = topic._runtime._store._get_conn().execute(
            "SELECT id FROM hypomnema_entries WHERE content = ?", (HEALTH,),
        ).fetchone()
        reply = json.loads(topic.handle_tool_call("mnemos_recall", {"query": row["id"]}))
        assert "this session" in reply["result"], reply["result"]


class TestTheWakeIsWhole:
    """The wake was cut to the 2,200 characters meant for what recall adds to a
    message, mid-sentence, on a memory with next to nothing in it."""

    def test_a_long_note_comes_through_whole(self, home):
        note = "Health thread. " + " ".join(
            f"Step {step} of the bloodwork is done and checked." for step in range(120)
        )
        assert len(note) > 2200
        _leave(_topic(home, 7), note)

        wake = _topic(home, 7, session="fresh-7").system_prompt_block()
        assert note in wake
        assert "truncated" not in wake

    def test_what_recall_adds_to_a_message_stays_small(self, home):
        topic = _topic(home, 7)
        for index in range(8):
            topic.handle_tool_call("mnemos_capture", {
                "content": f"Knee note {index}: the surgery recovery plan, week by week. " * 8,
            })
        recalled = topic.prefetch("knee surgery recovery plan")
        assert recalled and len(recalled) <= 2200

    def test_the_wake_can_still_be_bounded_on_purpose(self, home):
        save_hermes_mnemos_config(home, {"max_wake_chars": 1000})
        _leave(_topic(home, 7), "Health thread. " + "Step done and checked. " * 200)
        assert len(_topic(home, 7, session="fresh-7").system_prompt_block()) <= 1000


class TestWhatShowsOnce:
    """Starting up used to build a whole wake and throw it away. A wake counts
    what it shows as shown, so a reply from the person, a quiet hour and the
    rest were spent on a read no model saw, and never reached the agent."""

    def test_a_reply_from_the_person_reaches_the_wake_that_is_read(self, home, tmp_path):
        topic = _topic(home, 7)
        said = topic._runtime.note("The pier timetable changed.", "noticed", signed_as="claude-opus-5-5")
        note_id = said.split("Note ID: ", 1)[1].splitlines()[0].strip()
        topic.shutdown()
        replied = subprocess.run(
            [sys.executable, "-m", "mnemos.cli", "notes", "reply",
             "--db-path", str(tmp_path / "hermes.db"), "--agent-id", SCOPE[0],
             "--person-id", SCOPE[1], "--project-scope", SCOPE[2],
             note_id, "I'll check with the harbour office."],
            capture_output=True, text=True, timeout=120,
            env={"PATH": "/usr/bin:/bin", "HOME": str(home), "MNEMOS_DISABLE_DOTENV": "1",
                 "PYTHONPATH": ":".join(sys.path), "SYSTEMROOT": ""},
        )
        assert replied.returncode == 0, replied.stderr

        first = _topic(home, 7, session="fresh-7").system_prompt_block()
        assert "harbour office" in first, first
        second = _topic(home, 7, session="fresh-7b").system_prompt_block()
        assert "harbour office" not in second

    def test_starting_up_alone_spends_nothing(self, home):
        topic = _topic(home, 7)
        _leave(topic, HEALTH)
        topic.shutdown()
        started = _topic(home, 9)  # never reads its wake
        count = started._runtime._store._get_conn().execute(
            "SELECT surface_count FROM hypomnema_entries WHERE content = ?", (HEALTH,),
        ).fetchone()["surface_count"]
        assert count == 0


class TestAtTheSameTime:
    def test_eight_topics_leaving_notes_at_once_each_keep_theirs(self, home):
        topics = [_topic(home, thread) for thread in range(200, 208)]
        barrier = Barrier(len(topics))

        def leave(topic_and_thread):
            topic, thread = topic_and_thread
            barrier.wait()
            _leave(topic, f"Thread {thread} is where it stands.")

        with ThreadPoolExecutor(max_workers=len(topics)) as pool:
            list(pool.map(leave, zip(topics, range(200, 208))))

        assert {note["content"] for note in _active(topics[0])} == {
            f"Thread {thread} is where it stands." for thread in range(200, 208)
        }


class TestANewStoreOpenedTogether:
    """The first messages after setup: several topics open a store that doesn't
    exist yet. Turning WAL on doesn't wait, so all but one were told "database is
    locked", and the provider's start-up failed."""

    def test_every_one_of_them_opens_it(self, tmp_path):
        for round_number in range(8):
            db = tmp_path / f"new-{round_number}.db"
            barrier = Barrier(8)

            def open_it(index):
                runtime = MnemosRuntime(
                    db_path=str(db), agent_id="hermes", person_id="user", project_scope="global",
                )
                barrier.wait()
                runtime._ensure_init()
                foreign_keys = runtime._store._get_conn().execute("PRAGMA foreign_keys").fetchone()[0]
                runtime._store.close()
                return foreign_keys

            with ThreadPoolExecutor(8) as pool:
                assert list(pool.map(open_it, range(8))) == [1] * 8


    def test_turning_wal_on_waits_out_someone_else(self, tmp_path):
        # SQLite answers this switch with "locked" at once, busy timeout or no.
        db = tmp_path / "busy.db"
        holder = sqlite3.connect(db, check_same_thread=False)
        holder.execute("CREATE TABLE t (x)")
        holder.commit()
        holder.execute("BEGIN EXCLUSIVE")
        Timer(0.3, holder.rollback).start()
        waiter = sqlite3.connect(db, timeout=0)
        sqlite_store._turn_wal_on(waiter, time.monotonic() + 5)
        assert waiter.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        waiter.close()
        holder.close()

    def test_a_connection_that_failed_to_set_up_isnt_kept(self, tmp_path, monkeypatch):
        # The next call would take it as ready: foreign keys off, no privacy
        # on the files, with nothing to say so.
        store = MnemosRuntime(
            db_path=str(tmp_path / "m.db"), agent_id="hermes", person_id="user", project_scope="global",
        )
        store._ensure_init()
        store = store._store
        store.close()

        def locked(conn, deadline):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(sqlite_store, "_turn_wal_on", locked)
        with pytest.raises(sqlite3.OperationalError):
            store._get_conn()
        monkeypatch.undo()
        assert store._get_conn().execute("PRAGMA foreign_keys").fetchone()[0] == 1
        store.close()


class TestOneTopicsOwnThreads:
    """Hermes runs a turn's queued prefetch on one thread and the next message
    on another, both on one topic's provider and one SQLite connection. Two at
    once could stop the whole process: every topic, silent, no error."""

    def test_two_threads_on_one_topic_cant_freeze_the_gateway(self, tmp_path):
        code = (
            "import json, sys, threading, time\n"
            "from pathlib import Path\n"
            "from mnemos.integrations.hermes import MnemosMemoryProviderCore\n"
            "home = Path(sys.argv[1])\n"
            "(home / 'mnemos.json').write_text(json.dumps({'db_path': str(home / 'm.db'), 'agent_id': 'hermes',\n"
            "    'person_id': 'user', 'project_scope': 'global'}))\n"
            "p = MnemosMemoryProviderCore()\n"
            "p.initialize('s1', hermes_home=str(home), platform='telegram', gateway_session_key='k:7')\n"
            "for i in range(20):\n"
            "    p.handle_tool_call('mnemos_capture', {'content': f'Fact {i} about the knee surgery.'})\n"
            "end = time.time() + 4\n"
            "errors = []\n"
            "def run(work):\n"
            "    n = 0\n"
            "    while time.time() < end:\n"
            "        n += 1\n"
            "        try:\n"
            "            work(n)\n"
            "        except Exception as exc:\n"
            "            errors.append(repr(exc))\n"
            "work = [\n"
            "    lambda n: p.queue_prefetch(f'knee question {n}', session_id='s1'),\n"
            "    lambda n: p.prefetch(f'surgery detail {n}', session_id='s1'),\n"
            "    lambda n: p.handle_tool_call('mnemos_capture', {'content': f'More fact {n} on the deck.'}),\n"
            "]\n"
            "threads = [threading.Thread(target=run, args=(w,), daemon=True) for w in work]\n"
            "for t in threads:\n"
            "    t.start()\n"
            "for t in threads:\n"
            "    t.join()\n"
            "print('finished', len(errors), errors[:2])\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=tmp_path,
            env={**os.environ, "HOME": str(tmp_path), "MNEMOS_DISABLE_DOTENV": "1"},
        )
        try:
            out, err = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.fail("the process froze with two threads on one topic's memory")
        assert proc.returncode == 0, err
        assert out.startswith("finished 0"), out


class TestHermesOwnEnvironment:
    """Hermes loads the shim in its own Python, which has no Mnemos, and hides
    the failure at debug level. Provider Mode was set, reported active, and
    never loaded: no wake, no recall on each message, on any normal install."""

    def _run_shim_without_site_packages(self, shim: Path, cwd: Path) -> subprocess.CompletedProcess:
        # -S: no site-packages and no editable-install paths, as far as Mnemos
        # is concerned the same as Hermes' environment.
        code = (
            "import sys, types\n"
            "agent, memory_provider = types.ModuleType('agent'), types.ModuleType('agent.memory_provider')\n"
            "memory_provider.MemoryProvider = type('MemoryProvider', (), {})\n"
            "sys.modules['agent'], sys.modules['agent.memory_provider'] = agent, memory_provider\n"
            "exec(compile(open(sys.argv[1]).read(), sys.argv[1], 'exec'))\n"
            "got = []\n"
            "register(types.SimpleNamespace(register_memory_provider=got.append))\n"
            "print(got[0].name)\n"
        )
        return subprocess.run(
            [sys.executable, "-S", "-c", code, str(shim)],
            capture_output=True, text=True, timeout=120, cwd=cwd,
            env={"PATH": "/usr/bin:/bin", "HOME": str(cwd), "MNEMOS_DISABLE_DOTENV": "1", "SYSTEMROOT": ""},
        )

    def test_the_shim_finds_mnemos_from_an_environment_without_it(self, tmp_path):
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False)
        proc = self._run_shim_without_site_packages(home / "plugins" / "mnemos" / "__init__.py", tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "mnemos"

    def test_topics_speaking_at_once_after_a_start_all_get_memory(self, tmp_path):
        # Hermes' loader puts the module in sys.modules before running it. A
        # second thread that finds it there and sees no `register` yet gets no
        # provider, and its session's stored prompt never has the wake. Seen
        # through the real gateway: three topics at once, two without memory.
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False)
        slow = tmp_path / "slow" / "agent"
        slow.mkdir(parents=True)
        (slow / "__init__.py").write_text("")
        (slow / "memory_provider.py").write_text(
            "import time\ntime.sleep(1)\nclass MemoryProvider:\n    pass\n"
        )
        # The order is Hermes' own (plugins/memory/__init__.py, _load_provider_from_dir).
        code = (
            "import importlib.util, sys, threading, time, types\n"
            f"sys.path.insert(0, {str(slow.parent)!r})\n"
            "NAME = '_hermes_user_memory.mnemos'\n"
            "def load():\n"
            "    mod = sys.modules.get(NAME)\n"
            "    if mod is None or not getattr(mod, '__file__', None):\n"
            "        spec = importlib.util.spec_from_file_location(NAME, sys.argv[1])\n"
            "        mod = importlib.util.module_from_spec(spec)\n"
            "        sys.modules[NAME] = mod\n"
            "        spec.loader.exec_module(mod)\n"
            "    got = []\n"
            "    if hasattr(mod, 'register'):\n"
            "        mod.register(types.SimpleNamespace(register_memory_provider=got.append))\n"
            "    results.append(bool(got))\n"
            "results = []\n"
            "threads = [threading.Thread(target=load) for _ in range(3)]\n"
            "for one in threads:\n"
            "    one.start()\n"
            "    time.sleep(0.2)\n"
            "for one in threads:\n"
            "    one.join()\n"
            "print(sum(results), 'of', len(results))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-S", "-c", code, str(home / "plugins" / "mnemos" / "__init__.py")],
            capture_output=True, text=True, timeout=120, cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "MNEMOS_DISABLE_DOTENV": "1", "SYSTEMROOT": ""},
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "3 of 3", proc.stdout + proc.stderr

    def test_the_gateway_loads_it_before_any_message_can_arrive(self, tmp_path):
        # Hermes from before October 2026 can still give a topic no provider however
        # small the window: a hook's handler runs before the gateway connects,
        # and has to leave the module whole, in the module name Hermes uses.
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False, activate=True)
        hook = home / "hooks" / installer.PRELOAD_HOOK
        assert "gateway:startup" in (hook / "HOOK.yaml").read_text()
        code = (
            "import runpy, sys, types\n"
            "plugins = types.ModuleType('plugins')\n"
            "memory = types.ModuleType('plugins.memory')\n"
            "memory.load_memory_provider = lambda name: loaded.append(name)\n"
            "loaded = []\n"
            "sys.modules['plugins'], sys.modules['plugins.memory'] = plugins, memory\n"
            "handler = runpy.run_path(sys.argv[1])\n"
            "assert loaded == ['mnemos'], loaded\n"
            "assert handler['handle']('gateway:startup', {}) is None\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code, str(hook / "handler.py")], capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr

    def test_the_hook_goes_with_provider_mode_and_leaves_others_alone(self, tmp_path):
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False, activate=True)
        hook = home / "hooks" / installer.PRELOAD_HOOK
        other = home / "hooks" / "their-own"
        other.mkdir()
        (other / "handler.py").write_text("def handle(e, c):\n    pass\n")
        install_hermes_plugin(hermes_home=home, mode=SIDECAR_MODE, configure_mcp=False)
        assert not hook.exists()
        assert (other / "handler.py").exists()

    def test_sidecar_mode_adds_no_hook(self, tmp_path):
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=SIDECAR_MODE, configure_mcp=False)
        assert not (home / "hooks").exists()

    def test_doctor_says_so_when_hermes_cant_load_it(self, tmp_path, monkeypatch):
        # Moved or deleted after connecting: Hermes' loader hides why, and the
        # doctor used to say Provider Mode was active.
        monkeypatch.setattr(installer, "_mnemos_import_paths", lambda: [])
        script = tmp_path / "python"
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n')
        script.chmod(0o755)
        monkeypatch.setattr(installer, "_hermes_python", lambda home: script)
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False, activate=True)

        report = installer.build_diagnostics(home)
        assert report["hermes_loads_mnemos"] == "no"
        assert "No module named" in report["hermes_load_problem"]
        text = installer.format_diagnostics(report)
        assert "Hermes can load it: NO" in text
        assert "Provider Mode: active" not in text

    def test_doctor_names_the_store_a_sidecar_really_uses(self, tmp_path, monkeypatch):
        # A sidecar's server opens what its own arguments say. The doctor used to
        # name a file in Hermes' folder, "not created yet", beside fifty memories.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("MNEMOS_AGENT_ID", raising=False)
        monkeypatch.delenv("MNEMOS_DB_PATH", raising=False)
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=SIDECAR_MODE, configure_mcp=True)
        report = installer.build_diagnostics(home)
        assert report["mode"] == "sidecar"
        # The name a person can act on, in the home the server really uses.
        where = Path(installer.profile_store(home))
        assert report["db_path"] == str(where)
        assert report["db_exists"] is False
        where.parent.mkdir(parents=True)
        where.touch()
        assert installer.build_diagnostics(home)["db_exists"] is True

        chosen = tmp_path / "theirs.db"
        other = tmp_path / "hermes-chosen"
        install_hermes_plugin(hermes_home=other, mode=SIDECAR_MODE, configure_mcp=True, db_path=str(chosen))
        assert installer.build_diagnostics(other)["db_path"] == str(chosen)

    def test_doctor_tries_the_shim_that_is_there(self, tmp_path, monkeypatch):
        # Not where this Mnemos is now: the shim holds the path Hermes will use.
        monkeypatch.setattr(installer, "_hermes_python", lambda home: Path(sys.executable))
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False, activate=True)
        assert installer.build_diagnostics(home)["hermes_loads_mnemos"] == "yes"

        shim = home / "plugins" / "mnemos" / "__init__.py"
        shim.write_text(shim.read_text().replace("from mnemos.integrations.hermes", "from mnemos_moved.integrations.hermes"))
        report = installer.build_diagnostics(home)
        assert report["hermes_loads_mnemos"] == "no"
        assert "mnemos_moved" in report["hermes_load_problem"]

    def test_doctor_says_when_it_could_not_try(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, "_hermes_python", lambda home: None)
        home = tmp_path / "hermes"
        result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False, activate=True)
        assert "Hermes can load it: not tried" in result.summary()
        report = installer.build_diagnostics(home)
        assert report["hermes_loads_mnemos"] == "not tried"
        assert "Hermes can load it: not tried" in installer.format_diagnostics(report)

    def test_upkeep_starts_from_hermes_python_on_any_install(self, tmp_path):
        # Started from inside Hermes, it runs on Hermes' Python, which has only
        # what the shim added to the path: on a clone (`uv run`, the paste
        # prompt) that was the checkout alone, it died on its first import, and
        # nothing said, since its output goes nowhere.
        wrapper = tmp_path / "hermes-python"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n')
        wrapper.chmod(0o755)
        paths = installer._mnemos_import_paths()
        code = (
            "import json, sys, time\n"
            f"sys.path.extend({paths!r})\n"
            f"sys.executable = {str(wrapper)!r}\n"
            "from mnemos.simple_runtime import MnemosRuntime, _spawn_upkeep, _UPKEEP_CHILDREN\n"
            "runtime = MnemosRuntime(db_path=sys.argv[1], agent_id='hermes', person_id='user', project_scope='global')\n"
            "runtime._ensure_init()\n"
            "assert _spawn_upkeep(runtime.scope, 'token')\n"
            "print(_UPKEEP_CHILDREN[-1].wait(timeout=90))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-S", "-c", code, str(tmp_path / "m.db")],
            capture_output=True, text=True, timeout=120, cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "MNEMOS_DISABLE_DOTENV": "1", "SYSTEMROOT": ""},
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "0", proc.stdout + proc.stderr

    def test_a_failed_load_keeps_the_mcp_note_tool(self, tmp_path, monkeypatch):
        # Leaving it out assumes the provider's own takes its place.
        monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("no", "it can't"))
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=True, activate=True)
        assert "tools" not in installer._read_mcp_server(home, "mnemos")

    def test_connect_says_so_when_hermes_cant_load_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, "_mnemos_import_paths", lambda: [])
        script = tmp_path / "python"
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n')
        script.chmod(0o755)
        monkeypatch.setattr(installer, "_hermes_python", lambda home: script)

        result = install_hermes_plugin(hermes_home=tmp_path / "hermes", mode=PROVIDER_MODE, configure_mcp=False)
        assert any(
            "can't load Mnemos" in warning and "No module named" in warning for warning in result.warnings
        ), result.warnings

    def test_connect_is_quiet_when_it_loads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, "_hermes_python", lambda home: Path(sys.executable))
        result = install_hermes_plugin(hermes_home=tmp_path / "hermes", mode=PROVIDER_MODE, configure_mcp=False)
        assert not result.warnings

    def test_hermes_own_packages_come_first(self, tmp_path):
        # Its path is added after Hermes', or a package both have would come
        # from Mnemos' environment, built perhaps for another Python.
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False)
        code = (
            "import sys, types\n"
            "agent, memory_provider = types.ModuleType('agent'), types.ModuleType('agent.memory_provider')\n"
            "memory_provider.MemoryProvider = type('MemoryProvider', (), {})\n"
            "sys.modules['agent'], sys.modules['agent.memory_provider'] = agent, memory_provider\n"
            "before = list(sys.path)\n"
            "exec(compile(open(sys.argv[1]).read(), sys.argv[1], 'exec'))\n"
            "register(types.SimpleNamespace(register_memory_provider=lambda provider: None))\n"
            "assert sys.path[:len(before)] == before, (before, sys.path)\n"
            "assert len(sys.path) > len(before)\n"
        )
        proc = subprocess.run(
            [sys.executable, "-S", "-c", code, str(home / "plugins" / "mnemos" / "__init__.py")],
            capture_output=True, text=True, timeout=120, cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "MNEMOS_DISABLE_DOTENV": "1", "SYSTEMROOT": ""},
        )
        assert proc.returncode == 0, proc.stderr

    def test_hermes_asking_again_gets_the_same_class(self):
        # It asks once per agent, and a gateway builds agents all day.
        base = type("MemoryProvider", (), {})
        assert installer_build(base) is installer_build(base)

    def test_a_hook_of_the_same_name_that_isnt_ours_stays(self, tmp_path):
        home = tmp_path / "hermes"
        hook = home / "hooks" / installer.PRELOAD_HOOK
        hook.mkdir(parents=True)
        (hook / "handler.py").write_text("def handle(event, context):\n    pass\n")
        install_hermes_plugin(hermes_home=home, mode=SIDECAR_MODE, configure_mcp=False)
        assert (hook / "handler.py").exists()

    def test_connecting_again_replaces_a_shim_mnemos_wrote(self, tmp_path):
        home = tmp_path / "hermes"
        shim = home / "plugins" / "mnemos" / "__init__.py"
        shim.parent.mkdir(parents=True)
        shim.write_text('"""Mnemos memory provider shim for Hermes Agent."""\n\nfrom mnemos import stale\n')
        result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False)
        assert "stale" not in shim.read_text()
        assert not any("differs" in warning for warning in result.warnings)

    def test_connecting_again_leaves_someone_elses_file_alone(self, tmp_path):
        home = tmp_path / "hermes"
        shim = home / "plugins" / "mnemos" / "__init__.py"
        shim.parent.mkdir(parents=True)
        shim.write_text("# someone's own provider\n")
        result = install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=False)
        assert shim.read_text() == "# someone's own provider\n"
        assert any("differs" in warning for warning in result.warnings)


class TestTheDocumentedCommand:
    """`mnemos hermes quickstart --provider` is what the docs give. It wrote no
    scope, so memory split by chat and by person, moved when a group was renamed,
    and it had no tools past the provider's."""

    def _two_chats(self, home):
        def scope(**context):
            return derive_hermes_scope(session_id="s", hermes_home=home, runtime_context=context)
        return (
            scope(user_name="Leo", user_id="42", chat_name="Leo's agent", thread_id="7", gateway_session_key="a:7"),
            scope(user_name="Leo", user_id="42", chat_name="Leo", gateway_session_key="a:dm"),
            scope(user_name="Sam", user_id="43", chat_name="Renamed group", thread_id="7", gateway_session_key="a:7"),
        )

    def test_quickstart_is_one_memory_with_its_tools(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("yes", ""))
        monkeypatch.setenv("HOME", str(tmp_path))
        home = tmp_path / ".hermes"
        result = installer.quickstart_hermes(hermes_home=home, provider=True)
        assert result.ok, result.summary()

        first, second, third = self._two_chats(home)
        assert (first.agent_id, first.person_id, first.project_scope) == ("hermes", "user", "global")
        assert first.db_path == second.db_path == third.db_path
        assert (first.person_id, first.project_scope) == (second.person_id, second.project_scope)
        assert (first.person_id, first.project_scope) == (third.person_id, third.project_scope)

        # The provider carries the tools, on the same memory: no second door to another.
        assert not installer._read_mcp_server(home, "mnemos")

    def test_quickstart_after_the_sidecar_keeps_the_sidecars_memory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("yes", ""))
        monkeypatch.setenv("HOME", str(tmp_path))
        home = tmp_path / ".hermes"
        installer.quickstart_hermes(hermes_home=home, agent_safe=True)
        sidecar = installer._sidecar_scope(installer._read_mcp_server(home, "mnemos"))

        installer.quickstart_hermes(hermes_home=home, provider=True)

        scope = derive_hermes_scope(session_id="s", hermes_home=home, runtime_context={"user_name": "Leo"})
        assert (scope.agent_id, scope.db_path) == (sidecar.agent_id, sidecar.db_path)
        assert (scope.person_id, scope.project_scope) == (sidecar.person_id, sidecar.project_scope)

    def test_a_sidecar_from_before_keeps_the_memory_it_never_named(self, tmp_path, monkeypatch):
        # Before 0.6.4 a sidecar's server named nothing, and opened the defaults.
        monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("yes", ""))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("MNEMOS_AGENT_ID", raising=False)
        monkeypatch.delenv("MNEMOS_DB_PATH", raising=False)
        home = tmp_path / ".hermes"
        home.mkdir()
        (home / "config.yaml").write_text(
            "mcp_servers:\n  mnemos:\n    command: mnemos\n    args: [serve, --mode, simple]\n"
        )
        installer.quickstart_hermes(hermes_home=home, provider=True)
        scope = derive_hermes_scope(session_id="s", hermes_home=home, runtime_context={"user_name": "Leo"})
        assert (scope.agent_id, Path(scope.db_path).name) == ("mnemos-agent", "mnemos-agent.db")

    def test_quickstart_leaves_a_store_already_there(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("yes", ""))
        monkeypatch.setenv("HOME", str(tmp_path))
        home = tmp_path / ".hermes"
        (home / "mnemos").mkdir(parents=True)
        (home / "mnemos" / "mnemos.db").write_text("")
        installer.quickstart_hermes(hermes_home=home, provider=True)
        assert not (home / "mnemos.json").exists()

    def test_quickstart_keeps_a_scope_someone_gave(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("yes", ""))
        monkeypatch.setenv("HOME", str(tmp_path))
        home = tmp_path / ".hermes"
        installer.quickstart_hermes(hermes_home=home, provider=True, agent_id="nova")
        scope = derive_hermes_scope(session_id="s", hermes_home=home, runtime_context={"user_name": "Leo"})
        assert scope.agent_id == "nova"
        assert scope.person_id == "leo"


class TestTheOtherDoor:
    """All topics reach an MCP tool through one server, which can't tell them
    apart: a note left there would land in the one slot they'd all share."""

    def test_provider_mode_has_no_such_door(self, tmp_path, monkeypatch):
        yaml = pytest.importorskip("yaml")
        monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("yes", ""))
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, activate=True)
        assert "mcp_servers" not in yaml.safe_load((home / "config.yaml").read_text())

    def test_sidecar_mode_keeps_it_because_it_has_no_other(self, tmp_path):
        yaml = pytest.importorskip("yaml")
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=SIDECAR_MODE, configure_mcp=True, activate=False)
        server = yaml.safe_load((home / "config.yaml").read_text())["mcp_servers"]["mnemos"]
        assert "tools" not in server

    def test_the_wake_says_which_tool_to_use(self, home):
        wake = _topic(home, 7).system_prompt_block()
        assert "mnemos_handoff" in wake
