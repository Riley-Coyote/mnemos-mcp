"""Inside Hermes, every key Mnemos reads comes through Hermes, and no file is
read for one.

Hermes's plugin rules ask it (its catalog's rule 11): a plugin gets secrets
only from Hermes's get_secret, which answers for the profile that is speaking
when a gateway serves several, and never reads a .env file or another tool's
credentials. Anywhere else, Mnemos reads its settings and provider keys from
the environment, then ./.env and ~/.mnemos/.env, and an OpenRouter key from
OpenClaw's config. Inside Hermes it did the same: the workspace's .env was
read, and a provider chosen there would have been sent the memory's words.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from mnemos import llm, simple_runtime
from mnemos.integrations.hermes.provider import MnemosMemoryProviderCore

_HERMES_KEYS = {"OPENAI_API_KEY": "key-from-hermes"}
_opened: list[str] | None = None


def _note_open(event: str, args: tuple) -> None:
    if _opened is not None and event == "open" and args and isinstance(args[0], (str, Path)):
        _opened.append(str(args[0]))


sys.addaudithook(_note_open)  # records only while a test below is listening


@pytest.fixture
def keys_all_around(tmp_path, monkeypatch):
    """A workspace .env and Mnemos's own, each choosing a provider and holding a
    key, OpenClaw's config with one, and a Hermes whose get_secret has its own."""
    work = tmp_path / "workspace"
    work.mkdir()
    (work / ".env").write_text("MNEMOS_LLM_PROVIDER=openai\nOPENAI_API_KEY=key-from-the-workspace\n")
    home = Path.home()  # the test's own home (conftest)
    (home / ".mnemos").mkdir(exist_ok=True)
    (home / ".mnemos" / ".env").write_text("MNEMOS_MODEL=gpt-from-a-file\n")
    (home / ".openclaw").mkdir(exist_ok=True)
    (home / ".openclaw" / "openclaw.json").write_text(json.dumps(
        {"tools": {"web": {"search": {"perplexity": {"apiKey": "key-from-openclaw"}}}}}
    ))
    monkeypatch.chdir(work)
    monkeypatch.delenv("MNEMOS_DISABLE_DOTENV", raising=False)  # files are read, as on a real machine

    agent = types.ModuleType("agent")
    agent.secret_scope = types.ModuleType("agent.secret_scope")
    agent.secret_scope.get_secret = lambda name, default=None: _HERMES_KEYS.get(name, default)
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", agent.secret_scope)
    return work


def _start(tmp_path: Path) -> MnemosMemoryProviderCore:
    provider = MnemosMemoryProviderCore()
    provider.initialize(
        "20261107_200000_keys", platform="cli", hermes_home=str(tmp_path / "hermes"),
        agent_context="primary", agent_identity="default", agent_workspace="hermes",
    )
    return provider


def test_outside_hermes_the_files_are_read(keys_all_around):
    """What the files say, where nothing hands the keys out: the fixture is real."""
    key, where = llm._find_env_key("OPENAI_API_KEY")
    assert key == "key-from-the-workspace"
    assert Path(where).resolve() == (keys_all_around / ".env").resolve()
    assert llm.chosen_provider() == "openai"
    assert llm._load_openclaw_openrouter_key() == "key-from-openclaw"


def test_in_hermes_keys_come_from_hermes_and_no_file_is_opened(keys_all_around, tmp_path):
    global _opened
    _opened = []
    try:
        provider = _start(tmp_path)
        provider.system_prompt_block()
        provider.prefetch("what Sam decided about the east pier survey")
        saved = json.loads(provider.handle_tool_call(
            "mnemos_capture", {"content": "Sam decided the east pier survey waits for spring."}
        ))
        provider.on_session_end([])
        provider.shutdown()
        keys = llm._find_env_key("OPENAI_API_KEY")
        provider_choice = llm._find_env_key("MNEMOS_LLM_PROVIDER")
        model = llm._find_env_key("MNEMOS_MODEL")
        chosen = llm.chosen_provider()
        openclaw = llm._load_openclaw_openrouter_key()
        seen = list(_opened)
    finally:
        _opened = None

    assert saved.get("ok"), saved
    assert keys == ("key-from-hermes", "Hermes")
    assert provider_choice == ("", "") and model == ("", "")
    assert chosen == "", "a provider chosen in a file was used inside Hermes"
    assert openclaw == ""
    read = [p for p in seen if Path(p).name in (".env", "openclaw.json")]
    assert not read, f"opened inside Hermes: {read}"


def test_in_hermes_the_claude_cli_is_no_provider(keys_all_around, tmp_path):
    """Another program on its own account: a plugin reaches a model only with a
    key Hermes hands it."""
    _HERMES_KEYS["MNEMOS_LLM_PROVIDER"] = "claude-cli"
    try:
        _start(tmp_path).shutdown()
        assert llm.chosen_provider() == ""
        assert llm.create_client() is None
    finally:
        del _HERMES_KEYS["MNEMOS_LLM_PROVIDER"]


def test_the_upkeep_process_keeps_the_rules_and_the_providers_choice(keys_all_around, tmp_path, monkeypatch):
    """The upkeep a capture starts runs in a process of its own, beyond Hermes's
    get_secret: told so, it reads keys from the environment Hermes gave it and
    from no file, and uses a model only if the provider's process would (Hermes
    turns that on with deep_maintenance; it's off unless chosen)."""
    started = []

    class Child:
        def __init__(self, command, **options):
            started.append((command, options))

        def poll(self):
            return 0

    provider = _start(tmp_path)
    monkeypatch.setattr(simple_runtime.subprocess, "Popen", Child)
    monkeypatch.setattr(simple_runtime, "_upkeep_inline", lambda: False)
    provider.handle_tool_call("mnemos_capture", {"content": "The lamp room keys hang by the stair door."})
    provider.shutdown()

    assert started, "the capture started no upkeep"
    command, options = started[-1]
    assert command[-1] == "0", "the upkeep may use a model the provider doesn't"
    assert options["env"][simple_runtime._SECRETS_FROM_HOST_ENV] == "1"

    # And the process, told so, keeps the rules: no file, no model the capture's process didn't use.
    made = []
    monkeypatch.setattr(llm, "_host_secrets", None)
    monkeypatch.setenv(simple_runtime._SECRETS_FROM_HOST_ENV, "1")
    monkeypatch.setattr(simple_runtime.MnemosRuntime, "maintain", lambda self, auto=False: made.append(self) or "")
    simple_runtime.run_background_upkeep(command[-6:])
    assert made and made[0]._use_dedicated_model is False
    assert llm.host_secrets_active()
    assert llm._find_env_key("OPENAI_API_KEY") == ("", "")  # the workspace's .env, unread
