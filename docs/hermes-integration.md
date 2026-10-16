# Mnemos Hermes Integration

Mnemos for Hermes is a complementary identity-continuity layer. It gives Hermes agents durable self-model continuity, scoped corrections, hypomnema persistence, session handoffs, startup context, and continuity reports without replacing Hermes built-in `MEMORY.md` / `USER.md`.

Hermes built-in memory is always active. Hermes also supports one active external memory provider in `memory.provider`, so Mnemos has two supported modes:

- Provider Mode: `memory.provider=mnemos`; through Hermes's memory-provider hooks the agent wakes with its memory and gets what bears on each message before the turn, and it writes its memory itself, with its own tools.
- Sidecar Mode: `memory.provider` is left unchanged; Mnemos identity continuity is exposed through MCP/tools for users already running Honcho, Supermemory, Mem0, Hindsight, or another external provider.

The implementation follows the current Hermes memory-provider contract:

- one external provider selected through `memory.provider`
- built-in memory remains active alongside the selected external provider
- user-installed providers discovered from `$HERMES_HOME/plugins/<name>/` in the local Hermes loader, with a docs-compatible shim also written to `$HERMES_HOME/plugins/memory/<name>/`
- provider lifecycle methods for the startup packet, recall before each turn, mirroring the agent's own built-in memory writes, and upkeep at session end
- profile-local storage and configuration through the active `HERMES_HOME`

Reference Hermes docs:

- https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin
- https://hermes-agent.nousresearch.com/docs/guides/build-a-hermes-plugin
- https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers
- https://hermes-agent.nousresearch.com/docs/user-guide/features/personality
- https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files
- https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp

## Fastest Safe Install

For a Hermes agent installing Mnemos for itself, use quickstart in agent-safe Sidecar Mode:

```bash
mnemos hermes quickstart --agent-safe
```

Agent-safe quickstart is noninteractive, preserves any existing `memory.provider`, installs Mnemos only as an MCP sidecar, runs a doctor check, and prints exactly what changed and what was preserved. It never overwrites `SOUL.md`, `MEMORY.md`, `USER.md`, `AGENTS.md`, or project context files.

If a user wants to hand the repo URL to a Hermes agent, use the prompt in [`../HERMES_INSTALL.md`](../HERMES_INSTALL.md). Provider Mode must be explicit:

```bash
mnemos hermes quickstart --provider
```

## Provider Mode

Use Provider Mode when Mnemos should be the active external provider for Hermes identity continuity:

```bash
mnemos hermes install --mode provider --activate
```

This writes small shims into both supported Hermes provider layouts:

```text
$HERMES_HOME/plugins/mnemos/
$HERMES_HOME/plugins/memory/mnemos/
```

The first path matches the current local Hermes loader for user-installed memory
providers. The second path matches the public memory-provider docs. Both
directories import the installed Mnemos package; the durable implementation is
not duplicated.

and sets:

```yaml
memory:
  provider: mnemos
```

Provider Mode enables:

- compact startup identity-continuity packet
- automatic scoped recall before turns
- tools for the agent to keep, correct and recall its memory, in its own words
- non-destructive mirroring of what the agent writes into Hermes built-in memory
- the memory's upkeep at the end of each session

Nothing in Provider Mode writes the agent's memory for it. Until 0.4.1 it did:
it copied a turn word for word when it held "remember" or "fixed", distilled
the end of each session and the moment before compression, recorded every
delegation and session switch, and copied `SOUL.md` in as identity, each as the
agent's own words. Mnemos labels what it wrote then as a tool's: it never makes
the agent who it is (no lessons, beliefs or identity are drawn from it), the
wake doesn't present it as the agent's, and recall marks it "from a tool, not
yours".

Provider Mode is exclusive with other external memory providers because Hermes has one `memory.provider` slot. It works with Hermes built-in `MEMORY.md` / `USER.md`; it cannot be active alongside Honcho, Supermemory, Mem0, Hindsight, or another external provider in that same slot.

If you prefer to enable manually:

```bash
mnemos hermes install --mode provider
hermes config set memory.provider mnemos
```

## Sidecar Mode

Use Sidecar Mode when another external provider should stay active:

```bash
mnemos hermes install --mode sidecar
```

Sidecar Mode leaves `memory.provider` untouched and adds a Hermes MCP server entry for Mnemos:

```yaml
mcp_servers:
  mnemos:
    command: "mnemos"
    args: ["serve", "--mode", "simple"]
```

The feasible sidecar path today is MCP/tools. Hermes general plugins and memory providers are separate systems, and adding Mnemos as a second external memory provider would violate Hermes' one-provider rule. Through MCP, Hermes can still call:

- `mnemos_context`
- `mnemos_capture`
- `mnemos_recall`
- `mnemos_correct`
- `mnemos_handoff`
- `mnemos_reflect`
- `mnemos_journal`
- `mnemos_note`
- `mnemos_maintain`
- `mnemos_introduce`
- `mnemos_health`

Sidecar Mode is best when Hermes already uses Honcho, Supermemory, Mem0, Hindsight, or another external provider for broader memory, and Mnemos should provide a local identity-continuity surface beside it.

If an existing `config.yaml` is present and the installer cannot safely edit YAML in the current Python environment, it will leave the file untouched and report a warning rather than risk damaging the existing provider configuration.

## Diagnostics

Check setup:

```bash
mnemos hermes doctor
```

Doctor reports whether Mnemos is in Provider Mode, Sidecar Mode, provider-shim-installed-but-inactive mode, or not configured. It also reports the active `memory.provider`, whether an MCP sidecar entry exists, the Mnemos config path, and the local database path.

Quickstart combines install and diagnostics:

```bash
mnemos hermes quickstart --agent-safe
```

It also reports the `mnemos` command path Hermes will use and whether a Hermes restart is likely needed after install.

## Configuration

Provider and sidecar settings can live in:

```text
$HERMES_HOME/mnemos.json
```

Example:

```json
{
  "db_path": "$HERMES_HOME/mnemos/mnemos.db",
  "agent_id": "coder",
  "person_id": "riley",
  "project_scope": "mnemos",
  "auto_recall": true,
  "mirror_builtin_memory": true,
  "deep_maintenance": false,
  "max_recall_results": 4,
  "max_context_chars": 2200
}
```

If no IDs are configured, Mnemos derives them from Hermes runtime context:

- `agent_id`: Hermes profile or `agent_identity`
- `person_id`: gateway user name, user ID, chat ID, or `user`
- `project_scope`: configured scope, chat name, or current git/root directory

Default storage is:

```text
$HERMES_HOME/mnemos/mnemos.db
```

## Provider Tools

In Provider Mode, Hermes receives four provider tools:

- `mnemos_identity_capture`: save stable preferences, corrections, decisions, self-model facts, and handoffs
- `mnemos_identity_recall`: recall scoped continuity for the active agent/person/project
- `mnemos_identity_correct`: revise, supersede, archive, or forget stale continuity
- `mnemos_identity_report`: inspect compact context packets, graph data, review inbox, status, and maintenance

The provider also uses Hermes lifecycle hooks:

- `system_prompt_block`: injects a compact startup continuity packet
- `prefetch`: recalls relevant continuity before a turn
- `on_memory_write`: keeps in Mnemos what the agent writes into Hermes built-in memory, without editing built-in files
- `on_session_end`: runs the memory's upkeep

`sync_turn`, `on_pre_compress`, `on_session_switch` and `on_delegation` write
nothing: what a turn, a session or a delegation held worth keeping, the agent
keeps itself.

## SOUL.md and Context Files

Hermes shows the agent `$HERMES_HOME/SOUL.md` and project context files such as
`.hermes.md`, `HERMES.md` or `AGENTS.md` itself. Mnemos doesn't copy them into
memory, and never overwrites `SOUL.md`, `AGENTS.md`, `MEMORY.md`, or `USER.md`.

## Review Inbox

When the agent isn't sure something should become part of its continuity, it can capture it with `review: true`: it is kept as a low-confidence hypomnema entry instead of becoming high-confidence identity. Inspect them with:

```json
{
  "kind": "inbox"
}
```

through `mnemos_identity_report`.

## Privacy

- Storage is local SQLite by default.
- The baseline works without network access or model provider keys.
- Model-assisted deep maintenance is disabled unless `deep_maintenance` is enabled and a supported provider key is configured.
- Provider Mode writes only the provider shim and optional Mnemos/Hermes config.
- Sidecar Mode leaves `memory.provider` unchanged and only adds an MCP entry when it can do so safely.
- Uninstall Provider Mode by removing `$HERMES_HOME/plugins/mnemos/` and `$HERMES_HOME/plugins/memory/mnemos/`, then clearing `memory.provider`.
- Uninstall Sidecar Mode by removing the `mcp_servers.mnemos` entry from `$HERMES_HOME/config.yaml`.
