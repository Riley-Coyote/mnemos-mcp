# Mnemos Setup

This guide covers the production path: connect the MCP, get continuity, and
only opt into advanced infrastructure when you actually need it.

Mnemos is a continuity and identity layer for the agent itself — it carries
what the agent should know about *you and how you work together* across
sessions. It is not a general memory or retrieval system, and it is designed to
run alongside whatever you already use for that.

---

## 1. Install

From a local checkout:

```bash
pip install -e ".[mcp]"
```

When published:

```bash
pipx install "mnemos-continuity[mcp]"
```

The distribution package is `mnemos-continuity`. The Python import package and CLI
command are still `mnemos`.

On a Mac, install it outside `~/Documents`, `~/Desktop` and `~/Downloads`, and
keep a checkout installed in place out of them too. macOS doesn't let background
jobs read those folders, so the upkeep and quiet hours setup schedules would fail
there on every run. Setup warns when it finds this.

---

## 2. Check Readiness

```bash
mnemos doctor
```

Doctor will:

1. Resolve agent/person/project scope.
2. Create local SQLite storage if needed.
3. Run local deterministic maintenance.
4. Print the simple MCP tool list.
5. Show whether a dedicated model provider is configured.

No OpenRouter key is required for baseline continuity.

---

## 3. Connect an MCP Client

### Claude Code

```bash
mnemos mcp install claude-code --write
```

This runs Claude Code's own `claude mcp add`. Then go on to step 4, which
finishes setup for Claude Code.

### Claude Desktop

```bash
mnemos mcp install claude --write
```

Then restart Claude Desktop. For Claude Desktop this is all of setup: it also
schedules upkeep between sessions and asks about quiet hours (step 6).
`--no-upkeep` leaves the upkeep out.

To preview the config without writing:

```bash
mnemos mcp install claude
```

### Codex

```bash
mnemos mcp install codex
```

Run the printed `codex mcp add ...` command, then restart the Codex session.

### Cursor or Generic Clients

```bash
mnemos mcp install cursor
mnemos mcp install generic
```

Paste the printed JSON into the client's MCP config.

---

## 4. Make Continuity Automatic

Connecting the MCP gives the agent memory tools. Two mechanisms make sure it
actually uses them, so nothing has to be triggered by hand.

**Server instructions** ship with the MCP server and need no setup. Every MCP
client passes them to its agent: load context at session start, capture durable
things as they come up, correct rather than contradict.

**Session-start injection** is stronger, because it removes the tool call
entirely. On Claude Code:

```bash
mnemos hooks install --write
```

Memory is then injected before the agent's first turn. Preview it first with
`mnemos hooks install` (no `--write`).

The hook fails silent by design: empty, unreadable, or missing memory
contributes nothing and the session starts normally.

That one command turns on everything setup turns on for Claude Code:

- **The wake:** memory before the first turn, and again after compaction.
- **The cue:** each message you send brings up to three memories that may bear
  on it, or nothing. Messages Claude Code writes itself, such as a background
  task's notice, bring nothing.
- **Upkeep between sessions,** scheduled with your system's scheduler (step 6).
- **Quiet hours, if you say yes.** It asks once, and yes is the default: up
  to an hour a day that's the agent's own, and half an hour for the day's
  work. They run your own Claude Code on its own, on your Claude plan, so what
  the agent thinks over in them goes to Anthropic
  ([what, and how](docs/privacy-security.md#quiet-hours)). Run without a
  terminal, or with no `claude` command, it leaves them off and prints how to
  turn them on.

To turn each off:

```bash
mnemos hooks install --no-prompt --write    # the cue
mnemos daemon uninstall --write             # upkeep, and the quiet hours with it
mnemos daemon uninstall --hours --write     # only the quiet hours
```

To set up without scheduling upkeep at all: `mnemos hooks install --no-upkeep --write`.

On Codex, `mnemos hooks install codex --write` installs the wake and schedules
upkeep. Open `/hooks` in Codex to review the new hook.

---

## 5. Simple Mode

Simple mode is the default:

```bash
mnemos serve
```

It exposes only:

- `mnemos_context`
- `mnemos_handoff`
- `mnemos_capture`
- `mnemos_recall`
- `mnemos_correct`
- `mnemos_maintain`
- `mnemos_reflect`
- `mnemos_introduce`
- `mnemos_health`
- `mnemos_journal`
- `mnemos_note`

The user does not need to set up a database, choose tags, pass agent IDs, learn
engram/hypomnema terminology, configure OpenClaw, or supply a model key.

Optional visual-capable clients can ask `mnemos_context` for an identity graph:

```json
{
  "include_graph": true,
  "graph_max_nodes": 18
}
```

Mnemos still returns the normal continuity packet, plus an SVG image artifact
and structured graph data when the client can display it.

Optional scope:

```bash
mnemos serve --agent-id nova --person-id alex --project-scope mnemos
```

or:

```bash
MNEMOS_AGENT_ID=nova MNEMOS_PERSON_ID=alex MNEMOS_PROJECT_SCOPE=mnemos mnemos serve
```

---

## 6. Maintenance and Models

Mnemos maintenance has three levels:

1. **Local baseline**: always available. Runs decay, connection discovery,
   bookkeeping, promotion checks, correction handling, and reconsolidation
   updates with no provider key.
2. **Client-assisted**: future MCP sampling path for in-band model help during
   active tool calls when the client supports it.
3. **Dedicated background**: optional provider keys for richer deep maintenance
   and autonomous background work.

Dedicated provider example:

```bash
MNEMOS_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
MNEMOS_MODEL=anthropic/claude-sonnet-4-5
```

Deep maintenance can then be requested with:

```bash
mnemos_maintain(deep=true)
```

or from the CLI:

```bash
mnemos consolidate --deep
```

### Upkeep Between Sessions

Setup schedules upkeep with your system's scheduler (step 4, or step 3 for
Claude Desktop), so maintenance happens between sessions rather than only
while one is open: every 4 hours memories fade a little with time and related
ones are linked, and a deeper pass runs each night at 03:00. With no model
chosen for Mnemos, these are local passes only, and nothing leaves your
machine. By hand:

```bash
mnemos daemon install --write     # launchd, systemd, or crontab
mnemos daemon status
mnemos daemon uninstall --write   # off
```

`mnemos daemon install` with no `--write` prints exactly what it would
schedule. This requires no external agent runner. `mnemos doctor` reports
whether upkeep and the quiet hours are scheduled.

### Quiet Hours

Up to an hour a day that's the agent's own (08:00), and half an hour for the
day's work (19:00, skipped on a day with no work). Each runs your own Claude
Code on its own, with the agent's memory, on your Claude plan, so what the
agent thinks over in it goes to Anthropic: its words for the hour, short
excerpts of its recent memory, its wake, and whatever it reads or recalls
([more](docs/privacy-security.md#quiet-hours)). Setup asks about them once;
to schedule them yourself, or change their times:

```bash
mnemos daemon install --hours --write
mnemos daemon install --hours --mine-at 07:30 --ours-at 21:00 --write
mnemos daemon uninstall --hours --write     # off; upkeep stays
```

They need the `claude` command. Its location, and Mnemos's, are written into
the jobs when you install them, because a background job doesn't get your
shell's PATH.

---

## 7. Advanced Mode

Use advanced mode for debugging, migration, research, or direct control:

```bash
mnemos serve --mode advanced
```

Advanced mode is simple mode, unchanged, plus tools for inspecting and
administering memory: explicit remember and ingest, functional memory and
hypomnema management, beliefs, shared memory, inspect, forget, and explicit
consolidation. It's less tested than simple mode, and says so when it starts.

Forge and full agent workspaces are advanced integrations, not part of the
baseline setup.

To bootstrap a full workspace:

```bash
mnemos bootstrap --agent-name Nova --workspace ~/nova --user-name Alex
```

### OpenClaw (optional)

Background memory maintenance does **not** require OpenClaw — use `mnemos
daemon install` (section 5), which schedules it with launchd, systemd, or
crontab.

OpenClaw adds a different class of job: agent-mediated work that needs a model
and OpenClaw's session APIs, such as the observer context sync, `MEMORY.md`
upkeep, morning briefs, and daily debriefs.

```bash
mnemos setup-openclaw --agent main --dry-run
```

Review generated commands before enabling them.

---

## 8. Safety and Release Notes

- Privacy boundaries: [docs/privacy-security.md](docs/privacy-security.md)
- Release checklist: [docs/release-hardening.md](docs/release-hardening.md)

---

## 9. Troubleshooting

### The MCP client does not show Mnemos tools

1. Run `mnemos doctor`.
2. Confirm the client config points to `mnemos serve`.
3. Restart the client session or desktop app.
4. For simple mode, expect exactly eleven tools.
5. For advanced mode, use `mnemos serve --mode advanced`, and expect those
   eleven tools plus its own.

### The agent has no prior memory

That is normal on first run. The first `mnemos_context` creates storage and
returns an empty continuity packet. Use `mnemos_capture` to store preferences,
decisions, project state, and corrections.

### Deep maintenance says it used local maintenance

No dedicated provider is configured. Baseline continuity still works. Add a
provider key only if you want richer model-mediated maintenance or background
work.

### Scheduled jobs fail on a Mac, though the same command works by hand

Mnemos is probably installed under `~/Documents`, `~/Desktop` or
`~/Downloads`, which background jobs can't read; setup and
`mnemos daemon install` print a warning when it is. Install it from PyPI
(`pipx install "mnemos-continuity[mcp,embeddings]"`) or from a built wheel,
then run setup again. Each job's log is in `~/.mnemos/logs`.

### Multiple agents share a machine

Give each agent a scope:

```bash
MNEMOS_AGENT_ID=nova mnemos serve
MNEMOS_AGENT_ID=vektor mnemos serve
```

or separate DBs:

```bash
mnemos serve --agent-id nova --db-path ~/.mnemos/nova.db
mnemos serve --agent-id vektor --db-path ~/.mnemos/vektor.db
```
