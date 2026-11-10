"""Each Hermes profile is an agent of its own, as any two agents are: its own
memory, and the machine's shared memory between them. Riley, Nov 6 2026: "keep
profiles separate like any other two agents, with the shared pool like any other."
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mnemos.cli import main
from mnemos.integrations.hermes import HermesMnemosConfig, MnemosMemoryProviderCore, installer
from mnemos.integrations.hermes.installer import PROVIDER_MODE, install_hermes_plugin
from mnemos.integrations.hermes.scope import profile_agent_id, profile_store

yaml = pytest.importorskip("yaml")


@pytest.fixture
def default_home(tmp_path, monkeypatch) -> Path:
    home = Path.home() / ".hermes"
    (home / "profiles").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(tmp_path / "shared.db"))
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    monkeypatch.delenv("MNEMOS_AGENT_ID", raising=False)
    monkeypatch.delenv("MNEMOS_DB_PATH", raising=False)
    monkeypatch.setattr(installer, "_hermes_load_check", lambda home: ("yes", ""))
    return home


def _make_profile(default_home: Path, name: str) -> Path:
    home = default_home / "profiles" / name
    home.mkdir()
    return home


def _connect(*args: str) -> int:
    return main(["connect", "hermes", *args, "--write", "--no-upkeep"])


def _agent(home: Path) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize("session-1", hermes_home=str(home), platform="cli", agent_context="primary")
    return provider


def _call(provider: MnemosMemoryProviderCore, tool: str, **args) -> str:
    reply = json.loads(provider.handle_tool_call(tool, args))
    assert reply["ok"], reply
    return reply["result"]


def test_each_home_has_its_own_name(tmp_path):
    default = Path.home() / ".hermes"
    assert profile_agent_id(default) == "hermes"
    assert profile_agent_id(default / "profiles" / "Work") == "hermes-work"
    assert profile_store(default / "profiles" / "Work") == str(Path.home() / ".mnemos" / "hermes-work.db")

    # Kept anywhere else, two folders can share a name and stay two agents.
    one, other = profile_agent_id(tmp_path / "a" / "bot"), profile_agent_id(tmp_path / "b" / "bot")
    assert one.startswith("hermes-bot-") and other.startswith("hermes-bot-") and one != other
    assert profile_agent_id(tmp_path / "hermes").count("hermes") == 1


def test_connecting_a_profile_gives_it_its_own_memory(default_home, capsys):
    work = _make_profile(default_home, "work")
    assert _connect("--profile", "work") == 0

    kept = HermesMnemosConfig.load(work)
    assert (kept.agent_id, kept.db_path) == ("hermes-work", profile_store(work))
    assert yaml.safe_load((work / "config.yaml").read_text())["memory"]["provider"] == "mnemos"
    assert not (default_home / "config.yaml").exists()
    assert "hermes-work" in capsys.readouterr().out


def test_two_profiles_are_two_agents_with_the_shared_memory_between_them(default_home):
    work_home, home_home = _make_profile(default_home, "work"), _make_profile(default_home, "home")
    assert _connect("--profile", "work") == 0
    assert _connect("--profile", "home") == 0
    work, home = _agent(work_home), _agent(home_home)
    try:
        _call(work, "mnemos_capture", content="The kiln at the studio fires on Tuesdays.")
        _call(home, "mnemos_capture", content="The cat at the flat eats at six.")
        _call(work, "mnemos_capture", content="The spare house key sits under the third pot.", shared=True)

        assert "kiln" in _call(work, "mnemos_recall", query="kiln")
        assert "kiln" not in _call(home, "mnemos_recall", query="kiln")
        assert "cat" in _call(home, "mnemos_recall", query="cat flat")
        assert "cat at the flat" not in _call(work, "mnemos_recall", query="cat flat")
        assert "kiln" not in home.system_prompt_block()

        assert "third pot" in _call(home, "mnemos_recall", query="spare house key")
        assert "third pot" in _call(work, "mnemos_recall", query="spare house key")
    finally:
        work.shutdown()
        home.shutdown()


def test_a_full_copy_of_a_home_is_its_own_agent_from_the_first_turn(default_home):
    assert _connect() == 0
    original = HermesMnemosConfig.load(default_home)
    copy = default_home / "profiles" / "copy"
    copy.parent.mkdir(exist_ok=True)
    shutil.copytree(default_home, copy, ignore=shutil.ignore_patterns("profiles"))

    kept = HermesMnemosConfig.load(copy)
    assert (kept.agent_id, kept.db_path) == ("hermes-copy", profile_store(copy))
    assert (HermesMnemosConfig.load(default_home).agent_id, original.agent_id) == ("hermes", "hermes")

    provider = _agent(copy)
    try:
        assert provider.scope.agent_id == "hermes-copy"
    finally:
        provider.shutdown()

    assert _connect("--profile", "copy") == 0
    assert HermesMnemosConfig.load(copy).agent_id == "hermes-copy"


def test_a_renamed_profile_is_the_same_agent_with_the_same_memory(default_home):
    # `hermes profile rename`, or a home moved by hand: nothing is left behind to be a copy of.
    work = _make_profile(default_home, "work")
    assert _connect("--profile", "work") == 0
    renamed = default_home / "profiles" / "studio"
    work.rename(renamed)
    kept = HermesMnemosConfig.load(renamed)
    assert (kept.agent_id, kept.db_path) == ("hermes-work", profile_store(work))


def test_a_full_copy_beside_another_provider_stops_sharing_when_connected(default_home):
    (default_home / "config.yaml").write_text("memory:\n  provider: honcho\n")
    assert _connect() == 0
    assert "--agent-id" in installer._read_mcp_server(default_home, "mnemos")["args"]
    copy = default_home / "profiles" / "copy"
    copy.parent.mkdir(exist_ok=True)
    shutil.copytree(default_home, copy, ignore=shutil.ignore_patterns("profiles"))

    assert _connect("--profile", "copy") == 0

    args = installer._read_mcp_server(copy, "mnemos")["args"]
    assert args[args.index("--agent-id") + 1] == "hermes-copy"
    assert args[args.index("--db-path") + 1] == profile_store(copy)
    original = installer._read_mcp_server(default_home, "mnemos")["args"]
    assert original[original.index("--agent-id") + 1] == "hermes"


def test_connecting_names_the_other_profiles(default_home, capsys):
    _make_profile(default_home, "work")
    assert _connect() == 0
    said = capsys.readouterr().out
    assert "work" in said and "--profile work" in said


def test_a_profile_that_is_not_there_is_said_plainly(default_home, capsys):
    assert _connect("--profile", "nope") == 1
    assert "no profile called 'nope'" in capsys.readouterr().err


def test_the_hermes_commands_take_a_profile_too(default_home, capsys):
    work = _make_profile(default_home, "work")
    assert main(["hermes", "quickstart", "--provider", "--profile", "work"]) == 0
    assert HermesMnemosConfig.load(work).agent_id == "hermes-work"
    assert not (default_home / "config.yaml").exists()
    capsys.readouterr()
    assert main(["hermes", "doctor", "--profile", "work"]) == 0
    assert str(work) in capsys.readouterr().out
    assert main(["hermes", "doctor", "--profile", "nope"]) == 1
    assert "no profile called 'nope'" in capsys.readouterr().err


def test_profile_is_hermes_own(default_home, capsys):
    assert main(["connect", "codex", "--profile", "work", "--write", "--no-upkeep"]) == 1
    assert "Hermes" in capsys.readouterr().err


def test_connecting_twice_changes_nothing(default_home, capsys):
    assert _connect() == 0
    capsys.readouterr()
    before = (default_home / "config.yaml").read_text()
    assert _connect() == 0
    assert "Nothing to do" in capsys.readouterr().out
    assert (default_home / "config.yaml").read_text() == before


def test_connecting_keeps_whose_memory_it_is_and_which_part(default_home):
    # Recall looks only there: rewriting them cut the agent off from what it had.
    (default_home / "mnemos.json").write_text(json.dumps({
        "agent_id": "hermes", "db_path": str(Path.home() / ".mnemos" / "hermes.db"),
        "person_id": "riley", "project_scope": "work",
    }))
    agent = _agent(default_home)
    _call(agent, "mnemos_capture", content="The kiln at the studio fires on Tuesdays.")
    agent.shutdown()

    assert _connect() == 0

    kept = HermesMnemosConfig.load(default_home)
    assert (kept.person_id, kept.project_scope) == ("riley", "work")
    agent = _agent(default_home)
    try:
        assert "kiln" in _call(agent, "mnemos_recall", query="kiln studio")
    finally:
        agent.shutdown()


def test_the_same_from_a_server_that_names_them(default_home):
    store = str(Path.home() / ".mnemos" / "hermes.db")
    (default_home / "config.yaml").write_text(yaml.safe_dump({"mcp_servers": {"mnemos": {
        "command": "mnemos",
        "args": ["serve", "--mode", "simple", "--agent-id", "hermes", "--db-path", store,
                 "--person-id", "riley", "--project-scope", "work"],
    }}}))
    assert _connect() == 0
    kept = HermesMnemosConfig.load(default_home)
    assert (kept.db_path, kept.person_id, kept.project_scope) == (store, "riley", "work")


def test_naming_another_memory_starts_fresh_for_who_and_what(default_home):
    (default_home / "mnemos.json").write_text(json.dumps({
        "agent_id": "hermes", "db_path": str(Path.home() / ".mnemos" / "hermes.db"),
        "person_id": "riley", "project_scope": "work",
    }))
    assert _connect("--agent-id", "nova") == 0
    kept = HermesMnemosConfig.load(default_home)
    assert (kept.agent_id, kept.person_id, kept.project_scope) == ("nova", "user", "global")


def _copy_of(default_home: Path, original: Path, name: str) -> Path:
    copy = default_home / "profiles" / name
    copy.parent.mkdir(exist_ok=True)
    shutil.copytree(original, copy, ignore=shutil.ignore_patterns("profiles"))
    return copy


def test_a_copy_stays_itself_when_the_one_it_was_copied_from_goes(default_home):
    original = _make_profile(default_home, "first")
    assert _connect("--profile", "first") == 0
    copy = _copy_of(default_home, original, "second")
    agent = _agent(copy)
    _call(agent, "mnemos_capture", content="The second profile keeps bees.")
    agent.shutdown()

    shutil.rmtree(original)

    kept = HermesMnemosConfig.load(copy)
    assert (kept.agent_id, kept.db_path) == ("hermes-second", profile_store(copy))
    agent = _agent(copy)
    try:
        assert "bees" in _call(agent, "mnemos_recall", query="bees")
    finally:
        agent.shutdown()


def test_a_renamed_profile_stays_itself_when_a_new_one_takes_its_old_name(default_home):
    work = _make_profile(default_home, "work")
    assert _connect("--profile", "work") == 0
    store = profile_store(work)
    renamed = default_home / "profiles" / "studio"
    work.rename(renamed)
    _agent(renamed).shutdown()

    _make_profile(default_home, "work")

    kept = HermesMnemosConfig.load(renamed)
    assert (kept.agent_id, kept.db_path) == ("hermes-work", store)


def test_two_memories_connect_keeps_the_one_it_wakes_from_and_names_the_other(default_home, capsys):
    wakes, tools = (str(Path.home() / ".mnemos" / name) for name in ("wakes.db", "tools.db"))
    install_hermes_plugin(hermes_home=default_home, mode=PROVIDER_MODE, activate=True, agent_id="hermes", db_path=wakes)
    config = yaml.safe_load((default_home / "config.yaml").read_text())
    config["mcp_servers"] = {"mnemos": {
        "command": "mnemos", "args": ["serve", "--mode", "simple", "--agent-id", "hermes", "--db-path", tools],
    }}
    (default_home / "config.yaml").write_text(yaml.safe_dump(config))

    assert _connect() == 0

    assert HermesMnemosConfig.load(default_home).db_path == wakes
    assert "mcp_servers" not in yaml.safe_load((default_home / "config.yaml").read_text())
    assert tools in capsys.readouterr().out


def _copy_from_before_0_6_4(default_home: Path, name: str) -> Path:
    """A copy of the default home's config, from when it didn't say whose it was."""
    copy = _make_profile(default_home, name)
    raw = json.loads((default_home / "mnemos.json").read_text())
    del raw["hermes_home"]
    (copy / "mnemos.json").write_text(json.dumps(raw))
    return copy


def test_a_copy_from_before_is_left_as_it_is_and_told_how_to_have_its_own(default_home, capsys, monkeypatch):
    assert _connect() == 0
    copy = _copy_from_before_0_6_4(default_home, "old")
    capsys.readouterr()

    assert _connect("--profile", "old") == 0

    told = "mnemos connect hermes --profile old --agent-id hermes-old --write"
    assert told in capsys.readouterr().out
    assert HermesMnemosConfig.load(copy).agent_id == "hermes"

    # Said from the home it shares with, too: that's where someone's likelier to look.
    monkeypatch.setenv("HERMES_HOME", str(default_home))
    assert _connect() == 0
    assert told in capsys.readouterr().out

    # And taken up, it's its own, and nothing is left to say.
    assert _connect("--profile", "old", "--agent-id", "hermes-old") == 0
    assert HermesMnemosConfig.load(copy).agent_id == "hermes-old"
    assert "same memory" not in capsys.readouterr().out


def test_nothing_is_said_when_nothing_is_shared(default_home, capsys):
    _make_profile(default_home, "work")
    assert _connect() == 0
    assert _connect("--profile", "work") == 0
    assert "same memory" not in capsys.readouterr().out


def test_a_profile_reads_its_own_setup_when_the_environment_names_another_home(default_home, monkeypatch):
    # Recent Hermes runs `hermes -p work` with HERMES_HOME still at its root, and hands the
    # provider the profile's home. Read from the root, the agent told the person its wake and
    # its cue weren't set up when they were, and offered a command for them.
    work = _make_profile(default_home, "work")
    assert _connect() == 0
    assert _connect("--profile", "work") == 0
    monkeypatch.setenv("HERMES_HOME", str(default_home))

    agent = _agent(work)
    try:
        wake = agent.system_prompt_block()
    finally:
        agent.shutdown()

    assert "--agent-id hermes-work" in wake, "premise: this is the profile's first session"
    assert "waking with this memory" not in wake and "the memories that bear on each message" not in wake
    assert "upkeep between sessions" in wake
