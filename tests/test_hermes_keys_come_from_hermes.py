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


# What Hermes's own process holds: every provider's key, set for the profile the
# gateway was started for, and that profile's choices for Mnemos.
_GATEWAY_ENV = {
    "OPENAI_API_KEY": "the-gateway's-openai-key",
    "OPENROUTER_API_KEY": "the-gateway's-openrouter-key",
    "ANTHROPIC_API_KEY": "the-gateway's-anthropic-key",
    "GEMINI_API_KEY": "the-gateway's-gemini-key",
    "TELEGRAM_BOT_TOKEN": "a-bot-token",
    "AWS_SECRET_ACCESS_KEY": "an-aws-secret",
    "API_SERVER_KEY": "the-api-server's-key",
    "MNEMOS_LLM_PROVIDER": "openrouter",
    "MNEMOS_MODEL": "the-gateway's-model",
    "MNEMOS_EMBEDDING_PROVIDER": "gemini",
    "MNEMOS_JEV_KEY_FILE": "/somewhere/a-key",
    "MNEMOS_SHARED_MEMORY": "off",
    "MNEMOS_CONSOLIDATION_DECAY_RATE": "0.05",
    # Under Mnemos's name, or the locale's, and neither: nothing Mnemos reads.
    "MNEMOS_PAT": "a-secret-under-mnemos-name",
    "MNEMOS_AGENT_ID": "the-gateway's-agent",
    "LC_GITHUB_PAT": "a-secret-carried-through-ssh",
    "HTTPS_PROXY": "http://someone:a-password@proxy.example:3128",
    "LC_ALL": "en_US.UTF-8",
}
# What of that the upkeep process is given whatever the profile chose: the
# locale. Nothing of Mnemos's own: whether the shared memory is on and its
# numbers are the speaking profile's too, and asked of Hermes like the rest
# (tests/test_hermes_settings_come_from_hermes.py).
_GIVEN_ANYWAY = {"LC_ALL"}


def _hermes_says(monkeypatch, **profile):
    """Hermes, speaking for a profile that has set just this, on a gateway
    serving several: what the profile hasn't set is nothing, never the
    gateway's own (``agent.secret_scope.get_secret``, multiplexing)."""
    for name, value in _GATEWAY_ENV.items():
        monkeypatch.setenv(name, value)
    llm.take_secrets_from(lambda name, default=None: profile.get(name, default))


def test_the_upkeep_process_is_given_none_of_hermes_own_keys(keys_all_around, tmp_path, monkeypatch):
    """The upkeep a capture starts was handed Hermes's whole environment: every
    provider's key, the bot tokens, all of it, for a process that uses no key at
    all unless a provider was chosen for Mnemos (Nous's review of the catalog
    entry, 2026-11-09). It gets what a process needs to run, by name, and
    Mnemos's own settings as the profile that is speaking has them."""
    started = []

    class Child:
        def __init__(self, command, **options):
            started.append((command, options))

        def poll(self):
            return 0

    for name, value in _GATEWAY_ENV.items():
        monkeypatch.setenv(name, value)
    # What this profile set for Mnemos itself, as Hermes hands it out.
    monkeypatch.setitem(_HERMES_KEYS, "MNEMOS_SHARED_MEMORY", "OFF")
    monkeypatch.setitem(_HERMES_KEYS, "MNEMOS_CONSOLIDATION_DECAY_RATE", "0.07")
    provider = _start(tmp_path)
    monkeypatch.setattr(simple_runtime.subprocess, "Popen", Child)
    monkeypatch.setattr(simple_runtime, "_upkeep_inline", lambda: False)
    provider.handle_tool_call("mnemos_capture", {"content": "The spare lamp oil is under the stair."})
    provider.shutdown()

    assert started, "the capture started no upkeep"
    env = started[-1][1]["env"]
    held = (set(_GATEWAY_ENV.values()) - {_GATEWAY_ENV[name] for name in _GIVEN_ANYWAY}) | {"key-from-hermes"}
    assert not held & set(env.values()), sorted(env)
    assert {"PATH", "HOME"} <= set(env) and env["LC_ALL"] == "en_US.UTF-8"
    assert env["MNEMOS_SHARED_MEMORY"] == "OFF", "the profile's own setting for Mnemos didn't reach its upkeep"
    assert env["MNEMOS_CONSOLIDATION_DECAY_RATE"] == "0.07", "upkeep ran on other numbers than the call that asked"
    assert env[simple_runtime._SECRETS_FROM_HOST_ENV] == "1"
    # And nothing in it that isn't named, one by one: a name added to Hermes's
    # environment tomorrow doesn't go either, whatever it starts with.
    named = (simple_runtime._PLAIN_ENV | simple_runtime._tuning_env_names() | simple_runtime._SHARED_MEMORY_ENV
             | {simple_runtime._SECRETS_FROM_HOST_ENV})
    assert not {name.upper() for name in env} - named, sorted(env)
    assert not any(word in name for name in env for word in ("KEY", "TOKEN", "PASSWORD")), sorted(env)


def test_the_upkeep_process_is_given_the_one_key_the_profile_chose(monkeypatch):
    """With a provider chosen for Mnemos and upkeep allowed a model, the process
    gets that provider's key and no other, as the profile that is speaking has
    them, and it is the one a client is then made with."""
    _hermes_says(
        monkeypatch, MNEMOS_LLM_PROVIDER="openai", MNEMOS_MODEL="the-profile's-model",
        OPENAI_API_KEY="the-profile's-openai-key", ANTHROPIC_API_KEY="the-profile's-anthropic-key",
    )
    env = simple_runtime._hosted_upkeep_env(True)
    assert env["MNEMOS_LLM_PROVIDER"] == "openai" and env["MNEMOS_MODEL"] == "the-profile's-model"
    assert env["OPENAI_API_KEY"] == "the-profile's-openai-key"
    assert not {"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"} & set(env)
    assert env["HTTPS_PROXY"] == _GATEWAY_ENV["HTTPS_PROXY"], "a chosen provider behind a proxy can't be reached"

    # The process itself, reading what it was given and nothing else.
    llm.take_secrets_from(env.get)
    client = llm.create_client()
    assert (client._api_key, client._model) == ("the-profile's-openai-key", "the-profile's-model")

    # Upkeep that isn't allowed a model is given no provider's key at all.
    _hermes_says(monkeypatch, MNEMOS_LLM_PROVIDER="openai", OPENAI_API_KEY="the-profile's-openai-key")
    quiet = simple_runtime._hosted_upkeep_env(False)
    assert not {"OPENAI_API_KEY", "MNEMOS_LLM_PROVIDER", "MNEMOS_MODEL", "HTTPS_PROXY"} & set(quiet)


@pytest.mark.parametrize("provider", sorted(llm.PROVIDER_KEYS))
def test_each_providers_key_is_the_one_its_client_reads(monkeypatch, provider):
    """The key named for a provider is the one its client is made with: the
    upkeep process is handed exactly it."""
    if provider == "anthropic":
        pytest.importorskip("anthropic")
    key_name = llm.PROVIDER_KEYS[provider]
    _hermes_says(monkeypatch, MNEMOS_LLM_PROVIDER=provider, **{key_name: f"the-profile's-{provider}-key"})
    env = simple_runtime._hosted_upkeep_env(True)
    assert [name for name in env if name.endswith("_API_KEY")] == [key_name]
    llm.take_secrets_from(env.get)
    assert llm.create_client()._api_key == f"the-profile's-{provider}-key"


def test_a_profile_never_runs_on_the_gateways_choice(monkeypatch):
    """One gateway can serve several profiles, and its environment is the one it
    was started for. A profile that chose nothing for Mnemos took that one's
    provider (the environment overrides the config file) and, in the upkeep
    process, its keys."""
    _hermes_says(monkeypatch)  # this profile has set nothing
    assert llm.chosen_provider() == "", "the gateway's own choice of provider was this profile's"
    env = simple_runtime._hosted_upkeep_env(True)
    assert set(_GATEWAY_ENV) & set(env) == _GIVEN_ANYWAY, sorted(env)

    # And one that chose its own gets its own.
    _hermes_says(monkeypatch, MNEMOS_LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="the-profile's-anthropic-key")
    env = simple_runtime._hosted_upkeep_env(True)
    assert env["MNEMOS_LLM_PROVIDER"] == "anthropic"
    assert env["ANTHROPIC_API_KEY"] == "the-profile's-anthropic-key"
    assert "OPENROUTER_API_KEY" not in env and "MNEMOS_MODEL" not in env


def test_geminis_key_goes_only_when_meaning_search_is_set_to_it(monkeypatch):
    """A Gemini key the profile holds for something else goes nowhere."""
    _hermes_says(monkeypatch, GEMINI_API_KEY="the-profile's-gemini-key")
    env = simple_runtime._hosted_upkeep_env(False)
    assert "GEMINI_API_KEY" not in env and "MNEMOS_EMBEDDING_PROVIDER" not in env and "HTTPS_PROXY" not in env

    _hermes_says(monkeypatch, MNEMOS_EMBEDDING_PROVIDER="gemini", GEMINI_API_KEY="the-profile's-gemini-key")
    env = simple_runtime._hosted_upkeep_env(False)
    assert (env["MNEMOS_EMBEDDING_PROVIDER"], env["GEMINI_API_KEY"]) == ("gemini", "the-profile's-gemini-key")
    assert "HTTPS_PROXY" in env


def test_a_profile_never_searches_by_meaning_on_the_gateways_choice(monkeypatch):
    """The same for meaning search. MNEMOS_EMBEDDINGS_PROVIDER in the gateway's
    environment reads as ``embeddings.provider`` in Mnemos's config, for every
    profile the gateway serves: one that chose nothing, holding a Gemini key
    for something else, had its memory's words sent to Google."""
    from mnemos.store.embedding_index import embedding_choice

    monkeypatch.setenv("MNEMOS_EMBEDDINGS_PROVIDER", "gemini")
    monkeypatch.setenv("MNEMOS_EMBEDDING_MODEL", "the-gateway's-embedding-model")
    _hermes_says(monkeypatch, GEMINI_API_KEY="the-profile's-gemini-key")
    assert embedding_choice()["provider"] == "local", "the gateway's own choice of provider was this profile's"
    env = simple_runtime._hosted_upkeep_env(False)
    assert "GEMINI_API_KEY" not in env and "MNEMOS_EMBEDDING_PROVIDER" not in env

    # One that chose Gemini itself gets it, with the model it named and not the gateway's.
    _hermes_says(monkeypatch, MNEMOS_EMBEDDING_PROVIDER="gemini", GEMINI_API_KEY="the-profile's-gemini-key",
                 MNEMOS_EMBEDDING_MODEL="the-profile's-embedding-model")
    assert embedding_choice()["model"] == "the-profile's-embedding-model"
    env = simple_runtime._hosted_upkeep_env(False)
    assert env["MNEMOS_EMBEDDING_MODEL"] == "the-profile's-embedding-model"
    llm.take_secrets_from(env.get)  # the process itself, reading what it was given
    assert embedding_choice()["model"] == "the-profile's-embedding-model"
    _hermes_says(monkeypatch, MNEMOS_EMBEDDING_PROVIDER="gemini", GEMINI_API_KEY="the-profile's-gemini-key")
    assert embedding_choice()["model"] != "the-gateway's-embedding-model"


def test_upkeep_that_cant_be_handed_its_settings_runs_here_instead(tmp_path, monkeypatch):
    """What the process is handed is read through Hermes, and Hermes can refuse
    (a read outside any profile, on a gateway serving several). The refusal
    came up through the capture with this memory's claim still held, so nothing
    tended it until the claim went stale. It is a process that didn't start:
    the claim is given up, and the upkeep runs in the call that asked."""
    started = []
    provider = _start(tmp_path)
    monkeypatch.setattr(simple_runtime.subprocess, "Popen", lambda *a, **k: started.append(a))
    monkeypatch.setattr(simple_runtime, "_upkeep_inline", lambda: False)

    def refuses(dedicated_model):
        raise RuntimeError("no profile is speaking")

    monkeypatch.setattr(simple_runtime, "_hosted_upkeep_env", refuses)
    scope = provider._runtime.scope
    assert simple_runtime._spawn_upkeep(scope, "a-token") is False and not started

    said = json.loads(provider.handle_tool_call("mnemos_capture", {"content": "The well rope was replaced in May."}))
    assert said["ok"] is True
    runtime = provider._runtime
    assert not runtime._store.get_meta(runtime._meta_key(simple_runtime._UPKEEP_CLAIM)), "the claim was left held"
    provider.shutdown()



def test_a_profiles_memory_is_never_the_one_the_gateway_names(keys_all_around, tmp_path, monkeypatch):
    """MNEMOS_DB_PATH and MNEMOS_AGENT_ID in a gateway's environment are the
    launch profile's. Read straight from it, they were the memory of every
    profile the gateway serves that had named none: all of them in one file,
    as one agent. They are asked of Hermes, as the keys are."""
    monkeypatch.setenv("MNEMOS_DB_PATH", str(tmp_path / "the-gateways.db"))
    monkeypatch.setenv("MNEMOS_AGENT_ID", "the-gateways-agent")
    monkeypatch.setenv("MNEMOS_PERSON_ID", "the-gateways-person")
    monkeypatch.setenv("MNEMOS_PROJECT_SCOPE", "the-gateways-project")

    provider = _start(tmp_path)  # Hermes holds none of these for the profile speaking
    scope = provider._runtime.scope
    provider.shutdown()
    assert "gateways" not in " ".join((scope.db_path, scope.agent_id, scope.person_id, scope.project_scope)), scope
    assert not (tmp_path / "the-gateways.db").exists()
    kept = json.loads((tmp_path / "hermes" / "mnemos.json").read_text())
    assert "gateways" not in json.dumps(kept), "the gateway's names were written down as this profile's"

    # A profile that names its own memory, in what Hermes holds for it, has that one.
    monkeypatch.setitem(_HERMES_KEYS, "MNEMOS_DB_PATH", str(tmp_path / "named" / "mine.db"))
    monkeypatch.setitem(_HERMES_KEYS, "MNEMOS_AGENT_ID", "named-by-the-profile")
    provider = MnemosMemoryProviderCore()
    provider.initialize(
        "20261107_200500_keys", platform="cli", hermes_home=str(tmp_path / "another"),
        agent_context="primary", agent_identity="default", agent_workspace="hermes",
    )
    scope = provider._runtime.scope
    provider.shutdown()
    assert (scope.db_path, scope.agent_id) == (str(tmp_path / "named" / "mine.db"), "named-by-the-profile")


def test_the_person_a_profile_is_with_is_never_the_gateways(keys_all_around, tmp_path, monkeypatch):
    """MNEMOS_PERSON_NAME, the same way: every profile a gateway serves woke
    "with" the person the gateway was started for."""
    monkeypatch.setenv("MNEMOS_PERSON_NAME", "Gatewayperson")
    provider = _start(tmp_path)
    provider.handle_tool_call("mnemos_handoff", {"text": "Left the ledger at March."})
    woke = provider.system_prompt_block()
    provider.shutdown()
    assert "## waking up" in woke and "Gatewayperson" not in woke

    monkeypatch.setitem(_HERMES_KEYS, "MNEMOS_PERSON_NAME", "Mara")
    provider = _start(tmp_path)
    woke = provider.system_prompt_block()
    provider.shutdown()
    assert "with Mara" in woke


def test_the_upkeep_process_keeps_what_the_machine_needs_to_run_it(monkeypatch):
    """Where the machine's certificates are, where a local model is cached, and
    what a local model needs to load, none of it a key: without them upkeep
    inside Hermes failed where the same upkeep outside it worked (a NixOS
    machine's certificates, an older name for Hugging Face's cache, the switch
    macOS needs when two copies of OpenMP load)."""
    needed = {
        "NIX_SSL_CERT_FILE": "/etc/ssl/certs/ca-bundle.crt", "REQUESTS_CA_BUNDLE": "/etc/ssl/corp.pem",
        "HUGGINGFACE_HUB_CACHE": "/cache/hf", "PYTHONUTF8": "1",
        "OMP_NUM_THREADS": "2", "KMP_DUPLICATE_LIB_OK": "TRUE",
    }
    _hermes_says(monkeypatch)
    for name, value in needed.items():
        monkeypatch.setenv(name, value)

    env = simple_runtime._hosted_upkeep_env(False)

    assert {name: env.get(name) for name in needed} == needed


def test_outside_hermes_the_embedding_model_is_the_environments_as_ever(tmp_path, monkeypatch):
    """Outside Hermes nothing changed: the Gemini model's name is read from the
    environment and from no file. Read as the provider's choice is (0.6.7,
    for a profile inside Hermes), a name in a .env began to count on machines
    where it never had, for an index built with another model."""
    from mnemos.store.embedding_index import GEMINI_MODEL, embedding_choice

    (Path.home() / ".mnemos").mkdir(exist_ok=True)
    (Path.home() / ".mnemos" / ".env").write_text(
        "MNEMOS_EMBEDDING_PROVIDER=gemini\nGEMINI_API_KEY=a-key-in-a-file\nMNEMOS_EMBEDDING_MODEL=a-model-in-a-file\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MNEMOS_DISABLE_DOTENV", raising=False)  # files are read, as on a real machine
    monkeypatch.delenv("MNEMOS_EMBEDDING_MODEL", raising=False)
    llm.take_secrets_from(None)

    assert embedding_choice()["provider"] == "gemini", "the fixture is real: the file's choice and key are read"
    assert embedding_choice()["model"] == GEMINI_MODEL

    monkeypatch.setenv("MNEMOS_EMBEDDING_MODEL", "a-model-in-the-environment")
    assert embedding_choice()["model"] == "a-model-in-the-environment"
