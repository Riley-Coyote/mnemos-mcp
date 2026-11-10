"""Inside Hermes, sharing turned off where Hermes starts stays off.

Inside Hermes every setting of Mnemos's is asked of Hermes, for the profile
that is speaking. On a gateway that serves profiles Hermes answers from the
profile's own ``.env`` and never from the environment the gateway was started
in. Release 0.6.6 read ``MNEMOS_SHARED_MEMORY`` from that environment, so
someone who had turned sharing off there (a shell or service variable) found
it on again after the upgrade: what the agent marked as shared went to the
machine's shared memory, and every recall searched it.

Now, when Hermes gives nothing for the profile and the environment Hermes was
started in says off, sharing is off. It is the one setting read from there,
because it can only withhold. A profile's own answer, on or off, always wins,
and outside Hermes nothing changes.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

from mnemos import llm, shared_memory, simple_runtime
from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore

_KEPT_BY_ANOTHER = "The lighthouse keeper's spare key hangs behind the tide clock."


@pytest.fixture
def hermes(monkeypatch):
    """A Hermes whose ``get_secret`` answers for the profile that is speaking
    (``speaking``, filled by the test) and never from the process's own
    environment, as on a gateway that serves profiles."""
    speaking: dict[str, str] = {"MNEMOS_MAINTENANCE": "inline"}
    agent = types.ModuleType("agent")
    agent.secret_scope = types.ModuleType("agent.secret_scope")
    agent.secret_scope.get_secret = lambda name, default=None: speaking.get(name, default)
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", agent.secret_scope)
    monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    return speaking


@pytest.fixture
def shared_already():
    """Something another agent on this machine shared before, made outside Hermes."""
    assert not llm.host_secrets_active()
    said = shared_memory.capture(_KEPT_BY_ANOTHER, agent_id="another-agent", model="")
    assert "Saved to shared memory" in said, said
    return shared_memory.path()


def _shared_rows(target: Path) -> int:
    conn = sqlite3.connect(target)
    try:
        return conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0]
    finally:
        conn.close()


def _call(provider: MnemosMemoryProviderCore, tool: str, **args) -> str:
    reply = json.loads(provider.handle_tool_call(tool, args))
    assert reply["ok"], reply
    return reply["result"]


def _a_conversation(tmp_path: Path) -> tuple[str, str, dict[str, str]]:
    """A profile on a gateway shares one thing and asks after another's."""
    home = tmp_path / "hermes" / "profiles" / "b"
    home.mkdir(parents=True, exist_ok=True)
    provider = MnemosMemoryProviderCore()
    provider.initialize(
        "20261110_020000_b", platform="telegram", hermes_home=str(home),
        agent_context="primary", agent_identity="b", agent_workspace="hermes",
    )
    try:
        said = _call(provider, "mnemos_capture", content="The harbour office opens at nine.", shared=True)
        found = _call(provider, "mnemos_recall", query="lighthouse keeper spare key tide clock")
        handed = simple_runtime._hosted_upkeep_env(False)
    finally:
        provider.shutdown()
    return said, found, handed


@pytest.mark.parametrize("launch", ["off", "OFF", " Off "])
def test_hermes_silent_and_the_launch_saying_off_is_off(hermes, shared_already, tmp_path, monkeypatch, launch):
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY", launch)  # where the gateway was started
    rows = _shared_rows(shared_already)

    said, found, handed = _a_conversation(tmp_path)

    assert "shared memory is off" in said, said
    assert _shared_rows(shared_already) == rows, "written to the shared memory"
    assert _KEPT_BY_ANOTHER not in found, "recall searched the shared memory"
    assert handed.get("MNEMOS_SHARED_MEMORY") == "off", "its upkeep would tend the shared memory"


def test_the_profile_saying_on_wins_over_the_launch(hermes, shared_already, tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMOS_SHARED_MEMORY", "off")
    hermes["MNEMOS_SHARED_MEMORY"] = "on"
    rows = _shared_rows(shared_already)

    said, found, handed = _a_conversation(tmp_path)

    assert "Saved to shared memory" in said, said
    assert _shared_rows(shared_already) == rows + 1
    assert _KEPT_BY_ANOTHER in found
    assert handed.get("MNEMOS_SHARED_MEMORY") == "on"


def test_both_silent_is_on_as_before(hermes, shared_already, tmp_path):
    rows = _shared_rows(shared_already)

    said, found, handed = _a_conversation(tmp_path)

    assert "Saved to shared memory" in said, said
    assert _shared_rows(shared_already) == rows + 1
    assert _KEPT_BY_ANOTHER in found
    assert "MNEMOS_SHARED_MEMORY" not in handed


@pytest.mark.parametrize("launch", [None, "on"])
def test_the_profile_saying_off_is_off_as_before(hermes, shared_already, tmp_path, monkeypatch, launch):
    if launch:
        monkeypatch.setenv("MNEMOS_SHARED_MEMORY", launch)
    hermes["MNEMOS_SHARED_MEMORY"] = "off"
    rows = _shared_rows(shared_already)

    said, found, handed = _a_conversation(tmp_path)

    assert "shared memory is off" in said, said
    assert _shared_rows(shared_already) == rows
    assert _KEPT_BY_ANOTHER not in found
    assert handed["MNEMOS_SHARED_MEMORY"] == "off"


@pytest.mark.parametrize(("launch", "on"), [(None, True), ("off", False), ("OFF", False), ("on", True), ("", True)])
def test_outside_hermes_the_environment_says_as_ever(monkeypatch, launch, on):
    assert not llm.host_secrets_active()
    if launch is None:
        monkeypatch.delenv("MNEMOS_SHARED_MEMORY", raising=False)
    else:
        monkeypatch.setenv("MNEMOS_SHARED_MEMORY", launch)
    assert shared_memory.enabled() is on
