"""Inside Hermes, every setting of Mnemos's is the speaking profile's.

One Hermes gateway can serve several profiles. Its own environment is the one
it was started for; what a profile set for itself Hermes hands out by name
(``agent.secret_scope.get_secret``), for the profile that is speaking. Mnemos
read some of its settings straight from the process's environment, so on such
a gateway the launch profile's were everyone's:

- ``MNEMOS_SHARED_MEMORY`` and ``MNEMOS_SHARED_MEMORY_DB``: a profile that had
  turned sharing off still shared, into the file the launch profile named;
- ``MNEMOS_AGENT_MODEL``: every profile's writes were signed with it;
- Mnemos's numbers (``MNEMOS_CONSOLIDATION_DECAY_RATE`` and the like), in the
  conversation and in what its upkeep process was handed;
- and the marks Claude Code leaves on its own processes (``CLAUDECODE``,
  ``CLAUDE_CODE_SESSION_ID``): a Hermes started from a Claude Code terminal
  signed its agent's memories with that session's model, read from its
  transcript.

The first test is the wide one: it watches every read of the process's
environment that Mnemos's own code makes through a whole conversation, and no
name of Mnemos's, a harness's or a provider's may be among them.
"""

from __future__ import annotations

import collections.abc
import json
import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest

import mnemos
from mnemos import authorship, llm, shared_memory, simple_runtime
from mnemos.config.loader import load_config
from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore

_PACKAGE = str(Path(mnemos.__file__).resolve().parent) + os.sep
_OS_MODULE = os.__file__


class _Watched(collections.abc.MutableMapping):
    """The process's environment, noting each name Mnemos's own code reads
    from it and each place it takes the whole of it."""

    def __init__(self, real) -> None:
        self._real = real
        self.read: dict[str, set[str]] = {}
        self.whole: set[str] = set()

    def _reader(self) -> str:
        frame = sys._getframe(2)
        while frame is not None and frame.f_code.co_filename in (_OS_MODULE, __file__):
            frame = frame.f_back  # os.getenv, and this class's own methods
        if frame is None or not frame.f_code.co_filename.startswith(_PACKAGE):
            return ""
        return f"{frame.f_code.co_filename[len(_PACKAGE):]}:{frame.f_code.co_name}"

    def _note(self, name) -> None:
        reader = self._reader()
        if reader:
            self.read.setdefault(str(name), set()).add(reader)

    def __getitem__(self, name):
        self._note(name)
        return self._real[name]

    def get(self, name, default=None):
        self._note(name)
        return self._real.get(name, default)

    def __contains__(self, name) -> bool:
        self._note(name)
        return name in self._real

    def __iter__(self):
        reader = self._reader()
        if reader:
            self.whole.add(reader)
        return iter(self._real)

    def __len__(self) -> int:
        return len(self._real)

    def __setitem__(self, name, value) -> None:
        self._real[name] = value

    def __delitem__(self, name) -> None:
        del self._real[name]

    def copy(self):
        reader = self._reader()
        if reader:
            self.whole.add(reader)
        return self._real.copy()


@pytest.fixture
def hermes(monkeypatch):
    """A Hermes whose ``get_secret`` answers for the profile that is speaking
    (``speaking``, filled by the test) and never from the process's
    environment, as on a gateway that serves several profiles."""
    speaking: dict[str, str] = {"MNEMOS_MAINTENANCE": "inline"}
    asked: set[str] = set()

    def get_secret(name, default=None):
        asked.add(name)
        return speaking.get(name, default)

    agent = types.ModuleType("agent")
    agent.secret_scope = types.ModuleType("agent.secret_scope")
    agent.secret_scope.get_secret = get_secret
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", agent.secret_scope)
    return types.SimpleNamespace(speaking=speaking, asked=asked)


def _start(tmp_path: Path, **context) -> MnemosMemoryProviderCore:
    home = tmp_path / "hermes" / "profiles" / "b"
    home.mkdir(parents=True, exist_ok=True)
    provider = MnemosMemoryProviderCore()
    provider.initialize(
        "20261110_010000_b", platform="telegram", hermes_home=str(home),
        agent_context="primary", agent_identity="b", agent_workspace="hermes", **context,
    )
    return provider


def _call(provider: MnemosMemoryProviderCore, tool: str, **args) -> str:
    reply = json.loads(provider.handle_tool_call(tool, args))
    assert reply["ok"], reply
    return reply["result"]


def _signature(provider: MnemosMemoryProviderCore, words: str) -> str:
    conn = sqlite3.connect(provider.scope.db_path)
    try:
        return conn.execute("SELECT author_model FROM engrams WHERE content = ?", (words,)).fetchone()[0] or ""
    finally:
        conn.close()


def test_no_setting_is_read_from_the_gateways_own_environment(hermes, tmp_path, monkeypatch):
    watched = _Watched(os.environ)
    monkeypatch.setattr(os, "environ", watched)

    provider = _start(tmp_path)
    try:
        provider.system_prompt_block()
        provider.on_turn_start(1, "hello", model="made-up/model-1")
        provider.prefetch("what did Sam decide about the east pier survey")
        _call(provider, "mnemos_capture", content="Sam decided the east pier survey waits for spring.",
              impact="surveys wait on the weather")
        _call(provider, "mnemos_capture", content="The harbour office opens at nine.", shared=True)
        _call(provider, "mnemos_capture", content="Always greet Sam by name.", standing=True)
        _call(provider, "mnemos_recall", query="east pier survey")
        _call(provider, "mnemos_handoff", text="We were planning the spring survey.")
        _call(provider, "mnemos_journal", text="A quiet day by the water.")
        _call(provider, "mnemos_note", text="Ask Sam about the tide tables.")
        _call(provider, "mnemos_introduce", agent_model="made-up/model-1", agent_name="Probe")
        _call(provider, "mnemos_health")
        _call(provider, "mnemos_maintain")
        _call(provider, "mnemos_page")
        provider.on_memory_write("add", "memory", "The east pier is closed on Mondays.")
        provider.on_session_end([])
        provider.backup_paths()
        simple_runtime._hosted_upkeep_env(False)
    finally:
        provider.shutdown()

    # The one exception: sharing turned off where the gateway started stays off,
    # since it can only withhold (tests/test_hermes_sharing_turned_off_stays_off.py).
    allowed = {"MNEMOS_SHARED_MEMORY": {"shared_memory.py:_turned_off_where_the_host_started"}}
    theirs = sorted(
        f"{name} ({', '.join(sorted(readers - allowed.get(name, set())))})"
        for name, readers in watched.read.items()
        if (name.startswith(("MNEMOS_", "CLAUDE")) or name in ("AI_AGENT", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")
            or name.endswith("_API_KEY")) and readers - allowed.get(name, set())
    )
    assert not theirs, f"read from the gateway's own environment: {theirs}"
    # The one place the whole of it is taken: the upkeep process's plain names.
    assert watched.whole <= {"simple_runtime.py:_hosted_upkeep_env"}, watched.whole
    # And the wide test saw what it was for: these are asked of Hermes.
    assert {"MNEMOS_SHARED_MEMORY", "MNEMOS_AGENT_MODEL", "MNEMOS_MAINTENANCE",
            "MNEMOS_CONSOLIDATION_DECAY_RATE", "MNEMOS_DB_PATH"} <= hermes.asked


def test_a_profile_that_turned_sharing_off_shares_nothing(hermes, tmp_path, monkeypatch):
    launch_profiles = tmp_path / "launch-shared.db"
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(launch_profiles))  # the gateway's own
    hermes.speaking["MNEMOS_SHARED_MEMORY"] = "off"

    provider = _start(tmp_path)
    try:
        said = _call(provider, "mnemos_capture", content="The harbour office opens at nine.", shared=True)
        _call(provider, "mnemos_recall", query="harbour office")
    finally:
        provider.shutdown()
    assert "shared memory is off" in said
    assert not launch_profiles.exists() and not (Path.home() / ".mnemos" / "shared-memory.db").exists()


def test_what_a_profile_shares_goes_where_that_profile_says(hermes, tmp_path, monkeypatch):
    launch_profiles, its_own = tmp_path / "launch-shared.db", tmp_path / "b-shared.db"
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY_DB", str(launch_profiles))
    hermes.speaking["MNEMOS_SHARED_MEMORY_DB"] = str(its_own)

    provider = _start(tmp_path)
    try:
        _call(provider, "mnemos_capture", content="The harbour office opens at nine.", shared=True)
        assert shared_memory.path() == its_own
        handed = simple_runtime._hosted_upkeep_env(False)
    finally:
        provider.shutdown()
    assert its_own.exists() and not launch_profiles.exists()
    assert handed["MNEMOS_SHARED_MEMORY_DB"] == str(its_own)


def test_upkeep_runs_on_this_profiles_numbers(hermes, tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMOS_CONSOLIDATION_DECAY_RATE", "0.9")  # the gateway's own
    monkeypatch.setenv("MNEMOS_CONSOLIDATION_MIN_IDLE_MINUTES", "0")
    hermes.speaking["MNEMOS_CONSOLIDATION_DECAY_RATE"] = "0.2"

    provider = _start(tmp_path)
    try:
        numbers = load_config()["consolidation"]
        handed = simple_runtime._hosted_upkeep_env(False)
    finally:
        provider.shutdown()
    assert numbers["decay_rate"] == 0.2
    assert numbers["min_idle_minutes"] != 0, "a number set for the gateway's profile was this one's"
    assert handed["MNEMOS_CONSOLIDATION_DECAY_RATE"] == "0.2"
    assert "MNEMOS_CONSOLIDATION_MIN_IDLE_MINUTES" not in handed


def test_outside_hermes_the_numbers_are_the_environments_as_ever(monkeypatch):
    monkeypatch.setenv("MNEMOS_CONSOLIDATION_DECAY_RATE", "0.9")
    monkeypatch.setenv("MNEMOS_STORE_SOMETHING_NEW", "kept")  # a name the config has never had
    assert not llm.host_secrets_active()
    config = load_config()
    assert config["consolidation"]["decay_rate"] == 0.9
    assert config["store"]["something_new"] == "kept"


def test_a_write_is_signed_by_hermess_model_whatever_started_hermes(hermes, tmp_path, monkeypatch):
    """Hermes started from a Claude Code terminal carries that session's marks,
    and the gateway's profile may have named a model of its own."""
    session = "11111111-2222-3333-4444-555555555555"
    transcripts = Path.home() / ".claude" / "projects" / "-some-project"
    transcripts.mkdir(parents=True)
    (transcripts / f"{session}.jsonl").write_text(json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-4-7", "content": []}}
    ) + "\n")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", "launch-profile/model")
    assert authorship.detect_harness_model(os.environ) == "claude-opus-4-7"  # the transcript is real

    provider = _start(tmp_path)
    try:
        assert authorship.harness_session() == "" and not authorship.in_claude_code()
        _call(provider, "mnemos_capture", content="Hermes has named no model yet.")
        unsigned = _signature(provider, "Hermes has named no model yet.")
        provider.on_turn_start(1, "hello", model="b-profile/model")
        _call(provider, "mnemos_capture", content="Now Hermes has named one.")
        signed = _signature(provider, "Now Hermes has named one.")
        hermes.speaking["MNEMOS_AGENT_MODEL"] = "what-b-set/model"
        _call(provider, "mnemos_capture", content="And this profile set one itself.")
        set_here = _signature(provider, "And this profile set one itself.")
    finally:
        provider.shutdown()
    assert unsigned == "", "signed from the terminal Hermes was started in, or the gateway's own profile"
    assert signed == "b-profile/model"
    assert set_here == "what-b-set/model"


def test_outside_hermes_claude_codes_marks_are_read_as_ever(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setenv("MNEMOS_AGENT_MODEL", "set-here/model")
    assert not llm.host_secrets_active()
    assert authorship.in_claude_code()
    assert authorship.harness_session() == "11111111-2222-3333-4444-555555555555"
    assert authorship.resolve_author_model() == "set-here/model"
