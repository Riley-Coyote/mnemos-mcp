"""
LLM client abstraction for Mnemos.

Provides a simple protocol that any LLM provider can implement.
A chosen provider classifies the links between memories and weighs how
surprising a new one is. It never writes in the agent's place: no
rewording, no lessons, no belief changes. Those are the agent's own.

Three implementations:
- AnthropicClient: Uses the Anthropic SDK (Claude models)
- OpenRouterClient: Uses OpenRouter API (any model)
- MockClient: Returns canned responses (for testing)

create_client() returns the client for the provider the person chose for
Mnemos (``chosen_provider``), or None. A key on its own chooses nothing.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Protocol, runtime_checkable

logger = logging.getLogger("mnemos.llm")


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM clients.

    complete(prompt) -> str: simple single-prompt call.
    structured_complete(system, user, temperature, max_tokens) -> str:
        system+user prompt with temperature control for classification tasks.
    """

    def complete(self, prompt: str) -> str: ...

    def structured_complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str: ...


class AnthropicClient:
    """LLM client using the Anthropic SDK (Claude).

    Requires: pip install anthropic
    Env var: ANTHROPIC_API_KEY
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 500,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(self, prompt: str) -> str:
        """Send a prompt to Claude and return the response text."""
        client = self._get_client()
        response = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def structured_complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        """Send a system+user prompt with temperature control.

        Used by the LLM classifier for deterministic, structured output.
        Supports JSON-heavy responses with higher token limits.
        """
        client = self._get_client()
        response = client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text


# What a one-shot `claude -p` needs from the caller's environment to find itself and
# sign in with the subscription. Everything else stays behind: a parent Claude Code
# session's CLAUDE_CODE_* variables and ANTHROPIC_BASE_URL, and ANTHROPIC_API_KEY,
# which would bill the metered API instead.
_CLI_ENV = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE",
    "CLAUDE_CONFIG_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
    "https_proxy", "http_proxy", "no_proxy", "NODE_EXTRA_CA_CERTS",
)


def _cli_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _CLI_ENV}


def _cli_workdir_root() -> str:
    """A temp root outside the home folder: from a folder under home, Claude Code's
    project discovery can walk up into the person's own ~/.claude."""
    import tempfile

    home = os.path.realpath(os.path.expanduser("~"))
    root = os.path.realpath(tempfile.gettempdir())
    if (root == home or root.startswith(home + os.sep)) and os.path.isdir("/tmp"):
        return "/tmp"
    return root


class ClaudeCLIClient:
    """LLM client that routes through the local ``claude`` CLI.

    Uses Claude Code subscription auth (no API key, no per-token API billing).
    Each call spawns a one-shot ``claude -p`` process, so it is slower than the
    API and meant for background work (consolidation / reflection), not hot
    paths. Select with ``MNEMOS_LLM_PROVIDER=claude-cli``.
    """

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        claude_bin: str | None = None,
        timeout: int = 120,
    ) -> None:
        import shutil

        self._model = model
        self._bin = (
            claude_bin
            or os.environ.get("CLAUDE_BIN")
            or shutil.which("claude")
            or os.path.expanduser("~/.local/bin/claude")
        )
        self._timeout = timeout

    def _run(self, prompt: str) -> str:
        import subprocess
        import tempfile

        # Memory is untrusted input. A captured prompt can contain instructions
        # aimed at Claude Code, so a maintenance process must never have
        # filesystem, shell, or network tools available. It also runs with none
        # of the person's own Claude Code setup: no user or project settings
        # (their hooks can add private context), no MCP servers, no saved
        # session, an empty folder outside their home, and only the environment
        # `claude` needs to sign in.
        try:
            with tempfile.TemporaryDirectory(prefix="mnemos-llm-", dir=_cli_workdir_root()) as cwd:
                result = subprocess.run(
                    [
                        self._bin,
                        "--model", self._model,
                        "--tools", "",
                        "--disable-slash-commands",
                        "--setting-sources", "project",
                        "--strict-mcp-config",
                        "--no-session-persistence",
                        "-p", prompt,
                    ],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    cwd=cwd,
                    env=_cli_env(),
                )
            return (result.stdout or "").strip()
        except Exception:
            return ""

    def complete(self, prompt: str) -> str:
        return self._run(prompt)

    def structured_complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        return self._run(f"{system}\n\n{user}")


class OpenRouterClient:
    """LLM client using the OpenRouter API (any model).

    Requires: pip install httpx
    Env var: OPENROUTER_API_KEY
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "anthropic/claude-sonnet-4-6",
        max_tokens: int = 500,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, prompt: str) -> str:
        """Send a prompt via OpenRouter and return the response text."""
        import json
        import urllib.request

        body = json.dumps({
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

    def structured_complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        """Send a system+user prompt with temperature control."""
        import json
        import urllib.request

        body = json.dumps({
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }).encode()

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]


class MockClient:
    """Mock LLM client for testing. Returns simple distilled responses."""

    def structured_complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        """Mock structured completion — returns empty JSON array."""
        return "[]"

    def complete(self, prompt: str) -> str:
        """Return a mock response based on the prompt type."""
        prompt_lower = prompt.lower()

        if "lasting insight" in prompt_lower or "one lasting" in prompt_lower:
            # Impact extraction
            return "A lesson learned through experience."

        if "soften" in prompt_lower or "lower resolution" in prompt_lower:
            # Softening
            return "A memory of something that mattered, details softened by time."

        if "emotional essence" in prompt_lower or "impression" in prompt_lower:
            # Deep softening
            return "The feeling of understanding arriving."

        if "thoughts" in prompt_lower or "patterns" in prompt_lower:
            # Thought generation
            return "Patterns emerge when you stop looking for them directly."

        if "self-narrative" in prompt_lower or "who you are" in prompt_lower:
            # Narrative (legacy — graph identity replaces this)
            return "An entity learning through traces of impact."

        if "stress-test" in prompt_lower or "counterargument" in prompt_lower:
            # Belief challenge
            return (
                "CHALLENGE: This assumption may not hold in all contexts.\n"
                "ASSESSMENT: MAINTAIN\n"
                "CONFIDENCE_DELTA: -0.02\n"
                "REASONING: The belief is generally sound but could use nuance."
            )

        return "A considered response."


# A host that hands out settings and keys itself, and whose rules say a plugin
# reads them from nowhere else: Hermes, whose get_secret answers for the profile
# that is speaking (a gateway can serve several). None everywhere else.
_host_secrets: Callable[[str], str | None] | None = None


def take_secrets_from(get_secret: Callable[[str], str | None] | None) -> None:
    """From now on, read every setting and key through ``get_secret`` and from
    no file: no .env, no other tool's config. The Hermes provider calls it with
    Hermes's own as it starts. ``None`` goes back to the environment and files."""
    global _host_secrets
    _host_secrets = get_secret


def host_secrets_active() -> bool:
    """Whether a host (Hermes) hands out the settings and keys."""
    return _host_secrets is not None


# The key each provider is reached with.
_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def host_settings_for_upkeep() -> dict[str, str]:
    """What the background upkeep process reads from the host, read here, in
    the scope of the profile that is speaking: Mnemos's provider and model, the
    key of the provider chosen and no other, meaning search's provider, and
    Gemini's key only when meaning search uses Gemini. Empty without a host.

    The process runs beyond the host's get_secret, so it is handed these and
    nothing else of the host's (Hermes's review of 0.6.6: it was handed the
    whole environment, every provider's key in it, and a gateway's second
    profile ran upkeep on the first profile's choices)."""
    if _host_secrets is None:
        return {}
    from .store.embedding_index import GEMINI, PROVIDER_SETTING, embedding_choice

    settings: dict[str, str] = {}
    for name in ("MNEMOS_LLM_PROVIDER", "MNEMOS_MODEL", PROVIDER_SETTING):
        value = _load_env_key(name)
        if value:
            settings[name] = value
    key_name = _PROVIDER_KEYS.get(chosen_provider())
    key = _load_env_key(key_name) if key_name else ""
    if key:
        settings[key_name] = key
    if embedding_choice()["provider"] == GEMINI:
        gemini = _load_env_key("GEMINI_API_KEY")
        if gemini:
            settings["GEMINI_API_KEY"] = gemini
    return settings


def _dotenv_disabled() -> bool:
    if _host_secrets is not None:
        return True
    return os.environ.get("MNEMOS_DISABLE_DOTENV", "").strip().lower() in (
        "1", "true", "yes",
    )


def _env_search_paths() -> list:
    """Filesystem locations to search for .env files.

    MNEMOS_ENV_PATHS (colon-separated paths) takes precedence; otherwise
    the working directory's .env (typically the agent workspace) and the
    shared ~/.mnemos/.env are checked.
    """
    from pathlib import Path

    raw = os.environ.get("MNEMOS_ENV_PATHS", "").strip()
    if raw:
        return [Path(p).expanduser() for p in raw.split(":") if p.strip()]
    return [
        Path.cwd() / ".env",
        Path.home() / ".mnemos" / ".env",
    ]


def _load_env_key(key_name: str) -> str:
    """Try to find an API key from env vars, then from .env files."""
    return _find_env_key(key_name)[0]


def _find_env_key(key_name: str) -> tuple[str, str]:
    """A setting's value, and where it was found: "the environment", or the
    path of the .env file it was read from, or "Hermes" when Hermes hands
    them out. ("", "") when it is nowhere Mnemos looks. `mnemos doctor` says
    where."""
    if _host_secrets is not None:
        try:
            val = str(_host_secrets(key_name) or "").strip()
        except Exception:  # Hermes refuses a read outside a profile's scope
            val = ""
        return (val, "Hermes") if val else ("", "")

    # 1. Environment variable
    val = os.environ.get(key_name, "").strip()
    if val:
        return val, "the environment"

    # 2. .env files, unless ambient config reads are disabled
    #    (test isolation, hermetic deployments)
    if _dotenv_disabled():
        return "", ""

    for env_path in _env_search_paths():
        if env_path.exists():
            try:
                for line in env_path.read_text().splitlines():
                    line = line.strip()
                    if line.startswith(f"{key_name}="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val, str(env_path)
            except OSError:
                continue

    return "", ""



def _load_openclaw_openrouter_key() -> str:
    """The OpenRouter key in OpenClaw's config, or "".

    ``tools.web.search.perplexity.apiKey`` is OpenClaw's Perplexity
    web-search slot, and OpenClaw takes either kind of key there: a ``pplx-``
    key goes to Perplexity's own API, and an ``sk-or-`` key, or one beside a
    ``baseUrl`` at openrouter.ai, goes through OpenRouter. Only the OpenRouter
    kind is Mnemos's to use; a Perplexity key sent to openrouter.ai would be a
    credential given to the wrong company.
    """
    from pathlib import Path
    import json
    if _dotenv_disabled():
        # Same ambient-machine-state class as .env files.
        return ""
    openclaw_config = Path.home() / ".openclaw" / "openclaw.json"
    if not openclaw_config.exists():
        return ""
    try:
        with open(openclaw_config) as f:
            cfg = json.load(f)
        perplexity = cfg["tools"]["web"]["search"]["perplexity"]
        key = perplexity.get("apiKey", "")
        base_url = perplexity.get("baseUrl", "")
    except (json.JSONDecodeError, OSError, KeyError, TypeError, AttributeError):
        return ""
    # OpenClaw also takes a SecretRef object there, which isn't a key.
    key = key.strip() if isinstance(key, str) else ""
    if not key:
        return ""
    if key.startswith("sk-or-") or (isinstance(base_url, str) and "openrouter.ai" in base_url):
        return key
    _warn_once(
        "OpenClaw's tools.web.search.perplexity.apiKey is not an OpenRouter key, "
        "so Mnemos doesn't use it for openrouter; set OPENROUTER_API_KEY for Mnemos."
    )
    return ""


# Answers to "which provider?" that mean none, and the providers Mnemos knows.
_NO_PROVIDER = frozenset({"", "none", "off", "no", "skip", "local", "rule-based"})
_PROVIDERS = frozenset({"claude-cli", "claude_cli", "subscription", "openrouter", "anthropic", "openai"})
# The providers that are another program on this machine, signed in to its own account.
_CLI_PROVIDERS = frozenset({"claude-cli", "claude_cli", "subscription"})
_WARNED: set[str] = set()


def _warn_once(message: str) -> None:
    """A warning a long-running server gives once, not on every client."""
    if message not in _WARNED:
        _WARNED.add(message)
        logger.warning(message)


def chosen_provider() -> str:
    """The model provider the person chose for Mnemos, or "" for none.

    Only a choice made for Mnemos counts: MNEMOS_LLM_PROVIDER, in the
    environment or a .env file Mnemos reads, or ``llm.provider`` in its
    config. A key on its own chooses nothing. People keep provider keys in
    their shells and projects for other tools, and until 2026-10-05 one
    OPENROUTER_API_KEY was enough for a capture's words to go to openrouter.ai
    with no Mnemos setting at all. No model of Mnemos's is sent anything
    unless the person configures a provider for Mnemos; the quiet hours, when
    they're on, think over the memory through the person's own Claude Code
    (mnemos/life.py).
    """
    provider = _load_env_key("MNEMOS_LLM_PROVIDER").lower()
    if not provider:
        try:
            from .config.loader import load_config

            llm = load_config().get("llm")
        except Exception:
            llm = None
        if isinstance(llm, dict):
            provider = str(llm.get("provider") or "").strip().lower()
    if provider in _NO_PROVIDER:
        return ""
    if provider not in _PROVIDERS:
        _warn_once(
            f"Mnemos's provider {provider!r} is not one it knows (claude-cli, "
            "openrouter, anthropic or openai); no provider is used."
        )
        return ""
    if _host_secrets is not None and provider in _CLI_PROVIDERS:
        # Another program, signed in to its own account: inside Hermes a plugin
        # reaches a model only with a key Hermes hands it.
        _warn_once(
            "Mnemos's provider is the Claude CLI, which Mnemos doesn't run inside "
            "Hermes; no provider is used. A provider with a key in Hermes works."
        )
        return ""
    return provider


def create_client(agent_model_hint: str | None = None) -> "LLMClient | None":
    """The client for the provider the person chose for Mnemos, or None.

    The provider is ``chosen_provider()``: claude-cli, openrouter, anthropic
    or openai. Its key is read from the environment or a .env file Mnemos
    reads. A chosen provider without its key gives None, never another
    provider: memory goes only where the person said it may.

    None is an ordinary outcome, not a degraded one. Mnemos does not call a
    model to maintain memory: work needing judgement is proposed to the agent
    and answered in its own words. A provider only accelerates the deep
    passes for headless installs.

    This used to be gated by a substrate-affinity check that refused a model
    of the wrong family, on the reasoning that a foreign model should not
    rewrite an agent's memories. That concern was real and is now answered by
    construction rather than by policy — the agent maintains its own memory —
    so the gate and the ~200 lines behind it are gone.

    Args:
        agent_model_hint: Retained for call compatibility; no longer used.
    """
    return _create_client_unchecked()

def _create_client_unchecked() -> "LLMClient | None":
    """The chosen provider's client, without the affinity gate."""
    provider = chosen_provider()
    if not provider:
        return None

    model_override = _load_env_key("MNEMOS_MODEL")

    if provider in _CLI_PROVIDERS:
        return ClaudeCLIClient(model=model_override or "claude-haiku-4-5-20251001")

    if provider == "openai":
        key = _load_env_key("OPENAI_API_KEY")
        if key:
            return OpenAIClient(api_key=key, model=model_override or "gpt-4o-mini")
        logger.warning("Mnemos's provider is openai but OPENAI_API_KEY is not set; no provider is used.")
        return None

    if provider == "openrouter":
        key = _load_env_key("OPENROUTER_API_KEY") or _load_openclaw_openrouter_key()
        if key:
            return OpenRouterClient(
                api_key=key,
                model=model_override or "anthropic/claude-sonnet-4-5",
            )
        logger.warning("Mnemos's provider is openrouter but no OpenRouter key was found; no provider is used.")
        return None

    if provider == "anthropic":
        key = _load_env_key("ANTHROPIC_API_KEY")
        if not key:
            logger.warning("Mnemos's provider is anthropic but ANTHROPIC_API_KEY is not set; no provider is used.")
            return None
        try:
            import anthropic  # noqa: F401
        except ImportError:
            logger.warning(
                "Mnemos's provider is anthropic but the 'anthropic' package is not "
                "installed (pip install anthropic); no provider is used."
            )
            return None
        return AnthropicClient(api_key=key, model=model_override or "claude-sonnet-4-6")

    return None


class OpenAIClient:
    """LLM client using the OpenAI API directly.

    Requires: pip install httpx
    Env var: OPENAI_API_KEY
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        max_tokens: int = 500,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, prompt: str) -> str:
        """Send a prompt via OpenAI and return the response text."""
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": self._max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def structured_complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        """Send a system+user prompt with temperature control."""
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
