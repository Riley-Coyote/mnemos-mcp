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
import os
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
        {"tools": {"web": {"search": {"perplexity": {"apiKey": "sk-or-key-from-openclaw"}}}}}
    ))
    monkeypatch.chdir(work)
    monkeypatch.delenv("MNEMOS_DISABLE_DOTENV", raising=False)  # files are read, as on a real machine

    agent = types.ModuleType("agent")
    agent.secret_scope = types.ModuleType("agent.secret_scope")
    agent.secret_scope.get_secret = lambda name, default=None: _HERMES_KEYS.get(name, default)
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", agent.secret_scope)
    return work


def _keys_in(env: dict) -> list[str]:
    """The names in ``env`` that hold a key, a token or a secret."""
    return sorted(
        name for name in env
        if name != simple_runtime._SECRETS_FROM_HOST_ENV
        and any(word in name for word in ("KEY", "TOKEN", "SECRET"))
    )


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
    assert llm._load_openclaw_openrouter_key() == "sk-or-key-from-openclaw"


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

    # Keys Hermes's own process holds, which aren't this profile's to give.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-hermes-itself-uses")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-of-another-profile")
    provider = _start(tmp_path)
    monkeypatch.setattr(simple_runtime.subprocess, "Popen", Child)
    monkeypatch.setattr(simple_runtime, "_upkeep_inline", lambda: False)
    provider.handle_tool_call("mnemos_capture", {"content": "The lamp room keys hang by the stair door."})
    provider.shutdown()

    assert started, "the capture started no upkeep"
    command, options = started[-1]
    assert command[-1] == "0", "the upkeep may use a model the provider doesn't"
    assert options["env"][simple_runtime._SECRETS_FROM_HOST_ENV] == "1"
    handed = _keys_in(options["env"])
    assert handed == [], f"no provider is chosen, yet the upkeep was handed {handed}"

    # And the process, told so, keeps the rules: no file, no model the capture's process didn't use.
    made = []
    monkeypatch.setattr(llm, "_host_secrets", None)
    monkeypatch.setenv(simple_runtime._SECRETS_FROM_HOST_ENV, "1")
    monkeypatch.setattr(simple_runtime.MnemosRuntime, "maintain", lambda self, auto=False: made.append(self) or "")
    simple_runtime.run_background_upkeep(command[-6:])
    assert made and made[0]._use_dedicated_model is False
    assert llm.host_secrets_active()
    assert llm._find_env_key("OPENAI_API_KEY") == ("", "")  # the workspace's .env, unread


def test_the_upkeep_process_gets_the_profiles_settings_and_no_other_key(monkeypatch):
    """Hermes's review of 0.6.6: the upkeep process was handed Hermes's whole
    environment, every provider's key in it, and when one gateway serves
    several profiles, a second profile's upkeep ran on the choices of the one
    it started with. Now it gets what any process needs, Mnemos's own settings,
    and what this profile's get_secret answers: the chosen provider's key and
    no other, and Gemini's only when meaning search uses Gemini."""
    # The environment the gateway started with: the first profile's choices and every key.
    monkeypatch.setenv("MNEMOS_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("MNEMOS_MODEL", "the-first-profiles-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-of-the-first-profile")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-hermes-itself-uses")
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "token-of-another-tool")
    monkeypatch.setenv("MNEMOS_EMBEDDING_MODEL", "an-embedding-model")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    # What get_secret answers for the profile that is speaking.
    profile = {
        "MNEMOS_LLM_PROVIDER": "openai", "MNEMOS_MODEL": "gpt-of-this-profile",
        "OPENAI_API_KEY": "key-of-this-profile", "OPENROUTER_API_KEY": "its-openrouter-key",
        "MNEMOS_EMBEDDING_PROVIDER": "gemini", "GEMINI_API_KEY": "its-gemini-key",
    }
    monkeypatch.setattr(llm, "_host_secrets", profile.get)

    env = simple_runtime._upkeep_env()

    assert env["MNEMOS_LLM_PROVIDER"] == "openai" and env["MNEMOS_MODEL"] == "gpt-of-this-profile"
    assert env["OPENAI_API_KEY"] == "key-of-this-profile"
    assert env["MNEMOS_EMBEDDING_PROVIDER"] == "gemini" and env["GEMINI_API_KEY"] == "its-gemini-key"
    assert _keys_in(env) == ["GEMINI_API_KEY", "OPENAI_API_KEY"], _keys_in(env)
    assert env["MNEMOS_EMBEDDING_MODEL"] == "an-embedding-model"  # Mnemos's own, not a key
    assert env["PATH"] == os.environ["PATH"] and env["HOME"] == os.environ["HOME"]
    assert env["LC_ALL"] == "en_US.UTF-8"
    assert env[simple_runtime._SECRETS_FROM_HOST_ENV] == "1"

    # Local meaning search and no provider: no key at all.
    profile.clear()
    env = simple_runtime._upkeep_env()
    assert _keys_in(env) == []
    assert "MNEMOS_LLM_PROVIDER" not in env and "MNEMOS_MODEL" not in env


def test_hermes_memory_context_tags_strip_in_linear_time():
    """Hermes's review of 0.6.6: the strip pattern was quadratic on a message
    with many "<" (4.6 s at 51 KB). Hermes's own bounded shape is linear."""
    import time

    from mnemos.integrations.hermes.provider import _CONTEXT_TAG_RE

    hostile = "<" * 51_000 + " memory-context"
    started = time.perf_counter()
    _CONTEXT_TAG_RE.sub("", hostile)
    assert time.perf_counter() - started < 0.5
    said = "before <memory-context>\nwhat Mnemos recalled\n</memory-context> after"
    assert _CONTEXT_TAG_RE.sub("", said) == "before  after"
    assert _CONTEXT_TAG_RE.sub("", "a < memory-context >x< / MEMORY-CONTEXT > b") == "a  b"
