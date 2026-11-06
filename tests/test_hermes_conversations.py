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
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from mnemos.authorship import clean_session_id
from mnemos.integrations.hermes import MnemosMemoryProviderCore, installer
from mnemos.integrations.hermes.installer import PROVIDER_MODE, SIDECAR_MODE, install_hermes_plugin
from mnemos.integrations.hermes.scope import save_hermes_mnemos_config

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
    reply = json.loads(provider.handle_tool_call("mnemos_identity_handoff", {"text": text}))
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
        health.handle_tool_call("mnemos_identity_correct", {"target_id": row["id"], "action": "forget"})

        wake = _topic(home, 7, session="fresh-7").system_prompt_block()
        assert "pre-op bloodwork" not in wake


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
        topic.handle_tool_call("mnemos_identity_capture", {"content": "The knee surgery is on March 3."})
        rows = topic._runtime._store._get_conn().execute("SELECT author_session FROM engrams").fetchall()
        assert rows and all(not row["author_session"] for row in rows)

    def test_recall_by_id_says_the_note_is_its_own(self, home):
        topic = _topic(home, 7)
        _leave(topic, HEALTH)
        row = topic._runtime._store._get_conn().execute(
            "SELECT id FROM hypomnema_entries WHERE content = ?", (HEALTH,),
        ).fetchone()
        reply = json.loads(topic.handle_tool_call("mnemos_identity_recall", {"query": row["id"]}))
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
            topic.handle_tool_call("mnemos_identity_capture", {
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
            "print(MnemosMemoryProvider().name)\n"
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


class TestTheOtherDoor:
    """All topics reach an MCP tool through one server, which can't tell them
    apart: a note left there would land in the one slot they'd all share."""

    def test_provider_mode_leaves_the_mcp_handoff_out(self, tmp_path):
        yaml = pytest.importorskip("yaml")
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=PROVIDER_MODE, configure_mcp=True, activate=True)
        server = yaml.safe_load((home / "config.yaml").read_text())["mcp_servers"]["mnemos"]
        assert server["tools"]["exclude"] == ["mnemos_handoff"]

    def test_sidecar_mode_keeps_it_because_it_has_no_other(self, tmp_path):
        yaml = pytest.importorskip("yaml")
        home = tmp_path / "hermes"
        install_hermes_plugin(hermes_home=home, mode=SIDECAR_MODE, configure_mcp=True, activate=False)
        server = yaml.safe_load((home / "config.yaml").read_text())["mcp_servers"]["mnemos"]
        assert "tools" not in server

    def test_the_wake_says_which_tool_to_use(self, home):
        wake = _topic(home, 7).system_prompt_block()
        assert "mnemos_identity_handoff" in wake
