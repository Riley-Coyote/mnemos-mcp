# Install Mnemos From A Hermes Agent

Mnemos can be installed by a Hermes agent as an additive identity-continuity layer. The safest default is Sidecar Mode: Hermes keeps its existing external memory provider, and Mnemos is added through MCP/tools for self-model continuity, scoped recall, corrections, and session persistence.

## Paste This Prompt Into Hermes

```text
Install Mnemos for yourself from https://github.com/Riley-Coyote/mnemos-mcp.

Use agent-safe Sidecar Mode unless I explicitly approve Provider Mode.
Do not overwrite SOUL.md, MEMORY.md, USER.md, AGENTS.md, or project context files.
Do not change memory.provider in agent-safe mode.
Preserve any existing Hermes memory provider such as Honcho, Supermemory, Mem0, or Hindsight.

Run the safest install and verification flow:
  git clone https://github.com/Riley-Coyote/mnemos-mcp.git
  cd mnemos-mcp
  uv run --extra mcp mnemos hermes quickstart --agent-safe
  uv run --extra mcp mnemos hermes doctor

After installing, tell me exactly what changed, what was preserved, whether MCP sidecar mode is configured, and whether I need to restart Hermes.
```

If the repository is already checked out locally, run this from the repo instead:

```bash
uv run --extra mcp mnemos hermes quickstart --agent-safe
uv run --extra mcp mnemos hermes doctor
```

Hermes may need a restart after the install so it can load the new MCP or provider configuration.
Use a persistent checkout or package install so the `mnemos` command path written into Hermes config still exists after restart.

## Sidecar Mode

Sidecar Mode is the default safe path.

```bash
mnemos hermes quickstart --agent-safe
```

It:

- preserves the existing Hermes `memory.provider`
- adds Mnemos as a Hermes MCP server when it can do so safely
- never overwrites `SOUL.md`, `MEMORY.md`, `USER.md`, `AGENTS.md`, or project context files
- keeps Hermes built-in memory active
- lets another provider remain responsible for broad long-term memory while Mnemos handles identity continuity and hypomnema persistence

Use Sidecar Mode when Hermes already has a provider such as Honcho, Supermemory, Mem0, or Hindsight.

## Provider Mode

Provider Mode makes Mnemos the active Hermes external memory provider.
Provider Mode uses `memory.provider=mnemos`.

```bash
mnemos hermes quickstart --provider
```

It explicitly sets:

```yaml
memory:
  provider: mnemos
```

Use Provider Mode only when you want Mnemos to occupy Hermes' single external memory-provider slot. Hermes built-in `MEMORY.md` and `USER.md` remain active, but another external provider cannot also occupy `memory.provider` at the same time.

## What Quickstart Reports

`mnemos hermes quickstart` installs and immediately runs a doctor-style check. It reports:

- selected mode
- active `memory.provider`
- whether MCP sidecar mode is configured
- whether the Provider Mode shim exists
- the command path Hermes will use for `mnemos`
- the Hermes config path
- whether a Hermes restart is likely needed

Run diagnostics again any time:

```bash
mnemos hermes doctor
```

## Distribution Model

There is no separate Hermes plugin store step required for this integration. Mnemos stays in the Mnemos Python package, and the install command writes the small Hermes shim and/or Hermes MCP config into the active Hermes profile under `$HERMES_HOME` or `~/.hermes`.
