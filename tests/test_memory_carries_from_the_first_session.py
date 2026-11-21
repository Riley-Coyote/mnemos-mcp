"""The first session makes sure memory carries (0.5.0).

Someone who sets Mnemos up through their agent, or adds only its server, can
end up with memory that doesn't load by itself and with quiet hours no one
asked them about. So in Claude Code the first session starts by settling
both, from what is really on the machine: the agent offers to set up its
wake and runs setup itself with a yes, asks once about the quiet hours (yes
by default), and says in a line what is already on. Then the get-to-know-you
ritual, as before. Outside Claude Code the ritual is exactly what it was.

Setup keeps the person's answer about the quiet hours, so the first session
doesn't ask again what setup already asked; without a terminal, setup hands
the question to the agent that ran it. Doctor says whether the wake is set.

Every scheduler here is the suite's fake (tests/conftest.py): nothing reaches
the machine running the tests.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from mnemos import cli
from mnemos.cli import main
from mnemos.setup import scheduler, state
from mnemos.simple_runtime import MnemosRuntime, _ONBOARDING_RITUAL

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
MNEMOS = "/opt/mnemos/bin/mnemos"
OPUS = "claude-opus-5-5"
FIRST_QUESTION = "1. Ask what they would like you to call them."
NO_WAKE = "You won't wake with this memory by yourself yet"
HOURS_QUESTION = "Quiet hours: no one has asked them yet."
HOURS_LABELS = {f"com.mnemos.nova.{name}" for name in ("hour-mine", "hour-ours")}


@pytest.fixture
def claude_code(monkeypatch):
    """A session in Claude Code, which marks the environment of the MCP
    servers it starts; and the Mnemos that set up this machine."""
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(state, "mnemos_command", lambda: MNEMOS)
    monkeypatch.setattr(cli, "_mnemos_command", lambda: MNEMOS)


@pytest.fixture
def launchd(monkeypatch, os_scheduler):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "launchd")
    return os_scheduler


@pytest.fixture
def claude(tmp_path, monkeypatch) -> Path:
    """A claude command on PATH, which the quiet hours run."""
    folder = tmp_path / "local-bin"
    folder.mkdir()
    binary = folder / "claude"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.delenv("MNEMOS_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(folder))
    return binary


@pytest.fixture
def no_claude(tmp_path, monkeypatch):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.delenv("MNEMOS_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(empty))


def _db(agent: str = "nova") -> Path:
    return Path.home() / ".mnemos" / f"{agent}.db"


def _runtime(agent: str = "nova") -> MnemosRuntime:
    return MnemosRuntime(
        db_path=str(_db(agent)), use_dedicated_model=False, **{**SCOPE, "agent_id": agent},
    )


def _packet(agent: str = "nova") -> str:
    runtime = _runtime(agent)
    try:
        return runtime.context()
    finally:
        runtime.close()


def _command(*parts: str, agent: str = "nova") -> str:
    return state.command_line(agent, _db(agent), *parts, mnemos=MNEMOS)


def _as_the_agent_runs(command: str) -> int:
    """Run a command the packet gave, as the agent would in its shell."""
    executable, *arguments = shlex.split(command)
    assert executable == MNEMOS
    return main(arguments)


# ── What the first session settles ──


def test_a_first_session_with_nothing_set_settles_the_wake_and_the_hours_first(
    claude_code, launchd, claude
):
    packet = _packet()

    wake = _command("hooks", "install", "claude-code", "--write")
    yes = _command("daemon", "install", "--hours", "--write")
    no = _command("daemon", "uninstall", "--hours", "--write")
    assert NO_WAKE in packet and f"\n  {wake}\n" in packet, packet
    assert HOURS_QUESTION in packet, packet
    assert f"\n  yes: {yes}\n" in packet and f"\n  no: {no}\n" in packet, packet
    assert "use some of its usage" in packet and "goes to Anthropic" in packet
    assert "Yes is the default: they're on unless they say no." in packet
    # Settled before the first question of the ritual, which still follows whole.
    assert packet.index(NO_WAKE) < packet.index(HOURS_QUESTION) < packet.index(FIRST_QUESTION)
    assert "5. Call mnemos_introduce" in packet


def test_the_agents_yes_to_its_wake_sets_it_up_for_this_memory(claude_code, launchd, no_claude, capsys):
    packet = _packet()
    wake = next(line.strip() for line in packet.splitlines() if "hooks install" in line)

    assert _as_the_agent_runs(wake) == 0
    capsys.readouterr()

    assert state.wake_hook(str(_db())) is not None
    again = _packet()
    assert NO_WAKE not in again
    assert "- Already set: you'll wake with this memory at the start of every session." in again
    assert again.index("Already set") < again.index(FIRST_QUESTION)


def test_a_wake_for_another_agents_memory_does_not_count(claude_code, launchd, no_claude, capsys):
    other = _command("hooks", "install", "claude-code", "--write", agent="sage")
    assert _as_the_agent_runs(other) == 0
    capsys.readouterr()

    assert state.wake_hook(str(_db("sage"))) is not None
    assert state.wake_hook(str(_db("nova"))) is None
    assert NO_WAKE in _packet("nova")


def test_the_agents_yes_to_the_hours_schedules_them_and_the_session_says_so(
    claude_code, launchd, claude, capsys
):
    yes = _command("daemon", "install", "--hours", "--write")
    assert _as_the_agent_runs(yes) == 0
    capsys.readouterr()

    assert HOURS_LABELS <= launchd.loaded
    assert state.hours_choice("nova") == "yes"
    packet = _packet()
    assert HOURS_QUESTION not in packet
    assert "- Already set: quiet hours are on (" in packet
    assert "they can turn quiet hours off whenever they like." in packet


def test_the_agents_no_to_the_hours_is_kept_and_never_asked_again(
    claude_code, launchd, claude, capsys
):
    no = _command("daemon", "uninstall", "--hours", "--write")
    assert _as_the_agent_runs(no) == 0
    capsys.readouterr()

    assert not HOURS_LABELS & launchd.loaded
    assert state.hours_choice("nova") == "no"
    packet = _packet()
    assert HOURS_QUESTION not in packet
    assert "quiet hours" not in packet.lower().split(FIRST_QUESTION.lower())[0]


def test_a_preview_keeps_no_answer(claude_code, launchd, claude, capsys):
    assert main(["daemon", "uninstall", "--agent-id", "nova", "--hours"]) == 0
    assert main(["daemon", "install", "--agent-id", "nova", "--hours"]) == 0
    capsys.readouterr()
    assert state.hours_choice("nova") is None
    assert HOURS_QUESTION in _packet()


def test_with_no_claude_command_the_hours_are_not_offered(claude_code, launchd, no_claude):
    packet = _packet()
    assert NO_WAKE in packet
    assert "quiet hours" not in packet.lower()


def test_where_nothing_can_schedule_the_hours_they_are_not_offered(
    claude_code, monkeypatch, os_scheduler, claude
):
    monkeypatch.setattr(scheduler, "detect_backend", lambda system=None: "unsupported")
    assert "quiet hours" not in _packet().lower()


def test_outside_claude_code_the_ritual_is_as_it_was(launchd, claude):
    assert _packet() == _ONBOARDING_RITUAL


def test_an_agent_that_already_knows_its_person_is_not_told_they_are_strangers(launchd, claude):
    """0.6.0: an empty store is a new memory, not a new person. An agent that
    knows its person from what it carries in (instructions, notes, files) asks
    only what it doesn't know, still introduces itself and closes, and says
    it now remembers across sessions too. What the person asks to be always
    remembered is kept standing, so it never fades."""
    packet = _packet()
    assert "This is the first time you and this human meet" not in packet
    assert "you may already know them from what you carry into this session" in packet
    assert "don't ask what you can already answer" in packet
    assert "If they are new to you, ask each question." in packet
    assert "standing=true, so it never fades" in packet.split("3. ", 1)[1].split("\n", 1)[0]
    assert "from now on you remember across sessions too" in packet.split("6. ", 1)[1]
    assert "5. Call mnemos_introduce" in packet


def test_an_agent_that_introduced_itself_first_still_says_it_now_remembers(launchd, claude):
    """An agent may introduce itself before it reads its memory, and then wakes
    to the shorter reminder: it, too, says so to someone it already knew."""
    runtime = _runtime()
    try:
        runtime.introduce(agent_model=OPUS)
        packet = runtime.context()
    finally:
        runtime.close()
    assert packet.startswith("ONBOARDING - almost done"), packet
    assert "If you already know one, capture it instead of asking." in packet
    assert "from now on you remember across sessions too" in packet


def test_the_setup_part_never_costs_the_packet(claude_code, launchd, claude, monkeypatch):
    def broken(db_path):
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(state, "wake_hook", broken)
    assert _packet() == _ONBOARDING_RITUAL


def test_an_unfinished_ritual_still_carries_what_is_left_to_settle(claude_code, launchd, claude):
    runtime = _runtime()
    try:
        runtime.capture("Riley keeps bees on the roof.", signed_as=OPUS)
    finally:
        runtime.close()

    packet = _packet()
    left = packet.split("ONBOARDING - almost done\n", 1)[1]
    assert left.index(NO_WAKE) < left.index(HOURS_QUESTION) < left.index("Call mnemos_introduce")


def test_a_finished_ritual_brings_no_setup_at_all(claude_code, launchd, claude):
    runtime = _runtime()
    try:
        runtime.introduce(OPUS)
        runtime.capture("Riley keeps bees on the roof.", signed_as=OPUS)
    finally:
        runtime.close()

    packet = _packet()
    assert "ONBOARDING" not in packet
    assert NO_WAKE not in packet and HOURS_QUESTION not in packet


# ── What setup keeps, and hands to the agent ──


def _claude_code_setup(*extra: str) -> int:
    return main([
        "hooks", "install", "claude-code", "--agent-id", "nova", "--person-id", "riley",
        "--project-scope", "demo", "--write", *extra,
    ])


def test_without_a_terminal_setup_leaves_the_hours_to_the_first_session(claude_code, launchd, claude, capsys):
    assert _claude_code_setup() == 0
    out = capsys.readouterr().out

    assert "Quiet hours: off. They're time between sessions that's the agent's own" in out
    assert "it will tell you about them in its first session and set up only the ones you want" in out
    assert "If you're an agent setting Mnemos up for someone: don't turn them on now." in out
    assert "yes is the default" not in out and "on unless they say no" not in out
    assert not HOURS_LABELS & launchd.loaded, "nothing is scheduled before anyone chooses it"
    assert state.hours_choice("nova") is None


def test_after_a_no_setup_does_not_hand_the_question_on_again(claude_code, launchd, claude, capsys):
    state.record_hours_choice("nova", "no")
    assert _claude_code_setup() == 0
    out = capsys.readouterr().out
    assert "Quiet hours: off, as chosen." in out
    assert "If you're an agent" not in out


def test_at_a_terminal_setup_asks_nothing_and_keeps_nothing(claude_code, launchd, claude, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_can_ask", lambda: True)

    def never(question: str = "") -> str:
        raise AssertionError(f"asked: {question}")

    monkeypatch.setattr("builtins.input", never)
    assert _claude_code_setup() == 0
    capsys.readouterr()
    assert state.hours_choice("nova") is None
    assert not HOURS_LABELS & launchd.loaded


def test_an_unreadable_choice_is_no_choice():
    folder = state.hours_dir("nova")
    folder.mkdir(parents=True)
    for text in ("", "{", '"yes"', '{"choice": "maybe"}', "[1]"):
        (folder / state.CHOICE_FILE).write_text(text)
        assert state.hours_choice("nova") is None


# ── Doctor ──


def test_doctor_says_whether_claude_code_wakes_this_memory(claude_code, launchd, claude, capsys):
    scope = ["--agent-id", "nova", "--db-path", str(_db())]
    assert main([*scope, "doctor"]) == 0
    out = capsys.readouterr().out
    wake = _command("hooks", "install", "claude-code", "--write")
    assert f"Wake:         not automatic in Claude Code; to set it up: {wake}\n" in out
    assert not _db().exists(), "doctor creates nothing"

    assert _as_the_agent_runs(wake) == 0
    capsys.readouterr()
    assert main([*scope, "doctor"]) == 0
    settings = Path.home() / ".claude" / "settings.json"
    assert f"Wake:         automatic in Claude Code (its session-start hook, in {settings})" in (
        capsys.readouterr().out
    )


def test_doctor_says_nothing_of_claude_code_where_there_is_none(launchd, no_claude, capsys):
    assert main(["--agent-id", "nova", "doctor"]) == 0
    assert "Wake:" not in capsys.readouterr().out
