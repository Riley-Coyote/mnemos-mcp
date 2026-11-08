"""What each harness has of Mnemos on this machine, read without changing
anything, and the parts of connecting that are specific to one harness.

``mnemos connect`` (``cli._cmd_connect``) asks this module what is there, and
the first session's setup part asks it too (``MnemosRuntime._setup_part``).
Nothing here assumes: a server counts when a harness's own config names it,
a hook counts when a hooks file holds a Mnemos command for the right store.

Readers never create a file, a folder or a store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shlex
import shutil
from typing import Any

from . import harnesses as table
from .state import claude_code_settings_path, is_mnemos_hook

SERVER_NAME = "mnemos"


# ── Where each harness keeps things ──


def codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".codex"


def grok_home() -> Path:
    raw = os.environ.get("GROK_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".grok"


def gemini_settings_path() -> Path:
    """Gemini CLI's user settings: under ``GEMINI_CLI_HOME`` when that is set
    (Gemini's own override), else under the home folder."""
    base = os.environ.get("GEMINI_CLI_HOME", "").strip()
    return (Path(base).expanduser() if base else Path.home()) / ".gemini" / "settings.json"


def claude_json_path() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if config_dir:
        return Path(config_dir).expanduser() / ".claude.json"
    return Path.home() / ".claude.json"


def openclaw_state_dir() -> Path:
    raw = os.environ.get("OPENCLAW_STATE_DIR", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".openclaw"


def openclaw_config_path() -> Path:
    raw = os.environ.get("OPENCLAW_CONFIG_PATH", "").strip()
    return Path(raw).expanduser() if raw else openclaw_state_dir() / "openclaw.json"


def hermes_home() -> Path:
    from ..integrations.hermes.scope import default_hermes_home

    return default_hermes_home()


def hooks_path(harness: table.Harness) -> Path | None:
    """The file Mnemos's hooks go in for a harness, or None when it has none
    that reach the model."""
    if harness.key == "claude-code":
        return claude_code_settings_path()
    if harness.key == "codex":
        return codex_home() / "hooks.json"
    if harness.key == "gemini":
        return gemini_settings_path()
    return None


def openclaw_hook_dir() -> Path:
    return openclaw_state_dir() / "hooks" / "mnemos-wake"


# ── Reading ──


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _read_toml(path: Path) -> dict | None:
    try:
        text = path.read_text()
    except OSError:
        return None
    try:
        try:
            import tomllib
        except ImportError:  # Python 3.10
            import tomli as tomllib  # type: ignore[no-redef]
        return tomllib.loads(text)
    except Exception:
        pass
    # No TOML reader: enough to see which servers exist and what they run.
    found: dict[str, Any] = {}
    for match in re.finditer(r"^\[mcp_servers\.([A-Za-z0-9_-]+)\]\s*$", text, re.MULTILINE):
        block = text[match.end():].split("\n[", 1)[0]
        command = re.search(r'^command\s*=\s*"([^"]*)"', block, re.MULTILINE)
        args = re.search(r"^args\s*=\s*\[(.*?)\]", block, re.MULTILINE | re.DOTALL)
        found[match.group(1)] = {
            "command": command.group(1) if command else "",
            "args": re.findall(r'"([^"]*)"', args.group(1)) if args else [],
        }
    return {"mcp_servers": found}


@dataclass
class Server:
    """A Mnemos server a harness has in its config."""

    name: str
    command: str
    args: list[str]
    env: dict[str, str]
    source: str  # the file it came from
    inherited: bool = False  # the harness borrowed it from another agent's config

    def scope(self) -> tuple[str | None, str | None]:
        """The agent id and store this server was started for."""
        return _flags(self.args, self.env)

    def person_and_project(self) -> tuple[str | None, str | None]:
        """Whose memory it opens, and which part of it."""
        return (
            _flag(self.args, "--person-id") or self.env.get("MNEMOS_PERSON_ID"),
            _flag(self.args, "--project-scope") or self.env.get("MNEMOS_PROJECT_SCOPE"),
        )


def _flag(args: list[str], name: str) -> str | None:
    found = None
    for index, part in enumerate(args):
        if part == name and index + 1 < len(args):
            found = args[index + 1]
        elif part.startswith(f"{name}="):
            found = part.split("=", 1)[1]
    return found


def _flags(args: list[str], env: dict[str, str]) -> tuple[str | None, str | None]:
    agent = db = None
    for index, part in enumerate(args):
        value = args[index + 1] if index + 1 < len(args) else None
        if part == "--agent-id" and value:
            agent = value
        elif part.startswith("--agent-id="):
            agent = part.split("=", 1)[1]
        elif part == "--db-path" and value:
            db = value
        elif part.startswith("--db-path="):
            db = part.split("=", 1)[1]
    return agent or env.get("MNEMOS_AGENT_ID"), db or env.get("MNEMOS_DB_PATH")


def _is_mnemos_server(name: str, entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    if not isinstance(command, str):
        return False
    args = [str(a) for a in entry.get("args", []) if isinstance(a, (str, int))]
    if Path(command).stem.lower().startswith("mnemos"):
        return True
    return name == SERVER_NAME and any("mnemos" in a for a in args)


def _servers_in(mapping: Any, source: str, inherited: bool = False) -> list[Server]:
    found: list[Server] = []
    if not isinstance(mapping, dict):
        return found
    for name, entry in mapping.items():
        if _is_mnemos_server(name, entry):
            env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
            found.append(Server(
                name=name,
                command=entry["command"],
                args=[str(a) for a in entry.get("args", [])],
                env={str(k): str(v) for k, v in env.items()},
                source=source,
                inherited=inherited,
            ))
    return found


def _grok_borrows_claude_servers() -> bool:
    """Whether Grok reads Claude Code's MCP servers (it does unless told not to)."""
    if os.environ.get("GROK_CLAUDE_MCPS_ENABLED", "").strip().lower() in ("0", "false", "no"):
        return False
    config = _read_toml(grok_home() / "config.toml") or {}
    compat = config.get("compat")
    claude = compat.get("claude") if isinstance(compat, dict) else None
    return not (isinstance(claude, dict) and claude.get("mcps") is False)


def servers(harness: table.Harness) -> list[Server]:
    """The Mnemos servers a harness would start, from its own config files
    (and, for Grok, the Claude Code ones it borrows)."""
    if harness.key == "claude-code":
        path = claude_json_path()
        data = _read_json(path)
        return _servers_in(data.get("mcpServers") if isinstance(data, dict) else None, str(path))
    if harness.key == "codex":
        path = codex_home() / "config.toml"
        data = _read_toml(path)
        return _servers_in(data.get("mcp_servers") if data else None, str(path))
    if harness.key == "grok":
        path = grok_home() / "config.toml"
        data = _read_toml(path)
        own = _servers_in(data.get("mcp_servers") if data else None, str(path))
        if own or not _grok_borrows_claude_servers():
            return own
        borrowed = claude_json_path()
        data = _read_json(borrowed)
        return _servers_in(
            data.get("mcpServers") if isinstance(data, dict) else None, str(borrowed), inherited=True,
        )
    if harness.key == "gemini":
        path = gemini_settings_path()
        data = _read_json(path)
        return _servers_in(data.get("mcpServers") if isinstance(data, dict) else None, str(path))
    if harness.key == "openclaw":
        path = openclaw_config_path()
        data = _read_json(path)
        mcp = data.get("mcp") if isinstance(data, dict) else None
        return _servers_in(mcp.get("servers") if isinstance(mcp, dict) else None, str(path))
    if harness.key == "hermes":
        from ..integrations.hermes.installer import _read_mcp_server

        home = hermes_home()
        entry = _read_mcp_server(home, SERVER_NAME)
        return _servers_in({SERVER_NAME: entry} if entry else None, str(home / "config.yaml"))
    return []


def _hook_commands(harness: table.Harness, event: str, subcommand: str) -> list[str]:
    """The Mnemos commands installed under one hook event."""
    path = hooks_path(harness)
    data = _read_json(path) if path else None
    hooks = data.get("hooks") if isinstance(data, dict) else None
    listed = hooks.get(event) if isinstance(hooks, dict) else None
    commands: list[str] = []
    for entry in listed if isinstance(listed, list) else []:
        if is_mnemos_hook(entry, subcommand):
            commands.extend(
                h["command"] for h in entry.get("hooks", [])
                if isinstance(h, dict) and isinstance(h.get("command"), str)
            )
    return commands


def hook_scope(commands: list[str]) -> list[tuple[str | None, str | None]]:
    """The (agent id, store) each hook command reads."""
    out = []
    for command in commands:
        try:
            out.append(_flags(shlex.split(command), {}))
        except ValueError:
            continue
    return out


def _same_store(found: tuple[str | None, str | None], agent_id: str, db_path: str) -> bool:
    from ..simple_scope import resolve_scope

    agent, db = found
    scope = resolve_scope(db_path=db, agent_id=agent)
    wanted = resolve_scope(db_path=db_path, agent_id=agent_id)
    return (
        Path(scope.db_path).expanduser().resolve() == Path(wanted.db_path).expanduser().resolve()
    )


def has_hook(harness: table.Harness, kind: str, agent_id: str, db_path: str) -> bool:
    """Whether a Mnemos hook of this kind ("wake" or "cue") is installed for
    exactly this memory. A hook for another agent's memory does not count."""
    if harness.key == "openclaw":
        if kind != "wake":
            return False
        handler = openclaw_hook_dir() / "handler.js"
        try:
            text = handler.read_text()
        except OSError:
            return False
        return db_path in text or str(Path(db_path).expanduser()) in text
    event = harness.wake_event if kind == "wake" else harness.cue_event
    if not event:
        return False
    subcommand = "session-start" if kind == "wake" else "prompt"
    return any(
        _same_store(found, agent_id, db_path)
        for found in hook_scope(_hook_commands(harness, event, subcommand))
    )


def on_this_machine(harness: table.Harness) -> bool:
    """Whether the harness is here: its command on PATH."""
    return shutil.which(harness.command) is not None


@dataclass
class Found:
    harness: table.Harness
    installed: bool
    servers: list[Server] = field(default_factory=list)
    wake: bool | None = None
    cue: bool | None = None
    hermes_provider: str = ""
    hermes_elsewhere: bool = False  # Mnemos holds Hermes' slot, for another memory


def find(harness: table.Harness, agent_id: str, db_path: str) -> Verdict:
    """Everything connect would need to know about one harness: is it here, is
    Mnemos in its config, and are the hooks for this memory in."""
    found = Found(harness=harness, installed=on_this_machine(harness), servers=servers(harness))
    if harness.wake_event:
        found.wake = has_hook(harness, "wake", agent_id, db_path)
    if harness.cue_event:
        found.cue = has_hook(harness, "cue", agent_id, db_path)
    if harness.key == "hermes":
        from ..integrations.hermes.installer import _holds_mnemos_plugin, _read_active_provider, provider_plugin_dirs
        from ..integrations.hermes.scope import HermesMnemosConfig

        home = hermes_home()
        found.hermes_provider = _read_active_provider(home / "config.yaml")
        # The provider wakes the memory its own config names, which must be this
        # one, and only if the plugin it loads is there.
        kept = HermesMnemosConfig.load(home)
        here = _same_store((kept.agent_id, kept.db_path), agent_id, db_path)
        holds = found.hermes_provider == "mnemos"
        found.wake = found.cue = holds and here and _holds_mnemos_plugin(provider_plugin_dirs(home)[0])
        found.hermes_elsewhere = holds and not here and bool(kept.agent_id or kept.db_path)
    return Verdict(found)


class Verdict:
    """What is set for one harness, in the words connect and the first session
    use. Built from ``Found``."""

    def __init__(self, found: Found) -> None:
        self.found = found

    @property
    def harness(self) -> table.Harness:
        return self.found.harness

    @property
    def own_server(self) -> Server | None:
        own = [s for s in self.found.servers if not s.inherited]
        return own[0] if own else None

    @property
    def borrowed_server(self) -> Server | None:
        borrowed = [s for s in self.found.servers if s.inherited]
        return borrowed[0] if borrowed else None

    def has_mcp_for(self, agent_id: str, db_path: str) -> bool:
        server = self.own_server
        if server is None:
            return False
        return _same_store(server.scope(), agent_id, db_path)


def _hermes_config():
    from ..integrations.hermes.scope import HermesMnemosConfig

    return HermesMnemosConfig.load(hermes_home())


def _hermes_goes_by_its_config() -> bool:
    """Whether the memory Hermes' own Mnemos settings name is this agent's, over one a
    server in its config opens. A copy's server opens the memory of the one it was
    copied from. And where Mnemos is the provider, what the agent wakes from is its
    memory; a server beside it opening another is the one that goes, and connect names it."""
    from ..integrations.hermes.installer import _read_active_provider
    from ..integrations.hermes.scope import config_copied_from_elsewhere

    kept = _hermes_config()
    if not (kept.agent_id or kept.db_path):
        return False
    home = hermes_home()
    return config_copied_from_elsewhere(home) or _read_active_provider(home / "config.yaml") == "mnemos"


def existing_person_and_project(harness: table.Harness) -> tuple[str | None, str | None]:
    """Whose memory this is and which part of it, where connecting rewrites the setup
    around them: Hermes', whose plugin goes stale as Mnemos moves on. Recall looks only
    there, so losing them cuts the agent off from what it has."""
    if harness.key != "hermes":
        return None, None
    own = [s for s in servers(harness) if not s.inherited]
    if own and not _hermes_goes_by_its_config() and any(own[0].person_and_project()):
        return own[0].person_and_project()
    kept = _hermes_config()
    return kept.person_id, kept.project_scope


def existing_scope(harness: table.Harness) -> tuple[str | None, str | None] | None:
    """The agent id and store this harness already uses for its own Mnemos
    server or hook, so connecting again keeps the memory where it is: None
    when it has none; (None, None) when it has one that names neither, which
    keeps the defaults it was set up with."""
    own = [s for s in servers(harness) if not s.inherited]
    if harness.key == "hermes" and _hermes_goes_by_its_config():
        kept = _hermes_config()
        return kept.agent_id, kept.db_path
    for server in own:
        agent, db = server.scope()
        if agent or db:
            return agent, db
    if harness.key == "hermes":
        kept = _hermes_config()
        if kept.agent_id or kept.db_path:
            return kept.agent_id, kept.db_path
    for event, subcommand in (
        (harness.wake_event, "session-start"), (harness.cue_event, "prompt"),
    ):
        if not event or harness.key == "openclaw":
            continue
        for agent, db in hook_scope(_hook_commands(harness, event, subcommand)):
            if agent or db:
                return agent, db
    if own:
        return None, None
    return None


@dataclass
class Status:
    """What is set for one harness and one memory, and what is not."""

    harness: table.Harness
    agent_id: str
    db_path: str
    # "set", "missing", "borrowed", "elsewhere" (a server for another memory), or,
    # for Hermes, "provider": the memory provider carries the tools.
    mcp: str
    wake: str  # "set", "missing", "cannot"
    cue: str
    upkeep: bool
    borrowed: Server | None = None
    provider: str = ""  # Hermes: who holds the memory-provider slot


def status(harness: table.Harness, agent_id: str, db_path: str) -> Status:
    """Read, from the machine, what ``harness`` has of this memory."""
    from . import state

    verdict = find(harness, agent_id, db_path)
    found = verdict.found
    if harness.key == "hermes" and found.wake:
        mcp = "provider"
    elif found.hermes_elsewhere:
        mcp = "elsewhere"
    elif verdict.has_mcp_for(agent_id, db_path):
        mcp = "set"
    elif verdict.own_server is not None:
        mcp = "elsewhere"
    elif verdict.borrowed_server is not None:
        mcp = "borrowed"
    else:
        mcp = "missing"

    def kind(ability: table.Ability, event: str | None, present: bool | None) -> str:
        if harness.key == "hermes":
            if found.hermes_provider and found.hermes_provider != "mnemos":
                return "cannot"
            return "set" if present else "missing"
        if ability.works is False or event is None:
            return "cannot"
        return "set" if present else "missing"

    return Status(
        harness=harness,
        agent_id=agent_id,
        db_path=db_path,
        mcp=mcp,
        wake=kind(harness.wake, harness.wake_event or ("provider" if harness.key == "hermes" else None), found.wake),
        cue=kind(harness.cue, harness.cue_event or ("provider" if harness.key == "hermes" else None), found.cue),
        upkeep=state.upkeep_on(agent_id),
        borrowed=verdict.borrowed_server,
        provider=found.hermes_provider,
    )


# ── OpenClaw's hook ──


def render_openclaw_handler(mnemos: str, scope_flags: list[str]) -> str:
    """The OpenClaw internal hook that adds the wake to the agent's bootstrap
    files. It runs ``mnemos hook session-start`` and puts what it prints in
    one more file; if that prints nothing or fails, it adds nothing."""
    return f"""// Written by `mnemos connect openclaw`. Adds this agent's memory to what
// OpenClaw loads at the start of a run. If Mnemos prints nothing, so does this.
import {{ execFile }} from "node:child_process";
import {{ mkdir, writeFile }} from "node:fs/promises";
import {{ dirname, join }} from "node:path";
import {{ fileURLToPath }} from "node:url";

const MNEMOS = {json.dumps(mnemos)};
const ARGS = {json.dumps(["hook", "session-start", *scope_flags])};

function wake() {{
  return new Promise((resolve) => {{
    const child = execFile(MNEMOS, ARGS, {{ timeout: 10000, maxBuffer: 1 << 20 }}, (err, out) => {{
      if (err) return resolve("");
      try {{
        resolve(JSON.parse(out).hookSpecificOutput.additionalContext || "");
      }} catch {{
        resolve("");
      }}
    }});
    child.stdin.end("{{}}");
  }});
}}

export default async function handler(event) {{
  if (event.type !== "agent" || event.action !== "bootstrap") return;
  const files = event.context && event.context.bootstrapFiles;
  if (!Array.isArray(files)) return;
  const text = await wake();
  if (!text) return;
  const dir = dirname(fileURLToPath(import.meta.url));
  const path = join(dir, "MEMORY.md");
  await mkdir(dir, {{ recursive: true }});
  await writeFile(path, text);
  files.push({{ name: "MEMORY.md", path, content: text, missing: false }});
}}
"""


OPENCLAW_HOOK_MD = """---
name: mnemos-wake
description: "Wake with this agent's Mnemos memory"
metadata:
  { "openclaw": { "events": ["agent:bootstrap"] } }
---

# Mnemos wake

Adds the agent's own memory to its bootstrap files when a run starts.
Written by `mnemos connect openclaw`; remove with `mnemos uninstall`.
"""
