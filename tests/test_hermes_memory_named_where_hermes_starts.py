"""A memory named only where Hermes starts is no longer passed over in silence.

Release 0.6.6 read ``MNEMOS_DB_PATH``, ``MNEMOS_AGENT_ID``,
``MNEMOS_PERSON_ID`` and ``MNEMOS_PROJECT_SCOPE`` straight from the environment
Hermes was started in. Now every setting of Mnemos's is asked of Hermes, for
the profile that is speaking. In a plain run of one profile Hermes falls back
to its own environment, so nothing changes there. On a gateway that serves
profiles it answers from the profile's own ``.env`` only: someone who had named
their memory in the shell or service that starts Hermes found, after the
upgrade, a profile with a new memory of its own, and nothing said why.

Mnemos still doesn't take those names from there (one profile's would name
another's memory). It says so, once for each home: which names it passed over,
never their values, where this profile's memory is now, and where to read the
steps that bring the first memory back. The last test follows those steps.
"""

from __future__ import annotations

import json
import logging
import sys
import types
from pathlib import Path

import pytest

from mnemos.integrations.hermes import provider as provider_module
from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore
from mnemos.integrations.hermes.scope import profile_store

_README = Path(__file__).resolve().parents[1] / "hermes-plugin" / "README.md"
_KEPT = "The east pier survey waits for spring, Sam decided."
_NAMES = ("MNEMOS_DB_PATH", "MNEMOS_AGENT_ID", "MNEMOS_PERSON_ID", "MNEMOS_PROJECT_SCOPE")


def _profile_env(home: Path) -> dict[str, str]:
    path = home / ".env"
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {name.strip(): value.strip() for name, value in pairs}


@pytest.fixture
def hermes(monkeypatch):
    """Hermes's ``get_secret`` for one home, as a plain run of one profile has it
    (the profile's ``.env``, then the process's own environment) or as a
    gateway serving profiles has it (the profile's ``.env`` and nothing else)."""
    agent = types.ModuleType("agent")
    agent.secret_scope = types.ModuleType("agent.secret_scope")
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", agent.secret_scope)
    monkeypatch.setattr(provider_module, "_told_of_names_passed_over", set(), raising=False)

    def runs(home: Path, *, gateway: bool) -> None:
        import os

        def get_secret(name, default=None):
            own = _profile_env(home).get(name)
            if own is not None:
                return own
            return default if gateway else os.environ.get(name, default)

        agent.secret_scope.get_secret = get_secret

    return runs


def _home() -> Path:
    home = Path.home() / ".hermes" / "profiles" / "b"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _start(home: Path, session: str = "20261110_030000_b") -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize(session, platform="cli", hermes_home=str(home), agent_context="primary")
    return provider


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and "Upgrading from 0.6.6" in r.getMessage()]


def _where_hermes_starts(monkeypatch, tmp_path: Path) -> dict[str, str]:
    named = {
        "MNEMOS_DB_PATH": str(tmp_path / "kept" / "ada.db"),
        "MNEMOS_AGENT_ID": "ada-the-agent",
        "MNEMOS_PERSON_ID": "sam-the-person",
        "MNEMOS_PROJECT_SCOPE": "harbour-works",
    }
    for name, value in named.items():
        monkeypatch.setenv(name, value)
    return named


def test_on_a_gateway_the_names_passed_over_are_said_once(hermes, tmp_path, monkeypatch, caplog):
    named = _where_hermes_starts(monkeypatch, tmp_path)
    home = _home()
    hermes(home, gateway=True)
    caplog.set_level(logging.WARNING)

    for session in ("20261110_030000_b", "20261110_030500_b"):
        provider = _start(home, session)
        own = provider.scope.db_path
        provider.shutdown()

    assert own == profile_store(home), "which memory is opened changed"
    said = _warnings(caplog)
    assert len(said) == 1, said
    for name in _NAMES:
        assert name in said[0]
    assert not any(value in said[0] for value in named.values()), "a value was said: it may be another profile's"
    assert own in said[0]
    assert said[0].index("MNEMOS_DB_PATH") < said[0].index(own) < said[0].index("Upgrading from 0.6.6")


@pytest.mark.parametrize("case", ["one profile's run", "hermes gives them", "nothing set", "an older hermes"])
def test_nothing_is_said_where_nothing_is_passed_over(hermes, tmp_path, monkeypatch, caplog, case):
    home = _home()
    named = _where_hermes_starts(monkeypatch, tmp_path) if case != "nothing set" else {}
    if case == "hermes gives them":
        (home / ".env").write_text("".join(f"{name}={value}\n" for name, value in named.items()))
    if case == "an older hermes":  # no secret scopes: the process's own environment is the profile's
        monkeypatch.delitem(sys.modules, "agent.secret_scope")
        monkeypatch.delitem(sys.modules, "agent")
    else:
        hermes(home, gateway=case != "one profile's run")
    caplog.set_level(logging.WARNING)

    provider = _start(home)
    provider.shutdown()

    assert not _warnings(caplog)


def test_outside_hermes_nothing_is_said(tmp_path, monkeypatch, caplog):
    from mnemos import llm

    _where_hermes_starts(monkeypatch, tmp_path)
    monkeypatch.setattr(provider_module, "_told_of_names_passed_over", set(), raising=False)
    caplog.set_level(logging.WARNING)
    assert not llm.host_secrets_active()
    provider_module._say_names_passed_over(_home(), str(tmp_path / "x.db"))
    assert not _warnings(caplog)


def test_the_readmes_steps_bring_back_the_memory_0_6_6_was_using(hermes, tmp_path, monkeypatch, caplog):
    named = _where_hermes_starts(monkeypatch, tmp_path)
    home = _home()

    # Before: one profile's run, its memory named where Hermes starts.
    hermes(home, gateway=False)
    first = _start(home)
    before = first.scope
    reply = json.loads(first.handle_tool_call("mnemos_capture", {"content": _KEPT}))
    first.shutdown()
    assert reply["ok"], reply
    assert (before.db_path, before.agent_id, before.person_id, before.project_scope) == tuple(named.values())

    # Upgraded and under a gateway: the profile's own memory, and the warning.
    hermes(home, gateway=True)
    caplog.set_level(logging.WARNING)
    second = _start(home, "20261110_040000_b")
    apart = second.scope
    woke_apart = second.system_prompt_block()
    second.shutdown()
    assert apart.db_path == profile_store(home) and _warnings(caplog)
    assert _KEPT not in woke_apart
    assert Path(named["MNEMOS_DB_PATH"]).exists(), "the earlier memory was moved"

    # The README's steps: the same lines in the profile's .env, and the four
    # settings the first session filled in taken out of mnemos.json.
    section = _README.read_text().split("## Upgrading from 0.6.6", 1)[1].split("\n## ", 1)[0]
    for key in ("db_path", "agent_id", "person_id", "project_scope", ".env", "mnemos.json"):
        assert f"`{key}`" in section, key
    (home / ".env").write_text("".join(f"{name}={value}\n" for name, value in named.items()))
    settings = json.loads((home / "mnemos.json").read_text())
    for key in ("db_path", "agent_id", "person_id", "project_scope"):
        settings.pop(key, None)
    (home / "mnemos.json").write_text(json.dumps(settings))
    caplog.clear()

    again = _start(home, "20261110_050000_b")
    back = again.scope
    woke = again.system_prompt_block()
    found = json.loads(again.handle_tool_call("mnemos_recall", {"query": "east pier survey"}))["result"]
    again.shutdown()
    assert (back.db_path, back.agent_id, back.person_id, back.project_scope) == tuple(named.values())
    assert _KEPT in woke and _KEPT in found
    assert not _warnings(caplog)
