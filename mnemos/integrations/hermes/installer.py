"""Installer and diagnostics for the Hermes Mnemos provider shim."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...file_security import atomic_write_text
from ...setup.state import mnemos_command
from ...simple_scope import named_in_the_environment
from .scope import (
    HermesMnemosConfig,
    _load_json_config,
    config_copied_from_elsewhere,
    default_hermes_home,
    profile_agent_id,
    profile_store,
    read_settings,
    save_hermes_mnemos_config,
    slugify,
)
from .hours import HOUR_TOOL
from .tools import TOOL_SCHEMAS


PLUGIN_NAME = "mnemos"
PLUGIN_VERSION = "0.3.0"
PROVIDER_MODE = "provider"
SIDECAR_MODE = "sidecar"
DEFAULT_MCP_SERVER_NAME = "mnemos"
# What Mnemos itself writes in a server's entry: anything more is someone's own.
_OWN_SERVER_KEYS = {"command", "args", "env", "timeout", "connect_timeout"}
_OWN_SERVER_ENV = {"MNEMOS_HARNESS"}
# Mnemos and what it imports, which Hermes' own environment has to be able to find.
_NEEDS_IN_HERMES = ("mnemos", "ulid", "yaml", "mcp")
_SHIM_OPENING = '"""Mnemos memory provider shim for Hermes Agent.'
# How hermes-plugin/__init__.py opens: Mnemos as Hermes's plugin catalog installs it.
_CATALOG_OPENING = '"""Mnemos for Hermes, from Hermes\'s plugin catalog'
PRELOAD_HOOK = "mnemos-preload"
_HOOK_OPENING = '"""Mnemos: load the memory provider before the gateway takes messages.'


def provider_plugin_dirs(hermes_home: str | Path) -> list[Path]:
    """Return supported Hermes provider shim directories.

    Current local Hermes releases discover user memory providers from
    ``$HERMES_HOME/plugins/<name>``. The public docs describe memory providers
    under ``plugins/memory/<name>``. Writing both tiny shim directories keeps the
    Mnemos package compatible with both layouts without duplicating logic.
    """

    home = Path(hermes_home).expanduser()
    return [
        home / "plugins" / PLUGIN_NAME,
        home / "plugins" / "memory" / PLUGIN_NAME,
    ]


def _mnemos_import_paths() -> list[str]:
    """Where this Mnemos and what it imports are installed: usually one
    site-packages, or a checkout and a site-packages for an editable install."""

    paths: list[str] = []
    for name in _NEEDS_IN_HERMES:
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):  # ValueError: loaded, with no spec to read
            continue
        if spec is None or not spec.origin:
            continue
        origin = Path(spec.origin).resolve()
        paths.append(str(origin.parent.parent if spec.submodule_search_locations else origin.parent))
    return list(dict.fromkeys(paths))


def render_plugin_shim() -> str:
    """Return the tiny Hermes plugin shim that imports Mnemos.

    Hermes loads it in its own environment, which has no Mnemos, and hides the
    failure at debug level: until this said where Mnemos is, Provider Mode was
    set, reported active, and never loaded.

    Nothing slow runs as the file loads. Hermes shows the module to every other
    thread before running it, and one that finds no ``register`` yet goes without
    memory for its whole session: several topics speaking at once after a start.
    ``register`` waits on Python's own import lock instead, however many arrive.
    """

    return (
        f"{_SHIM_OPENING}\"\"\"\n\n\n"
        "def register(ctx):\n"
        "    import os, sys\n\n"
        "    # Where Mnemos was when it was connected. Looked in last, so Hermes' own\n"
        "    # packages win. If Mnemos moves, run `mnemos connect hermes --write` again.\n"
        f"    sys.path.extend(p for p in {_mnemos_import_paths()!r} if p not in sys.path)\n"
        "    # Its command, for what the agent is told to run: Hermes' shell may not find it.\n"
        f"    os.environ.setdefault('MNEMOS_COMMAND', {mnemos_command()!r})\n\n"
        "    from agent.memory_provider import MemoryProvider\n"
        "    from mnemos.integrations.hermes import build_memory_provider_class\n\n"
        "    ctx.register_memory_provider(build_memory_provider_class(MemoryProvider)())\n"
    )


def render_preload_hook() -> dict[str, str]:
    """A gateway hook that loads the provider before any message can arrive.

    Hermes from before October 2026 shows a plugin's module to other threads before
    running it, and a thread that finds no ``register`` yet goes without memory for
    that session. The shim makes that window small but can't close it: several topics
    speaking at once after a start reach the loader at the same instant, and two
    of three lost their memory through a real gateway. A hook's handler is loaded
    before the gateway connects to anything, so the module is whole by then. On
    a Hermes that locks its loader this only loads it a little earlier.
    """

    return {
        "HOOK.yaml": (
            f"name: {PRELOAD_HOOK}\n"
            "description: Loads Mnemos before the gateway takes messages\n"
            "events:\n"
            "  - gateway:startup\n"
        ),
        "handler.py": (
            f"{_HOOK_OPENING}\"\"\"\n\n"
            "from plugins.memory import load_memory_provider\n\n"
            'load_memory_provider("mnemos")\n\n\n'
            "def handle(event_type, context):\n"
            "    return None\n"
        ),
    }


def _hermes_python(home: Path) -> Path | None:
    """The Python Hermes runs in, when this machine has one to find."""

    found = shutil.which("hermes")
    candidates = [Path(found).resolve().parent / "python"] if found else []
    candidates.extend([
        home / "hermes-agent" / "venv" / "bin" / "python",
        home / "hermes-agent" / "venv" / "Scripts" / "python.exe",
    ])
    return next((path for path in candidates if path.is_file()), None)


def _why_hermes_cant_load_mnemos(python: Path, shim: Path) -> str | None:
    """Run the shim that's there as Hermes does, in Hermes' own Python, and say
    why it failed: Hermes' loader hides it, so nothing else would. None when it
    registers a provider."""

    code = (
        "import runpy, sys, types\n"
        "try:\n"
        "    import agent.memory_provider\n"
        "except ImportError:\n"  # Hermes isn't importable from here: only Mnemos is in question.
        "    stub = types.ModuleType('agent.memory_provider')\n"
        "    stub.MemoryProvider = type('MemoryProvider', (), {})\n"
        "    sys.modules['agent'] = types.ModuleType('agent')\n"
        "    sys.modules['agent.memory_provider'] = stub\n"
        "got = []\n"
        f"runpy.run_path({str(shim)!r})['register'](types.SimpleNamespace(register_memory_provider=got.append))\n"
        "assert got, 'the shim registered nothing'\n"
    )
    try:
        proc = subprocess.run(
            [str(python), "-c", code], capture_output=True, text=True, timeout=60, cwd=str(shim.parent),
        )
    except subprocess.TimeoutExpired:
        return "loading it took over a minute"
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    if proc.returncode == 0:
        return None
    lines = proc.stderr.strip().splitlines()
    return lines[-1] if lines else f"exit {proc.returncode}"


def _hermes_load_check(home: Path) -> tuple[str, str]:
    """Whether Hermes can load the shim that's there: ``yes``, ``no`` or
    ``not tried``, and why when it isn't yes."""

    shim = provider_plugin_dirs(home)[0] / "__init__.py"
    if not shim.is_file():
        return "no", f"there is no shim at {shim}"
    if not _holds_mnemos_plugin(shim.parent):
        return "not tried", "the file there isn't one Mnemos wrote"
    python = _hermes_python(home)
    if python is None:
        return "not tried", "Hermes isn't on this machine's PATH or in its default folder"
    problem = _why_hermes_cant_load_mnemos(python, shim)
    return ("no", problem) if problem else ("yes", "")


def _hermes_load_line(loads: str, problem: str) -> str:
    if loads == "no":
        return f"Hermes can load it: NO: {problem}"
    return f"Hermes can load it: {loads}" + (f" ({problem})" if problem else "")


def render_plugin_manifest() -> str:
    """Return Hermes plugin metadata."""

    return (
        "name: mnemos\n"
        f"version: {PLUGIN_VERSION}\n"
        "kind: exclusive\n"
        "description: Local-first Mnemos identity-continuity provider for Hermes\n"
        "provides_tools:\n"
        + "".join(f"  - {tool['name']}\n" for tool in [*TOOL_SCHEMAS, HOUR_TOOL])
        + "hooks:\n"
        "  - prefetch\n"
        "  - on_session_end\n"
        "  - on_memory_write\n"
    )


def render_plugin_readme() -> str:
    """Return the installed plugin readme."""

    return (
        "# Mnemos for Hermes\n\n"
        "This directory is a small Hermes memory-provider shim. The durable identity-continuity "
        "implementation lives in the installed `mnemos-continuity` Python package.\n\n"
        "Provider Mode makes Mnemos Hermes' single active external memory provider, leaving "
        "Hermes built-in `MEMORY.md` and `USER.md` active. It's what `mnemos connect hermes "
        "--write` sets up.\n\n"
        "Sidecar Mode leaves `memory.provider` unchanged and exposes Mnemos through MCP/tools "
        "for agents already using Honcho, Supermemory, Mem0, or another external provider.\n\n"
        "Each Hermes profile is its own agent, with its own memory in `~/.mnemos/`. Which one "
        "is in `$HERMES_HOME/mnemos.json`.\n"
    )


@dataclass
class HermesInstallResult:
    hermes_home: Path
    plugin_dir: Path
    plugin_dirs: list[Path] = field(default_factory=list)
    mode: str = PROVIDER_MODE
    files_written: list[Path] = field(default_factory=list)
    config_path: Path | None = None
    mcp_config_path: Path | None = None
    mcp_server_name: str = DEFAULT_MCP_SERVER_NAME
    mcp_configured: bool = False
    active_provider: str = ""
    activated: bool = False
    dry_run: bool = False
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    hermes_loads: str = ""
    hermes_load_problem: str = ""

    def summary(self) -> str:
        mode_label = "Provider Mode" if self.mode == PROVIDER_MODE else "Sidecar Mode"
        lines = [
            "Mnemos Hermes install",
            f"Mode: {mode_label}",
            f"HERMES_HOME: {self.hermes_home}",
        ]
        if self.mode == PROVIDER_MODE or self.files_written:
            dirs = self.plugin_dirs or [self.plugin_dir]
            lines.append("Provider shim: " + ", ".join(str(path) for path in dirs))
        if self.dry_run:
            lines.append("Dry run: yes")
        if self.files_written:
            lines.append("Files: " + ", ".join(str(path) for path in self.files_written))
        if self.config_path:
            lines.append(f"Config: {self.config_path}")
        if self.mcp_config_path:
            status = "configured" if self.mcp_configured else "not changed"
            lines.append(f"MCP sidecar: {self.mcp_server_name} ({status})")
            lines.append(f"Hermes config: {self.mcp_config_path}")
        if self.active_provider:
            lines.append(f"memory.provider: {self.active_provider}")
        elif self.mode == SIDECAR_MODE:
            lines.append("memory.provider: (not set)")
        if self.mode == PROVIDER_MODE:
            if self.activated and self.hermes_loads == "no":
                lines.append("Provider Mode active: set, but Hermes can't load it")
            else:
                lines.append(f"Provider Mode active: {'yes' if self.activated else 'no'}")
            if self.hermes_loads:
                lines.append(_hermes_load_line(self.hermes_loads, self.hermes_load_problem))
        else:
            lines.append("Provider Mode active: no (left unchanged)")
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        lines.extend(self.notes)
        if self.mode == PROVIDER_MODE and not self.activated:
            lines.append("Enable with: mnemos connect hermes --write")
        if self.mode == SIDECAR_MODE:
            lines.append("Sidecar Mode keeps the existing Hermes external memory provider and exposes Mnemos through MCP/tools.")
        return "\n".join(lines)


@dataclass
class HermesQuickstartResult:
    hermes_home: Path
    mode: str
    agent_safe: bool = False
    install_result: HermesInstallResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    preserved_provider: str = ""
    restart_likely_needed: bool = True
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if self.install_result is None:
            return False
        if self.warnings:
            return False
        if (
            self.agent_safe
            and not self.install_result.mcp_configured
            and self.install_result.active_provider != PLUGIN_NAME
        ):
            return False
        return True

    def summary(self) -> str:
        mode_label = "Provider Mode" if self.mode == PROVIDER_MODE else "Sidecar Mode"
        diagnostics = self.diagnostics or {}
        install = self.install_result
        active_provider = str(diagnostics.get("active_memory_provider") or "")
        mcp_configured = bool(diagnostics.get("mcp_server_configured"))
        provider_shim_ready = bool(diagnostics.get("provider_shim_ready"))
        command = str(diagnostics.get("mnemos_command") or "mnemos")
        preserved = self.preserved_provider or "(not set)"
        if install and install.mcp_configured:
            mcp_status = "configured"
        elif mcp_configured:
            mcp_status = "present"
        else:
            mcp_status = "not configured"
        lines = [
            "Mnemos Hermes quickstart",
            f"Mode: {mode_label}",
            f"Agent-safe: {'yes' if self.agent_safe else 'no'}",
            f"HERMES_HOME: {self.hermes_home}",
            "Doctor summary:",
        ]
        if self.mode == SIDECAR_MODE:
            lines.append(f"Preserved memory.provider: {preserved}")
        else:
            lines.append(f"memory.provider: {active_provider or '(not set)'}")
        lines.extend([
            f"MCP sidecar: {mcp_status}",
            f"Provider shim: {'installed' if provider_shim_ready else 'not installed'}",
            f"Command: {command}",
        ])
        if install and install.files_written:
            lines.append("Changed files: " + ", ".join(str(path) for path in install.files_written))
        if install and install.mcp_config_path:
            mcp_status = "updated" if install.mcp_configured else "not changed"
            lines.append(f"Hermes config: {install.mcp_config_path} ({mcp_status})")
        if self.agent_safe:
            lines.append("Preserved: SOUL.md, MEMORY.md, USER.md, AGENTS.md, and memory.provider")
        if self.restart_likely_needed:
            lines.append("Restart: yes; restart Hermes to load new provider or MCP config.")
        else:
            lines.append("Restart: not likely; no Hermes config change was made.")
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        elif self.mode == SIDECAR_MODE:
            lines.append("Ready: Mnemos is available through Hermes MCP/tools alongside the current memory provider.")
        else:
            lines.append("Ready: Mnemos is the active Hermes external memory provider.")
        return "\n".join(lines)


def install_hermes_plugin(
    *,
    hermes_home: str | Path | None = None,
    db_path: str | None = None,
    agent_id: str | None = None,
    person_id: str | None = None,
    project_scope: str | None = None,
    mode: str = PROVIDER_MODE,
    configure_mcp: bool | None = None,
    mcp_server_name: str = DEFAULT_MCP_SERVER_NAME,
    activate: bool = False,
    force: bool = False,
    dry_run: bool = False,
    agent_safe: bool = False,
) -> HermesInstallResult:
    """Install the Hermes user memory-provider shim under ``$HERMES_HOME``."""

    selected_mode = str(mode or PROVIDER_MODE).strip().lower()
    if selected_mode not in {PROVIDER_MODE, SIDECAR_MODE}:
        raise ValueError(f"Unsupported Hermes Mnemos mode: {mode}")

    home = Path(hermes_home).expanduser() if hermes_home else default_hermes_home()
    # Settings that can't be read stop it before anything is written
    # (SettingsUnreadable): they are never written over.
    read_settings(home)
    plugin_dirs = provider_plugin_dirs(home)
    plugin_dir = plugin_dirs[0]
    mcp_name = slugify(mcp_server_name, DEFAULT_MCP_SERVER_NAME)
    should_configure_mcp = selected_mode == SIDECAR_MODE if configure_mcp is None else bool(configure_mcp)
    result = HermesInstallResult(
        hermes_home=home,
        plugin_dir=plugin_dir,
        plugin_dirs=plugin_dirs,
        mode=selected_mode,
        mcp_server_name=mcp_name,
        dry_run=dry_run,
        active_provider=_read_active_provider(home / "config.yaml"),
    )
    if selected_mode == SIDECAR_MODE and agent_safe and result.active_provider == PLUGIN_NAME:
        result.mode = PROVIDER_MODE
        result.activated = True
        result.notes.append(
            "Mnemos is already Hermes' memory provider, which carries its tools: nothing to add."
        )
        return result

    # One agent, one memory, whichever way it is set up and in whatever order:
    # what was asked for here, or else the memory this Hermes already has.
    kept = HermesMnemosConfig.load(home)
    # The server in a copied home names the memory of the one it was copied from.
    copied = config_copied_from_elsewhere(home)
    if _no_scope_chosen(home, db_path, agent_id, person_id, project_scope):
        db_path, agent_id, person_id, project_scope = _one_memory_scope(home)
    else:
        db_path = db_path or kept.db_path
        agent_id = agent_id or kept.agent_id
        person_id = person_id or kept.person_id
        project_scope = project_scope or kept.project_scope

    older = home / "mnemos" / "mnemos.db"
    if db_path and older.exists() and Path(db_path).expanduser().resolve() != older.resolve():
        result.notes.append(f"An older memory from this Hermes is still at {older}. It stays there, unread.")

    files: dict[Path, str] = {}
    hook_dir = home / "hooks" / PRELOAD_HOOK
    if selected_mode == PROVIDER_MODE:
        for provider_dir in plugin_dirs:
            if _holds_catalog_plugin(provider_dir):
                result.notes.append(
                    f"Mnemos from Hermes's plugin catalog is in {provider_dir}: it stays as Hermes "
                    "installed it, and Hermes updates it (hermes plugins update mnemos)."
                )
                continue
            files.update({
                provider_dir / "__init__.py": render_plugin_shim(),
                provider_dir / "plugin.yaml": render_plugin_manifest(),
                provider_dir / "README.md": render_plugin_readme(),
            })
        files.update({hook_dir / name: content for name, content in render_preload_hook().items()})
    elif not dry_run:
        _remove_preload_hook(hook_dir)

    # Someone else's plugin under this name stays, and Mnemos isn't made the
    # provider: Hermes would load theirs and call it Mnemos.
    theirs = [
        path for path, content in files.items()
        if not force
        and not _wrote_this_folder(path.parent)
        and path.exists()
        and path.read_text(encoding="utf-8", errors="replace") != content
    ]
    for path in theirs:
        result.warnings.append(f"Existing file differs; re-run with --force to replace: {path}")
    for path, content in {} if theirs else files.items():
        if dry_run:
            result.files_written.append(path)
            continue
        ours = path.exists() and _wrote_this_folder(path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, content, backup_existing=path.exists() and (force or ours))
        result.files_written.append(path)

    if selected_mode == PROVIDER_MODE and not dry_run and not theirs:
        result.hermes_loads, result.hermes_load_problem = _hermes_load_check(home)
        if result.hermes_loads == "no":
            result.warnings.append(
                "Hermes can't load Mnemos in its own Python, so it won't wake with this memory: "
                f"{result.hermes_load_problem}"
            )

    config_updates = {
        "db_path": db_path,
        "agent_id": agent_id,
        "person_id": person_id,
        "project_scope": project_scope,
    }
    if any(value not in (None, "") for value in config_updates.values()) and not theirs:
        config_path = home / "mnemos.json"
        if dry_run:
            result.config_path = config_path
        else:
            result.config_path = save_hermes_mnemos_config(home, {**config_updates, "hermes_home": str(home)})

    # This run's first change to Hermes' config is what its backup keeps: the
    # file as it found it, however many changes follow.
    backed_up: set[Path] = set()

    def add_server() -> None:
        configured, warning, config_path = _configure_mcp_server(
            home,
            server_name=mcp_name,
            db_path=db_path,
            agent_id=agent_id,
            person_id=person_id,
            project_scope=project_scope,
            dry_run=dry_run,
            replace_existing_server=copied or not agent_safe,
            backed_up=backed_up,
        )
        result.mcp_configured = configured
        result.mcp_config_path = config_path
        if warning:
            result.warnings.append(warning)

    if should_configure_mcp:
        add_server()

    if selected_mode == SIDECAR_MODE:
        if activate:
            result.warnings.append("Sidecar Mode leaves memory.provider unchanged; ignoring --activate.")
        if result.active_provider == PLUGIN_NAME:
            # Asked for the tools alone, from Provider Mode: the switch, with the
            # same memory. (agent_safe, which promises to leave it, returned above.)
            if not dry_run:
                cleared, warning = _clear_memory_provider(home, backed_up)
                if warning:
                    result.warnings.append(warning)
                if cleared:
                    result.active_provider = _read_active_provider(home / "config.yaml")
            result.notes.append(
                "Mnemos is no longer Hermes' memory provider, so this agent has the tools alone, on "
                "the same memory. For its wake and per-message recall back: mnemos connect hermes --write"
            )
    elif theirs:
        pass  # result.activated stays False
    elif activate:
        if dry_run:
            result.activated = result.active_provider in {"", PLUGIN_NAME} or force
        else:
            activated, warning = _activate_memory_provider(home, force=force, backed_up=backed_up)
            result.activated = activated
            if warning:
                result.warnings.append(warning)
            result.active_provider = _read_active_provider(home / "config.yaml")
    else:
        result.activated = result.active_provider == PLUGIN_NAME

    if (
        selected_mode == PROVIDER_MODE
        and result.active_provider == PLUGIN_NAME
        and not should_configure_mcp
        and not dry_run
        and not theirs  # then the provider carries nothing, and the server is what the agent has
    ):
        if result.hermes_loads == "no":
            # The provider carries the tools: without it, a server is how the agent has them.
            before = _read_mcp_server(home, mcp_name)
            add_server()
            its_memory = _another_memory(home, before)
            if its_memory:
                result.notes.append(
                    f"mcp_servers.{mcp_name} kept another memory, in {its_memory}. It opens this "
                    "agent's memory now, and that one stays there, unread."
                )
        else:
            _retire_own_server(home, mcp_name, result, backed_up)

    return result


def _holds_catalog_plugin(folder: Path) -> bool:
    """Whether a plugin folder holds Mnemos as Hermes's plugin catalog installed
    it. Hermes keeps that at the commit it reviewed and updates it itself, so
    Mnemos never rewrites or removes it."""

    path = folder / "__init__.py"
    try:
        return path.is_file() and path.read_text(encoding="utf-8", errors="replace").startswith(_CATALOG_OPENING)
    except OSError:
        return False


def _holds_mnemos_plugin(folder: Path) -> bool:
    """Whether the plugin Hermes loads from a folder is Mnemos: the shim
    ``mnemos connect hermes`` writes, or the catalog's plugin."""

    return _wrote_this_folder(folder) or _holds_catalog_plugin(folder)


def _wrote_this_folder(folder: Path) -> bool:
    """Whether a plugin or hook folder holds what Mnemos wrote: those go stale as
    Mnemos moves and changes, and are its own to rewrite."""

    for name, opening in (("__init__.py", _SHIM_OPENING), ("handler.py", _HOOK_OPENING)):
        path = folder / name
        if path.is_file() and path.read_text(encoding="utf-8", errors="replace").startswith(opening):
            return True
    return False


def _no_scope_chosen(
    home: Path, db_path: str | None, agent_id: str | None, person_id: str | None, project_scope: str | None,
) -> bool:
    """Whether nobody has said which memory this is: nothing named here, none in
    ``mnemos.json``, and no store from a provider that worked it out chat by chat."""

    if any((db_path, agent_id, person_id, project_scope)):
        return False
    kept = HermesMnemosConfig.load(home)
    return not (kept.db_path or kept.agent_id) and not (home / "mnemos" / "mnemos.db").exists()


def _one_memory_scope(home: Path) -> tuple[str, str, str, str]:
    """One agent, one memory, in every chat and for everyone in them, as
    ``mnemos connect hermes`` sets it up: left to itself the provider works its
    scope out from the chat's name and the person writing, so a group's rename or
    a private chat is another memory. Each profile is its own agent. What a
    sidecar already keeps stays kept."""

    from ...simple_scope import resolve_scope

    server = _read_mcp_server(home, DEFAULT_MCP_SERVER_NAME)
    if server and not config_copied_from_elsewhere(home):
        scope = _sidecar_scope(server)
    else:
        scope = resolve_scope(agent_id=profile_agent_id(home), db_path=profile_store(home))
    return str(scope.db_path), scope.agent_id, scope.person_id, scope.project_scope


def settle_one_memory(hermes_home: str | Path | None = None) -> bool:
    """Give a home Mnemos was never connected to the memory ``mnemos connect
    hermes`` would (``_one_memory_scope``): one agent, the profile's own, with one
    memory in every chat. A plugin installed from Hermes's catalog starts this
    way, with no connect run first, and left to itself the provider would name
    its memory after each chat and person.

    What mnemos.json already names stays as named, and only what it leaves
    empty is settled: Hermes's dashboard shows each setting with what it is
    when left empty, and until 0.6.7 that held only with all of them empty.
    With just the agent named nothing was settled (a memory inside Hermes's
    folder, another for each chat and person); with just the person named,
    their name was replaced.

    Nothing changes for a home that names all of it, one the environment names
    a memory for, or one that has a memory already where its settings look as
    they stand: what it kept is under the names it worked out then, and stays
    in reach. Returns whether it wrote."""

    home = Path(hermes_home).expanduser() if hermes_home else default_hermes_home()
    raw = _load_json_config(home)
    named = {key: str(raw.get(key) or "").strip() for key in ("db_path", "agent_id", "person_id", "project_scope")}
    if all(named.values()):
        return False
    if named_in_the_environment("MNEMOS_DB_PATH") or named_in_the_environment("MNEMOS_AGENT_ID"):
        return False
    in_use = named["db_path"].replace("$HERMES_HOME", str(home)).replace("${HERMES_HOME}", str(home))
    if (Path(in_use).expanduser() if in_use else home / "mnemos" / "mnemos.db").exists():
        return False  # the memory it has kept until now stays its memory
    settled = dict(zip(named, _one_memory_scope(home)))
    try:
        save_hermes_mnemos_config(home, {
            **{key: value for key, value in settled.items() if not named[key]},
            "hermes_home": str(home),
        })
    except OSError:
        return False  # a home it can't write to: it goes on as it was
    return True


def _sidecar_scope(server: dict[str, Any]) -> Any:
    """The memory a sidecar's MCP server opens, going by its own arguments."""

    from ...simple_scope import resolve_scope

    args = [str(arg) for arg in server.get("args") or []]

    def named(flag: str) -> str | None:
        return args[args.index(flag) + 1] if flag in args[:-1] else None

    return resolve_scope(
        db_path=named("--db-path"),
        agent_id=named("--agent-id"),
        person_id=named("--person-id"),
        project_scope=named("--project-scope"),
    )


def quickstart_hermes(
    *,
    hermes_home: str | Path | None = None,
    db_path: str | None = None,
    agent_id: str | None = None,
    person_id: str | None = None,
    project_scope: str | None = None,
    provider: bool = False,
    activate_provider: bool = False,
    agent_safe: bool = False,
    mcp_server_name: str = DEFAULT_MCP_SERVER_NAME,
    dry_run: bool = False,
) -> HermesQuickstartResult:
    """Install Mnemos for Hermes with safe defaults and an immediate doctor pass."""

    home = Path(hermes_home).expanduser() if hermes_home else default_hermes_home()
    read_settings(home)  # as install does, before anything is looked at or written
    before = build_diagnostics(home)
    preserved_provider = str(before.get("active_memory_provider") or "")
    wants_provider = bool(provider or activate_provider)
    mode = SIDECAR_MODE if agent_safe or not wants_provider else PROVIDER_MODE
    activate = mode == PROVIDER_MODE
    warnings: list[str] = []
    if agent_safe and wants_provider:
        warnings.append("Agent-safe quickstart ignores provider activation flags and keeps memory.provider unchanged.")
    install = install_hermes_plugin(
        hermes_home=home,
        db_path=db_path,
        agent_id=agent_id,
        person_id=person_id,
        project_scope=project_scope,
        mode=mode,
        configure_mcp=mode == SIDECAR_MODE,
        mcp_server_name=mcp_server_name,
        activate=activate,
        dry_run=dry_run,
        agent_safe=agent_safe,
    )
    warnings.extend(install.warnings)
    after = build_diagnostics(home)
    if agent_safe:
        after_provider = str(after.get("active_memory_provider") or "")
        if after_provider != preserved_provider:
            warnings.append(
                f"Agent-safe quickstart expected to preserve memory.provider as {preserved_provider or '(not set)'}, "
                f"but found {after_provider or '(not set)'}."
            )
        if not install.mcp_configured and after_provider != PLUGIN_NAME:
            warnings.append("Agent-safe quickstart could not safely configure the Mnemos MCP sidecar.")

    restart_likely = bool(install.files_written or install.mcp_configured or install.activated)
    return HermesQuickstartResult(
        hermes_home=home,
        mode=install.mode,
        agent_safe=agent_safe,
        install_result=install,
        diagnostics=after,
        preserved_provider=preserved_provider,
        restart_likely_needed=restart_likely,
        warnings=warnings,
    )


def connect_would_change(home: Path) -> bool:
    """Whether Provider Mode here isn't what this Mnemos would set up: a plugin
    from an older Mnemos or another place, which can't load or names a path gone,
    or the server it no longer needs beside it. Read from a command run in Mnemos's
    own environment: inside Hermes the paths come out differently."""

    shim = provider_plugin_dirs(home)[0] / "__init__.py"
    try:
        stale = not _holds_catalog_plugin(shim.parent) and (
            shim.read_text(encoding="utf-8", errors="replace") != render_plugin_shim()
        )
    except OSError:
        stale = True
    server = _read_mcp_server(home, DEFAULT_MCP_SERVER_NAME)
    return stale or (_is_mnemos_server(server) and not _has_settings_of_its_own(server))


def build_diagnostics(hermes_home: str | Path | None = None) -> dict[str, Any]:
    """Return a compact diagnostics payload for Mnemos/Hermes setup."""

    home = Path(hermes_home).expanduser() if hermes_home else default_hermes_home()
    plugin_dirs = provider_plugin_dirs(home)
    plugin_dir = plugin_dirs[0]
    config_path = home / "config.yaml"
    mnemos_config = home / "mnemos.json"
    command = shutil.which("mnemos") or "mnemos"
    active = _read_active_provider(config_path)
    mcp_server = _read_mcp_server(home, DEFAULT_MCP_SERVER_NAME)
    ready_dirs = [
        path for path in plugin_dirs
        if (path / "__init__.py").exists() and (path / "plugin.yaml").exists()
    ]
    provider_shim_ready = bool(ready_dirs)
    mcp_configured = bool(mcp_server)
    loads, load_problem = _hermes_load_check(home) if active == PLUGIN_NAME else ("", "")
    if active == PLUGIN_NAME:
        mode = "provider"
    elif mcp_configured:
        mode = "sidecar"
    elif provider_shim_ready:
        mode = "provider-installed"
    else:
        mode = "not-configured"
    # A sidecar's memory is wherever its server opens it, not a file in Hermes' folder.
    db_path = Path(_sidecar_scope(mcp_server).db_path).expanduser() if mode == "sidecar" else _configured_db_path(home)
    damage = _store_damage(db_path)
    # Beside the provider, a server opening another memory splits this agent in two.
    other_memory = ""
    if active == PLUGIN_NAME and mcp_server and _is_mnemos_server(mcp_server):
        tools_store = Path(_sidecar_scope(mcp_server).db_path).expanduser()
        if tools_store.resolve() != db_path.resolve():
            other_memory = str(tools_store)
    return {
        "hermes_home": str(home),
        "plugin_dir": str(plugin_dir),
        "plugin_dirs": [str(path) for path in plugin_dirs],
        "provider_shim_ready_dirs": [str(path) for path in ready_dirs],
        "plugin_init_exists": (plugin_dir / "__init__.py").exists(),
        "plugin_manifest_exists": (plugin_dir / "plugin.yaml").exists(),
        "provider_shim_ready": provider_shim_ready,
        "hermes_config": str(config_path),
        "active_memory_provider": active,
        "mode": mode,
        "provider_mode_active": active == PLUGIN_NAME,
        "hermes_loads_mnemos": loads,
        "hermes_load_problem": load_problem,
        "external_provider_in_slot": active not in {"", PLUGIN_NAME},
        "mcp_server_name": DEFAULT_MCP_SERVER_NAME,
        "mcp_server_configured": mcp_configured,
        "mcp_server": mcp_server,
        "mnemos_config": str(mnemos_config),
        "mnemos_config_exists": mnemos_config.exists(),
        "mnemos_command": command,
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "db_damage": damage,
        "tools_open_other_memory": other_memory,
        "ready": not damage and not other_memory and (loads != "no" if active == PLUGIN_NAME else mcp_configured),
        "restart_likely_needed": active == PLUGIN_NAME or mcp_configured or provider_shim_ready,
    }


def format_diagnostics(payload: dict[str, Any]) -> str:
    """Format diagnostics for CLI output."""

    lines = [
        "Mnemos Hermes Doctor",
        "-" * 40,
        f"HERMES_HOME: {payload['hermes_home']}",
        f"Mode:        {_diagnostic_mode_label(payload)}",
        f"Plugin shim: {'yes' if payload['provider_shim_ready'] else 'no'}",
        f"Provider:    {payload['active_memory_provider'] or '(not set)'}",
        f"MCP sidecar: {'yes' if payload['mcp_server_configured'] else 'no'}",
        f"Config:      {'yes' if payload['mnemos_config_exists'] else 'no'}",
        f"Database:    {payload['db_path']} ({_store_state(payload)})",
        f"Command:     {payload['mnemos_command']}",
        f"Restart:     {'likely after install/config changes' if payload['restart_likely_needed'] else 'not likely'}",
    ]
    if payload.get("hermes_loads_mnemos"):
        lines.append(_hermes_load_line(payload["hermes_loads_mnemos"], payload.get("hermes_load_problem", "")))
    if payload.get("db_damage"):
        lines.append(
            f"The memory file is damaged: {payload['db_damage']}. Hermes still answers, without this "
            "memory. `mnemos doctor` has what to do next."
        )
    if payload.get("tools_open_other_memory"):
        lines.append(
            f"Two memories: the provider keeps {payload['db_path']}, and the tools keep "
            f"{payload['tools_open_other_memory']}. Run `mnemos connect hermes --write` to keep one."
        )
    if payload["provider_mode_active"] and payload.get("hermes_loads_mnemos") == "no":
        lines.append(
            "Provider Mode: set, but Hermes has no memory until it can load Mnemos. "
            "Run `mnemos connect hermes --write` from where Mnemos is installed now."
        )
    elif payload["provider_mode_active"]:
        lines.append("Provider Mode: active; Hermes built-in memory remains active alongside Mnemos.")
    elif payload["mcp_server_configured"]:
        preserved = payload["active_memory_provider"] or "(not set)"
        lines.append(f"Sidecar Mode: active; memory.provider preserved as {preserved}.")
    elif payload["active_memory_provider"] and payload["active_memory_provider"] != PLUGIN_NAME:
        lines.append(
            f"Hermes' memory provider is {payload['active_memory_provider']}, and Hermes has one slot. "
            "`mnemos connect hermes --write` keeps it and adds the tools alone."
        )
    else:
        lines.append("Enable with: mnemos connect hermes --write")
    return "\n".join(lines)


def _store_damage(path: Path) -> str:
    """What's wrong with the memory file, in SQLite's words, or "": fine, not there
    yet, or busy, which is not damage."""

    if not path.is_file() or path.stat().st_size == 0:
        return ""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error as exc:
        return str(exc)
    try:
        said = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
        return "" if said == "ok" else str(said)
    except sqlite3.OperationalError as exc:
        return "" if "locked" in str(exc) or "busy" in str(exc) else str(exc)
    except sqlite3.Error as exc:
        return str(exc)
    finally:
        conn.close()


def _store_state(payload: dict[str, Any]) -> str:
    if payload.get("db_damage"):
        return "damaged"
    return "exists" if payload["db_exists"] else "not created yet"


def _diagnostic_mode_label(payload: dict[str, Any]) -> str:
    mode = payload.get("mode")
    if mode == "provider":
        return "Provider Mode"
    if mode == "sidecar":
        return "Sidecar Mode"
    if mode == "provider-installed":
        return "Provider shim installed, not active"
    return "Not configured"


def _remove_preload_hook(hook_dir: Path) -> None:
    """Take the hook away with Provider Mode, if it's the one Mnemos wrote."""

    handler = hook_dir / "handler.py"
    if handler.is_file() and handler.read_text(encoding="utf-8", errors="replace").startswith(_HOOK_OPENING):
        for name in ("handler.py", "HOOK.yaml"):
            (hook_dir / name).unlink(missing_ok=True)
        shutil.rmtree(hook_dir / "__pycache__", ignore_errors=True)
        try:
            hook_dir.rmdir()
        except OSError:
            pass  # someone keeps something of their own there


def _is_mnemos_server(server: Any) -> bool:
    """Whether an MCP server's entry runs Mnemos, rather than something of the
    same name."""

    if not isinstance(server, dict):
        return False
    args = [str(arg) for arg in server.get("args") or []]
    return Path(str(server.get("command") or "")).stem == "mnemos" and "serve" in args


def _has_settings_of_its_own(server: dict[str, Any]) -> bool:
    env = server.get("env")
    return bool(set(server) - _OWN_SERVER_KEYS or (isinstance(env, dict) and set(env) - _OWN_SERVER_ENV))


def _write_config(config_path: Path, text: str, backed_up: set[Path] | None) -> None:
    """Hermes' config, written where it really lives (a linked file stays linked),
    with a backup of it as this run found it."""

    target = config_path.resolve() if config_path.is_symlink() else config_path
    first = backed_up is None or target not in backed_up
    atomic_write_text(target, text, backup_existing=first and target.exists())
    if backed_up is not None:
        backed_up.add(target)


def _retire_own_server(home: Path, server_name: str, result: HermesInstallResult, backed_up: set[Path]) -> None:
    """Take out the server Mnemos wrote for this agent when it had only tools. The
    provider carries them now, and one that can't tell conversations apart beside
    it would show the agent every tool twice. One with settings of its own stays."""

    server = _read_mcp_server(home, server_name)
    if not server or not _is_mnemos_server(server):
        return
    if _has_settings_of_its_own(server):
        result.notes.append(
            f"mcp_servers.{server_name} has settings of its own, so it stays, and the agent will see "
            "Mnemos's tools twice. Take it out of Hermes' config when you're ready."
        )
        return
    problem = _without_server(home, server_name, backed_up)
    if problem:
        result.warnings.append(problem)
        return
    said = f"The provider carries the tools now, so mcp_servers.{server_name} is gone."
    its_memory = _another_memory(home, server)
    if its_memory:
        said += f" It kept another memory, in {its_memory}, which stays there, unread."
    result.notes.append(said)


def _another_memory(home: Path, server: dict[str, Any] | None) -> Path | None:
    """The store a Mnemos server opens, if it isn't the one this home's config names."""

    if not server or not _is_mnemos_server(server):
        return None
    its_memory = Path(_sidecar_scope(server).db_path).expanduser()
    return None if its_memory.resolve() == _configured_db_path(home).resolve() else its_memory


def _without_server(home: Path, server_name: str, backed_up: set[Path] | None) -> str | None:
    """Take one server out of Hermes' config, or say why not."""

    config_path = home / "config.yaml"
    try:
        import yaml  # type: ignore

        existing = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        servers = existing.get("mcp_servers") if isinstance(existing, dict) else None
        if not isinstance(servers, dict) or server_name not in servers:
            return None
        del servers[server_name]
        if not servers:
            del existing["mcp_servers"]
        _write_config(config_path, yaml.safe_dump(existing, sort_keys=False), backed_up)
        return None
    except Exception as exc:
        return f"Could not update {config_path}: {exc}"


def _configure_mcp_server(
    home: Path,
    *,
    server_name: str,
    db_path: str | None = None,
    agent_id: str | None = None,
    person_id: str | None = None,
    project_scope: str | None = None,
    dry_run: bool = False,
    replace_existing_server: bool = True,
    backed_up: set[Path] | None = None,
) -> tuple[bool, str | None, Path]:
    config_path = home / "config.yaml"
    if dry_run:
        return True, None, config_path

    server = _mcp_server_config(
        db_path=db_path,
        agent_id=agent_id,
        person_id=person_id,
        project_scope=project_scope,
    )

    try:
        import yaml  # type: ignore
    except Exception:
        if config_path.exists():
            return (
                False,
                "PyYAML is not available, so existing config.yaml was not modified for MCP sidecar mode.",
                config_path,
            )
        home.mkdir(parents=True, exist_ok=True)
        atomic_write_text(config_path, _render_mcp_only_config(server_name, server))
        return True, None, config_path

    home.mkdir(parents=True, exist_ok=True)
    try:
        if config_path.exists():
            raw_existing = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if raw_existing is None:
                existing = {}
            elif isinstance(raw_existing, dict):
                existing = raw_existing
            else:
                return (
                    False,
                    f"Existing {config_path} is not a YAML mapping, so it was not modified for MCP sidecar mode.",
                    config_path,
                )
        else:
            existing = {}
        mcp_servers = existing.get("mcp_servers")
        if mcp_servers is None:
            mcp_servers = {}
        elif not isinstance(mcp_servers, dict):
            return (
                False,
                f"Existing mcp_servers in {config_path} is not a YAML mapping, so it was not modified.",
                config_path,
            )
        existing_server = mcp_servers.get(server_name)
        if isinstance(existing_server, dict) and existing_server:
            same_server = all(existing_server.get(key) == server[key] for key in ("command", "args"))
            if not same_server and not replace_existing_server:
                return (
                    False,
                    f"Existing mcp_servers.{server_name} differs; agent-safe mode left it unchanged.",
                    config_path,
                )
            # What Mnemos runs is Mnemos's to set. Everything else there is someone's own.
            own_env = existing_server.get("env")
            server = {
                **server,
                **existing_server,
                "command": server["command"],
                "args": server["args"],
                "env": {**(own_env if isinstance(own_env, dict) else {}), **server["env"]},
            }
            if server == existing_server:
                return True, None, config_path
        elif existing_server and not replace_existing_server:
            return (
                False,
                f"Existing mcp_servers.{server_name} differs; agent-safe mode left it unchanged.",
                config_path,
            )
        mcp_servers[server_name] = server
        existing["mcp_servers"] = mcp_servers
        _write_config(config_path, yaml.safe_dump(existing, sort_keys=False), backed_up)
        return True, None, config_path
    except Exception as exc:
        return False, f"Could not update {config_path} for MCP sidecar mode: {exc}", config_path


def _mcp_server_config(
    *,
    db_path: str | None = None,
    agent_id: str | None = None,
    person_id: str | None = None,
    project_scope: str | None = None,
) -> dict[str, Any]:
    args = ["serve", "--mode", "simple"]
    if db_path:
        args.extend(["--db-path", db_path])
    if agent_id:
        args.extend(["--agent-id", agent_id])
    if person_id:
        args.extend(["--person-id", person_id])
    if project_scope:
        args.extend(["--project-scope", project_scope])
    return {
        "command": mnemos_command(),
        "args": args,
        # How the server knows which agent it is serving (Hermes sends nothing
        # that says so).
        "env": {"MNEMOS_HARNESS": "hermes"},
        "timeout": 120,
        "connect_timeout": 60,
    }


def _render_mcp_only_config(server_name: str, server: dict[str, Any]) -> str:
    lines = [
        "mcp_servers:",
        f"  {server_name}:",
        f"    command: {json.dumps(str(server['command']))}",
        "    args:",
    ]
    lines.extend(f"      - {json.dumps(str(arg))}" for arg in server["args"])
    lines.extend([
        "    env:",
        '      MNEMOS_HARNESS: "hermes"',
        f"    timeout: {int(server['timeout'])}",
        f"    connect_timeout: {int(server['connect_timeout'])}",
    ])
    return "\n".join(lines) + "\n"


def _read_mcp_server(home: Path, server_name: str) -> dict[str, Any]:
    config_path = home / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml  # type: ignore

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            servers = raw.get("mcp_servers")
            if isinstance(servers, dict):
                server = servers.get(server_name)
                return server if isinstance(server, dict) else {}
    except Exception:
        pass
    try:
        text = config_path.read_text(encoding="utf-8")
        raw_json = json.loads(text)
        servers = raw_json.get("mcp_servers") if isinstance(raw_json, dict) else None
        server = servers.get(server_name) if isinstance(servers, dict) else None
        return server if isinstance(server, dict) else {}
    except Exception:
        pass
    try:
        return _read_simple_mcp_yaml(config_path.read_text(encoding="utf-8", errors="replace"), server_name)
    except Exception:
        pass
    return {}


def _read_simple_mcp_yaml(text: str, server_name: str) -> dict[str, Any]:
    server: dict[str, Any] = {}
    in_mcp = False
    in_server = False
    in_args = False
    args: list[str] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if not line.startswith(" ") and stripped != "mcp_servers:":
            in_mcp = False
            in_server = False
            in_args = False
        if stripped == "mcp_servers:":
            in_mcp = True
            continue
        if not in_mcp:
            continue
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            in_server = stripped[:-1] == server_name
            in_args = False
            continue
        if not in_server:
            continue
        if stripped == "args:":
            in_args = True
            continue
        if in_args and stripped.startswith("- "):
            args.append(_simple_yaml_value(stripped[2:]))
            continue
        in_args = False
        if ":" in stripped:
            key, raw = stripped.split(":", 1)
            server[key.strip()] = _simple_yaml_value(raw.strip())
    if args:
        server["args"] = args
    return server


def _simple_yaml_value(raw: str) -> Any:
    if raw == "{}":
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _configured_db_path(home: Path) -> Path:
    raw = HermesMnemosConfig.load(home).db_path
    if not raw:
        return home / "mnemos" / "mnemos.db"
    return Path(raw.replace("$HERMES_HOME", str(home)).replace("${HERMES_HOME}", str(home))).expanduser()


def _activate_memory_provider(
    home: Path, *, force: bool = False, backed_up: set[Path] | None = None,
) -> tuple[bool, str | None]:
    config_path = home / "config.yaml"
    try:
        import yaml  # type: ignore
    except Exception:
        if config_path.exists():
            return False, "PyYAML is not available, so existing config.yaml was not modified."
        home.mkdir(parents=True, exist_ok=True)
        atomic_write_text(config_path, "memory:\n  provider: mnemos\n")
        return True, None

    home.mkdir(parents=True, exist_ok=True)
    try:
        existing = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        if existing is None:
            existing = {}
        if not isinstance(existing, dict):
            return False, f"Existing {config_path} is not a YAML mapping, so it was not modified."
        memory = existing.get("memory")
        if memory is None:
            existing["memory"] = memory = {}
        elif not isinstance(memory, dict):
            return False, f"Existing memory section in {config_path} is not a mapping, so it was not modified."
        holder = str(memory.get("provider") or "")
        if holder == PLUGIN_NAME:
            return True, None
        if holder and not force:
            return False, (
                f"Hermes' memory provider is {holder}, and Hermes has one slot, so I left it. "
                "`mnemos connect hermes --write` keeps it and adds the tools alone; "
                "`mnemos hermes install --activate --force` replaces it."
            )
        memory["provider"] = PLUGIN_NAME
        _write_config(config_path, yaml.safe_dump(existing, sort_keys=False), backed_up)
        return True, None
    except Exception as exc:
        return False, f"Could not update {config_path}: {exc}"


def _clear_memory_provider(home: Path, backed_up: set[Path] | None = None) -> tuple[bool, str | None]:
    """Take Mnemos out of Hermes' memory-provider slot, and only Mnemos."""

    config_path = home / "config.yaml"
    try:
        import yaml  # type: ignore

        existing = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        memory = existing.get("memory") if isinstance(existing, dict) else None
        if not isinstance(memory, dict) or memory.get("provider") != PLUGIN_NAME:
            return False, None
        del memory["provider"]
        if not memory:
            del existing["memory"]
        _write_config(config_path, yaml.safe_dump(existing, sort_keys=False), backed_up)
        return True, None
    except Exception as exc:
        return False, f"Could not update {config_path}: {exc}"


def known_hermes_homes() -> list[Path]:
    """Every Hermes home this machine shows: the one in use, the default, and each
    profile's."""

    default = Path.home() / ".hermes"
    homes = [default_hermes_home(), default]
    profiles = default / "profiles"
    if profiles.is_dir():
        homes.extend(sorted(path for path in profiles.iterdir() if path.is_dir()))
    seen: dict[Path, Path] = {}
    for home in homes:
        seen.setdefault(home.resolve(), home)
    return list(seen.values())


def remove_from_hermes(home: Path, *, write: bool) -> tuple[list[str], list[str]]:
    """Take Mnemos out of one Hermes home: the provider slot, its server, its
    plugin and its hook. Without ``write``, say what that would do. Returns what
    it did and what it couldn't. ``mnemos.json`` stays, as the memories do: it's
    how connecting again finds this agent's memory."""

    done: list[str] = []
    problems: list[str] = []
    verb = "removed from" if write else "in"
    backed_up: set[Path] = set()
    config_path = home / "config.yaml"
    if _read_active_provider(config_path) == PLUGIN_NAME:
        problem = None
        if write:
            _cleared, problem = _clear_memory_provider(home, backed_up)
        if problem:
            problems.append(problem)
        else:
            done.append(f"Hermes: memory.provider {verb} {config_path}")
    if _is_mnemos_server(_read_mcp_server(home, DEFAULT_MCP_SERVER_NAME)):
        problem = _without_server(home, DEFAULT_MCP_SERVER_NAME, backed_up) if write else None
        if problem:
            problems.append(problem)
        else:
            done.append(f"Hermes: the {DEFAULT_MCP_SERVER_NAME} server {verb} {config_path}")
    for folder in provider_plugin_dirs(home):
        if _wrote_this_folder(folder):
            if write:
                _remove_plugin_folder(folder)
            done.append(f"Hermes: the Mnemos plugin {verb} {folder}")
    hook_dir = home / "hooks" / PRELOAD_HOOK
    if _wrote_this_folder(hook_dir):
        if write:
            _remove_preload_hook(hook_dir)
        done.append(f"Hermes: the preload hook {verb} {hook_dir}")
    return done, problems


def _remove_plugin_folder(folder: Path) -> None:
    """Take away what Mnemos wrote in a plugin folder, and the folder if that
    empties it: someone may keep something of their own there."""

    for name in ("__init__.py", "plugin.yaml", "README.md"):
        (folder / name).unlink(missing_ok=True)
        (folder / f"{name}.bak").unlink(missing_ok=True)
    shutil.rmtree(folder / "__pycache__", ignore_errors=True)
    try:
        folder.rmdir()
    except OSError:
        pass


def _read_active_provider(config_path: Path) -> str:
    if not config_path.exists():
        return ""
    try:
        import yaml  # type: ignore

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            memory = raw.get("memory")
            if isinstance(memory, dict):
                return str(memory.get("provider") or "")
    except Exception:
        pass
    try:
        # Without PyYAML: read the `provider:` line inside the top-level
        # `memory:` block, and no other. The file also names the model
        # provider (`model: provider: ...`), which is not the memory's.
        in_memory = False
        for line in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line[0].isspace():
                in_memory = line.split("#", 1)[0].strip() == "memory:"
                continue
            stripped = line.strip()
            if in_memory and stripped.startswith("provider:"):
                value = stripped.split(":", 1)[1].split("#", 1)[0].strip().strip("'\"")
                return value
    except Exception:
        pass
    return os.environ.get("HERMES_MEMORY_PROVIDER", "")
