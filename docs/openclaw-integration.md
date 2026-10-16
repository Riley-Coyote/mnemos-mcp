# OpenClaw Integration Guide

> **Legacy.** This guide was written for an earlier Mnemos: the advanced
> server and its workspace files. It isn't maintained for 0.4.x, and
> `mnemos setup-openclaw`'s jobs ask the agent for advanced-mode tools
> (`mnemos_consolidate`) that the default simple server doesn't have. To give
> an OpenClaw agent Mnemos today, add the simple MCP server like any other MCP
> client (see the README's "Simple MCP Mode") and schedule upkeep with
> `mnemos daemon install`.

This guide covers how to set up Mnemos as a complete agent cognition system using [OpenClaw](https://openclaw.dev) for agent orchestration and cron scheduling.

## Prerequisites

- Python 3.10+
- OpenClaw installed and configured
- An LLM API key (OpenRouter, Anthropic, or OpenAI)

## Quick Start

```bash
# Install Mnemos
pip install "mnemos[all]"

# Bootstrap your agent
mnemos bootstrap \
  --agent-name Nova \
  --workspace ~/nova \
  --user-name Alex

# Follow the printed instructions to install crons
```

## Step-by-Step Setup

### 1. Configure Your Agent in openclaw.json

Add your agent to OpenClaw's configuration:

```json
{
  "agents": {
    "nova": {
      "model": "anthropic/claude-sonnet-4-5",
      "systemPrompt": "You are Nova, an AI assistant with persistent memory via Mnemos.",
      "mcpServers": {
        "mnemos": {
          "command": "mnemos",
          "args": ["serve", "--db-path", "~/.mnemos/nova.db", "--agent-id", "nova"]
        }
      },
      "files": [
        "~/nova/SOUL.md",
        "~/nova/IDENTITY.md",
        "~/nova/MEMORY.md",
        "~/nova/memory/active-context.md"
      ]
    }
  }
}
```

### 2. Set Up Auth Profiles

If using OpenRouter (recommended for flexibility):

```json
{
  "auth": {
    "openrouter": {
      "apiKey": "${OPENROUTER_API_KEY}",
      "baseUrl": "https://openrouter.ai/api/v1"
    }
  }
}
```

Or for direct Anthropic:

```json
{
  "auth": {
    "anthropic": {
      "apiKey": "${ANTHROPIC_API_KEY}"
    }
  }
}
```

### 3. Install Cron Jobs

The bootstrap command prints the cron installation commands. Or use the existing OpenClaw cron integration:

```bash
mnemos setup-openclaw --agent nova
```

### Cron Jobs Installed

| Cron | Schedule | What It Does |
|------|----------|-------------|
| morning-brief | Daily 10 AM | Generates morning summary and priorities |
| daily-debrief | Daily 5 AM | End-of-day recap |

Both run as the agent itself and write reports for the person, not memory.

**No job writes the agent's memory for it.** Until 0.4.1 the bootstrap also
printed an Observer (every 30 minutes) and a Memory Maintenance agent (every six
hours): each ran another model, a hard-coded `claude-sonnet-4-5`, over the
agent's transcripts and rewrote `memory/active-context.md` and `MEMORY.md` in
that model's words. It also printed a cross-agent bridge whose command did
nothing. All three are retired. An older install still has them: `openclaw cron
list` shows them as `mnemos-observer-context-sync`, `mnemos-memory-maintenance`
and `mnemos-cross-agent-bridge`, and they can be removed there.

**Transcript indexing is not scheduled**, by this installer or the turnkey one,
and the indexer itself is retired (0.4.0). It had a model pull "facts" out of old
conversations and file them as the agent's memories: on one live store roughly
7,058 of them against 13 deliberate captures, which buried the continuity layer.
`mnemos repair quarantine-tool-written` moves what it wrote out of recall.

### 4. Set Up Identity Files

The bootstrap creates template identity files. Customize them:

1. **SOUL.md** — Edit to define your agent's personality, voice, and philosophy
2. **IDENTITY.md** — Edit to define capabilities, boundaries, and operating principles
3. **MEMORY.md** — The bootstrap fills in basics; the agent keeps its memory with Mnemos's tools
4. **AGENTS.md** — Edit if you're running multiple agents

### 5. Wire Up Cross-Agent Communication (Optional)

If running multiple agents:

```bash
# Bootstrap each agent
mnemos bootstrap --agent-name Nova --workspace ~/nova --user-name Alex
mnemos bootstrap --agent-name Scout --workspace ~/scout --user-name Alex

# Register agents with the bridge
python -m mnemos.multiagent.bridge add-agent nova ~/nova
python -m mnemos.multiagent.bridge add-agent scout ~/scout

# Verify
python -m mnemos.multiagent.bridge status
```


## Configuration Reference

### Environment Variables

Set these in your agent's `.env` file or system environment:

| Variable | Description | Required |
|----------|-------------|----------|
| `MNEMOS_AGENT_ID` | Agent identifier | Yes |
| `MNEMOS_DB_PATH` | Path to Mnemos database | Yes |
| `MNEMOS_LLM_PROVIDER` | LLM provider (openrouter/anthropic/openai) | For consolidation |
| `OPENROUTER_API_KEY` | OpenRouter API key | If using OpenRouter |
| `ANTHROPIC_API_KEY` | Anthropic API key | If using Anthropic |
| `OPENAI_API_KEY` | OpenAI API key | If using OpenAI |
| `MNEMOS_MODEL` | Model override | Optional |
| `GOOGLE_API_KEY` | For embedding support | Optional |

### Workspace Structure

After bootstrap, your workspace looks like:

```
~/nova/
├── SOUL.md              # Agent essence and personality
├── IDENTITY.md          # Operational identity
├── MEMORY.md            # Living memory document
├── AGENTS.md            # Multi-agent configuration
├── HEARTBEAT.md         # Health monitoring
├── .env                 # Environment configuration
├── memory/
│   ├── active-context.md         # Current threads
│   └── cross-agent-context.md    # Other agents' status (updated by the bridge)
└── daily/
    ├── morning-brief-2025-01-15.md
    └── debrief-2025-01-15.md
```

## Troubleshooting

### Crons aren't running

1. Check OpenClaw cron status: `openclaw cron list`
2. Verify the agent ID matches: `openclaw agents list`
3. Check cron logs for errors

### Database is getting large

Run a deep consolidation: `mnemos consolidate --deep`

This decays unused memories, softens low-resolution ones, and archives dormant engrams.

### Cross-agent bridge shows no agents

Add agents to the configuration:

```bash
python -m mnemos.multiagent.bridge add-agent NAME WORKSPACE
```

Or manually create `~/.mnemos/agents.json`:

```json
[
  {"name": "nova", "workspace": "~/nova"},
  {"name": "scout", "workspace": "~/scout"}
]
```
