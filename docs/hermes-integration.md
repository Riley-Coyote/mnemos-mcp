# Mnemos Hermes Integration

Mnemos for Hermes is a complementary identity-continuity layer. It gives Hermes agents durable self-model continuity, scoped corrections, hypomnema persistence, session handoffs, startup context, and continuity reports without replacing Hermes built-in `MEMORY.md` / `USER.md`.

Hermes built-in memory is always active. Hermes also supports one active external memory provider in `memory.provider`, so Mnemos has two supported modes:

- Provider Mode: `memory.provider=mnemos`; through Hermes's memory-provider hooks the agent wakes with its memory and gets what bears on each message before the turn, and it writes its memory itself, with the tools every agent has, by the same names.
- Sidecar Mode: `memory.provider` is left unchanged; the agent has the tools through an MCP server, with no wake and no recall on each message, for users already running Honcho, Supermemory, Mem0, Hindsight, or another external provider.

The implementation follows the current Hermes memory-provider contract:

- one external provider selected through `memory.provider`
- built-in memory remains active alongside the selected external provider
- user-installed providers discovered from `$HERMES_HOME/plugins/<name>/` in the local Hermes loader, with a docs-compatible shim also written to `$HERMES_HOME/plugins/memory/<name>/`
- provider lifecycle methods for the startup packet, recall before each turn, mirroring the agent's own built-in memory writes, and upkeep at session end
- configuration through the active `HERMES_HOME`, and each profile an agent of its own (see [Profiles](#profiles))

Reference Hermes docs:

- https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin
- https://hermes-agent.nousresearch.com/docs/guides/build-a-hermes-plugin
- https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers
- https://hermes-agent.nousresearch.com/docs/user-guide/features/personality
- https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files
- https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp

## Connect

```bash
mnemos connect hermes --write
```

This makes Mnemos Hermes' memory provider when the slot is free. When another provider holds it, connect leaves that provider alone and adds the tools alone, through an MCP server. It says what it will do first if you leave off `--write`. Restart Hermes afterwards.

For a Hermes agent installing Mnemos for itself, agent-safe quickstart never touches `memory.provider`:

```bash
mnemos hermes quickstart --agent-safe
```

It is noninteractive, installs Mnemos only as an MCP sidecar (or does nothing if Mnemos already holds the slot), runs a doctor check, and prints exactly what changed and what was preserved. It never overwrites `SOUL.md`, `MEMORY.md`, `USER.md`, `AGENTS.md`, or project context files. To hand the repo URL to a Hermes agent, use the prompt in [`../HERMES_INSTALL.md`](../HERMES_INSTALL.md).

## Provider Mode

Use Provider Mode when Mnemos should be the active external provider for Hermes identity continuity. `mnemos connect hermes --write` sets it up, as does:

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
- the tools every agent has, by the same names, for the agent to keep, correct and recall its memory in its own words
- non-destructive mirroring of what the agent writes into Hermes built-in memory
- the memory's upkeep at the end of each session
- room for many conversations: each holds a few open files, more with meaning search, so the provider asks for up to 4096 where Hermes hasn't (a Mac starts a process with 256)

Nothing in Provider Mode writes the agent's memory for it. Until 0.4.1 it did:
it copied a turn word for word when it held "remember" or "fixed", distilled
the end of each session and the moment before compression, recorded every
delegation and session switch, and copied `SOUL.md` in as identity, each as the
agent's own words. Mnemos labels what it wrote then as a tool's: it never makes
the agent who it is (no lessons, beliefs or identity are drawn from it), the
wake doesn't present it as the agent's, and recall marks it "from a tool, not
yours".

Provider Mode is exclusive with other external memory providers because Hermes has one `memory.provider` slot. It works with Hermes built-in `MEMORY.md` / `USER.md`; it cannot be active alongside Honcho, Supermemory, Mem0, Hindsight, or another external provider in that same slot.

The provider carries the tools, so Provider Mode needs no MCP server. If an earlier setup left one that Mnemos wrote, connecting takes it out. One with settings of its own stays, and connect says so. If Hermes can't load Mnemos in its own Python, connect warns and keeps a server, since that's how the agent has its tools then.

If another provider holds the slot, `--activate` and `--provider` leave it and say so. To replace it on purpose, pass `mnemos hermes install --mode provider --activate --force`.

## Sidecar Mode

Use Sidecar Mode when another external provider should stay active:

```bash
mnemos hermes install --mode sidecar
```

Sidecar Mode leaves `memory.provider` untouched and adds a Hermes MCP server entry for Mnemos:

```yaml
mcp_servers:
  mnemos:
    command: "/path/to/mnemos"
    args: ["serve", "--mode", "simple", "--db-path", "~/.mnemos/hermes.db", "--agent-id", "hermes", "--person-id", "user", "--project-scope", "global"]
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

It keeps anything you've added to that entry, and a backup of the config as it found it. Asked for from Provider Mode (`mnemos hermes install --mode sidecar`), it's a clean switch on the same memory: it clears the provider and the gateway hook and adds the server.

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

A memory file that's damaged, or a provider and a server keeping two different memories, shows as not ready, and the doctor says which.

## Configuration

Provider and sidecar settings can live in:

```text
$HERMES_HOME/mnemos.json
```

Example:

```json
{
  "db_path": "~/.mnemos/hermes.db",
  "agent_id": "hermes",
  "person_id": "riley",
  "project_scope": "mnemos",
  "auto_recall": true,
  "mirror_builtin_memory": true,
  "deep_maintenance": false,
  "max_recall_results": 4,
  "max_context_chars": 2200
}
```

`mnemos connect hermes` and `mnemos hermes quickstart --provider` configure them, so the agent has one memory in every chat and for everyone in them. If no IDs are configured, as after a plain `mnemos hermes install --mode provider`, Mnemos derives them from Hermes runtime context, so each chat and each person has a memory of their own, and renaming a group starts a new one:

- `agent_id`: Hermes profile or `agent_identity`
- `person_id`: gateway user name, user ID, chat ID, or `user`
- `project_scope`: configured scope, chat name, or current git/root directory

Default storage is:

```text
$HERMES_HOME/mnemos/mnemos.db
```

Connecting replaces both with one memory in `~/.mnemos/`, where every agent's is. A store already at that path stays where it is if you set up with `quickstart` or `install`. `connect` starts this agent's own memory and tells you where the older one is.

## Profiles

Each Hermes profile is an agent of its own, with its own memory, as any two agents are. They share what any two agents share: the machine's shared memory, which an agent writes to with `shared: true` and every agent's recall reads.

| Hermes home | Agent | Memory |
|---|---|---|
| `~/.hermes` | `hermes` | `~/.mnemos/hermes.db` |
| `~/.hermes/profiles/work` | `hermes-work` | `~/.mnemos/hermes-work.db` |
| anywhere else | `hermes-<folder>-<a few letters of its path>` | `~/.mnemos/<agent>.db` |

Connect one at a time:

```bash
mnemos connect hermes --profile work --write
```

`mnemos.json` says which home it was written for, so a profile made with `hermes profile create --clone-all` is its own agent from its first turn, not a second door into the original's memory. A copy made before Mnemos 0.6.4 has nothing to say it's a copy: it stays on the memory it has, and `mnemos connect hermes` says so and gives the command that parts them. To have two profiles share a memory on purpose, name it: `--agent-id` and `--db-path`.

## Provider Tools

In Provider Mode, Hermes offers the agent the tools every agent has, by the same names, which are what its wake and its memory's own questions tell it to use: `mnemos_capture`, `mnemos_recall`, `mnemos_correct`, `mnemos_handoff`, `mnemos_reflect`, `mnemos_journal`, `mnemos_note`, `mnemos_maintain`, `mnemos_introduce`, `mnemos_health` and `mnemos_page`. There's no `mnemos_context`, because the provider has already woken it. Here `mnemos_handoff` keeps one note for each conversation. See [the guide](guide.md) for what each does.

The model Hermes names signs what's written, where Hermes passes it (Hermes from after September 2026), and `signed_as` overrides it. Hermes from before that passes no model, so the agent signs for itself, as it's asked to.

The provider also uses Hermes lifecycle hooks:

- `system_prompt_block`: injects a compact startup continuity packet
- `prefetch`: recalls relevant continuity before a turn
- `on_memory_write`: keeps in Mnemos what the agent writes into Hermes built-in memory, without editing built-in files
- `on_session_end`: runs the memory's upkeep

`sync_turn`, `on_pre_compress`, `on_session_switch` and `on_delegation` write
nothing: what a turn, a session or a delegation held worth keeping, the agent
keeps itself.

## Quiet Hours

`mnemos connect hermes --hours --write` puts three jobs in Hermes' own scheduler. Hermes from after September 2026 gives a job its memory provider, and so its tools. Hermes from before that runs a job without it, so the job's words give it the same tools through its shell: `mnemos hermes tool mnemos_capture <<'EOF'` and then the arguments as JSON. Connecting again gives jobs from an older Mnemos the newer words.

## SOUL.md and Context Files

Hermes shows the agent `$HERMES_HOME/SOUL.md` and project context files such as
`.hermes.md`, `HERMES.md` or `AGENTS.md` itself. Mnemos doesn't copy them into
memory, and never overwrites `SOUL.md`, `AGENTS.md`, `MEMORY.md`, or `USER.md`.

## Privacy

- Storage is local SQLite by default.
- The baseline works without network access or model provider keys.
- Model-assisted deep maintenance is disabled unless `deep_maintenance` is enabled and a supported provider key is configured.
- Provider Mode writes the provider shim, a small gateway hook that loads it, and Mnemos/Hermes config.
- Sidecar Mode leaves `memory.provider` unchanged and only adds an MCP entry when it can do so safely.
- `mnemos uninstall --write` takes Mnemos out of Hermes, in every profile: the provider, the server, the plugin and the hook. It leaves anything that isn't Mnemos's, the memories, and `mnemos.json`, which is how connecting again finds them.
