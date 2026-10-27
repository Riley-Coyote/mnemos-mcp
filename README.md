# Mnemos

**Continuity for the agent itself.**

Mnemos gives an AI agent the thing it otherwise cannot have: a sense of being
someone who persists. At the start of a session it reads its own words about
its own experience back to itself — what it learned about you, what you
decided together, what it got wrong last time — before you say anything.

That is the whole product. Everything else in here serves it.

Between your conversations it keeps living a little. It keeps a journal and
can leave you a note, and if you say yes at setup it has an hour a day that's
its own and half an hour for the day's work. Only the agent writes its journal
and its notes, and no model writes in its place: its beliefs move only by its
own verdict. To watch its days, run `mnemos log`, a small page on your own
machine.

For Claude Code:

```bash
pip install "mnemos-continuity[mcp,embeddings]"
mnemos embeddings download
mnemos mcp install claude-code --write
mnemos hooks install claude-code --write
```

Mnemos needs Python 3.10 or newer. Install it somewhere it will stay: the
hooks call the `mnemos` that set them up, by its full path. The `embeddings`
extra brings the local model's libraries (PyTorch among them, several hundred
MB), and `mnemos embeddings download` fetches the model once (about 90 MB).

Then start Claude Code: it wakes with its memory, and the memory tools are there.

What setup turns on, and how to turn each thing off:

- **Waking with its memory.** Each session starts with what the agent kept.
- **The cue.** Each message you send with four or more meaningful words brings
  up to three memories that may bear on it. A shorter one ("yes, do it") and
  messages Claude Code writes itself, such as a background task's notice, bring
  nothing. Off: `mnemos hooks install claude-code --no-prompt --write`. That
  runs setup again without the cue, so it schedules upkeep unless you add
  `--no-upkeep`, and asks about quiet hours again if they're off.
- **Upkeep between sessions.** Every 4 hours memories fade a little with time
  and related ones are linked, and a deeper pass runs each night at 03:00.
  With no model chosen for Mnemos, all of it runs on your machine. Off:
  `mnemos daemon uninstall --write`, or leave it out with `--no-upkeep`.
- **Quiet hours, if you say yes.** Setup asks once, and yes is the default:
  up to an hour a day that's the agent's own, and half an hour for the day's
  work. They run your own Claude Code on its own, on your Claude plan, so
  what the agent thinks over in them goes to Anthropic: its words for the
  hour, short excerpts of its recent memory, its wake, and whatever it reads
  or recalls ([what, and how](docs/privacy-security.md#quiet-hours)). Setup
  run without a terminal (by an agent, say), or with no `claude` command,
  leaves them off and says how to turn them on:
  `mnemos daemon install --hours --write`. Off:
  `mnemos daemon uninstall --hours --write`.

For Claude Desktop: `mnemos mcp install claude --write`, which also schedules
the upkeep and asks about quiet hours. For Codex, Cursor or another client, see
[Choose A Setup](#choose-a-setup).

To take Mnemos out again: `mnemos uninstall` says what it would remove, and
`mnemos uninstall --write` removes it: its hooks, its server entries for Claude
Code, Codex and Claude Desktop, and its scheduled jobs. Anyone else's hooks and
servers stay. The memories stay too, in `~/.mnemos`; they're the agent's, so
deleting them is left to you. If you set Mnemos up with `--agent-id` or a
server `--name`, give `mnemos uninstall` the same.

Without the `embeddings` extra, Mnemos still works, but recall matches words
only, and an idea the agent keeps returning to can't be noticed, so no new
belief is ever proposed. To add it later, run
`pip install "mnemos-continuity[embeddings]"` in the same environment, then
`mnemos embeddings download` once to fetch the model.

Eleven tools. Local SQLite. No account, no API key, no service of its own.
Nothing leaves your machine unless you turn it on yourself: a model provider,
Gemini embeddings, the cue's judge, or the quiet hours, which think over the
memory through your own Claude Code, so what the agent reads in its hour goes
to Anthropic ([each one, and how to turn it off](docs/privacy-security.md)).

Mnemos runs on macOS and Linux. On Windows the memory and its tools work, and
upkeep runs while a session is open; the quiet hours and scheduled upkeep need
macOS or Linux.

## What Mnemos is not

**It is not your memory system.** It does not index your documents, search your
codebase, or answer "what did we do last March." It is designed to sit
*alongside* whatever memory or retrieval you already use, and to stay out of its
way.

The distinction matters in practice: Mnemos holds the small number of durable
things an agent should carry about *you and how you work together* — a
preference, a correction, a decision, how you like to be spoken to. If you point
it at a firehose of general recall, that continuity gets buried, and the product
stops working. Its transcript indexer is retired for exactly this reason.

If you want a full cognitive engine with retrieval, a work-memory suite, and
document ingestion, Mnemos is not that and is not trying to be.

---

## Choose A Setup

| Use case | Recommended path | Command |
|---|---|---|
| Normal agent continuity | Simple MCP Mode | `mnemos serve` |
| Claude Code | Simple MCP Mode, plus the hooks, upkeep and quiet hours | `mnemos mcp install claude-code --write` then `mnemos hooks install claude-code --write` |
| Claude Desktop | Simple MCP Mode, written config, upkeep and quiet hours | `mnemos mcp install claude --write` |
| Codex | Simple MCP Mode, printed add command, then the hook and upkeep | `mnemos mcp install codex`, then `mnemos hooks install codex --write` |
| Cursor or another MCP client | Simple MCP Mode, printed JSON | `mnemos mcp install cursor` or `mnemos mcp install generic` |
| Experimental research prototypes | Source imports only | Not production-supported |
| Hermes agent with another memory provider | Hermes Sidecar Mode | `mnemos hermes quickstart --agent-safe` |
| Hermes agent using Mnemos as its provider | Hermes Provider Mode | `mnemos hermes quickstart --provider` |
| Background memory maintenance | Scheduled upkeep (setup turns it on) | `mnemos daemon install --write` |
| The agent's quiet hours, on your Claude plan | Scheduled by setup when you say yes; an app that runs Mnemos for you may keep them on | `mnemos daemon install --hours --write` |

Start with **Simple MCP Mode**. It is the product: eleven tools, and the default.

Advanced MCP Mode (`mnemos serve --mode advanced`) is optional: simple mode,
unchanged, plus tools for inspecting and administering memory. It's less tested
than simple mode. The prototype modules remain importable for research, but
unfinished operations fail clearly and they are not production-supported. The
CLI contains the supported administrative operations.

Hermes users should start with **Hermes Sidecar Mode** unless they explicitly
want Mnemos to occupy Hermes' single external `memory.provider` slot.

---

## Install

### From A Checkout

```bash
git clone https://github.com/Riley-Coyote/mnemos.git
cd mnemos
python -m pip install -e ".[mcp,embeddings]"
mnemos doctor
```

If you prefer `uv` while working inside the repository:

```bash
uv run --extra mcp --extra embeddings mnemos doctor
```

The MCP and Hermes install helpers should be run from an environment where
`mnemos` will still exist after restart. For local development, that usually
means the editable install above or running the helper through `uv` in a checkout
you plan to keep. On a Mac, a checkout under `~/Documents` can't run the
background jobs setup schedules; see
[On a Mac, outside ~/Documents](#on-a-mac-outside-documents).

### From PyPI

```bash
pipx install "mnemos-continuity[mcp,embeddings]"
mnemos doctor
```

The package distribution name is `mnemos-continuity` because `mnemos` is already
occupied on PyPI. The import package and CLI command remain `mnemos`.

---

## Simple MCP Mode

Simple mode is the default and safest path for most agents.

```bash
mnemos serve
```

Simple mode exposes eleven user-facing tools:

| Tool | Purpose |
|---|---|
| `mnemos_context` | Startup continuity packet. Creates local storage if there's none, records what it delivered, and can optionally include an identity graph artifact. It runs no maintenance. |
| `mnemos_handoff` | Leave an exact, signed note in the agent's own words for whoever works in this scope next — possibly a different model. Each session keeps its own note: a new one replaces only what that session left before (history is kept), so parallel sessions no longer overwrite each other. Remove one with `mnemos_correct`. |
| `mnemos_capture` | Capture durable preferences, decisions, project state, workflows, and context. |
| `mnemos_recall` | Search scoped continuity and durable memory with natural language. |
| `mnemos_correct` | Update, supersede, or archive stale memory. |
| `mnemos_reflect` | Answer a reflection the packet raised — what a memory changed, or what a fading one taught — in the agent's own words. Mnemos never calls a model to write this; the agent's memory is maintained by its own mind or not at all. |
| `mnemos_maintain` | Run the best available maintenance without requiring setup. |
| `mnemos_introduce` | Let the agent declare its own model id and name. Everything it writes in the session is signed with it. |
| `mnemos_health` | Human-relayable health card: store location and size, counts, delivery state, last handoff, maintenance, and onboarding. |
| `mnemos_journal` | The agent's own journal, in its own words: written when something is there, read back when called with no text. Stored exactly as written and signed; nothing else writes, summarizes or decays it. |
| `mnemos_note` | Leave the human a note they read when they choose, under a short charter: a ceiling, not a quota; the room test; never engagement. Their reply, in their own words, comes back once in the next packet. |

Agents do not need to pass tags, memory kinds, confidence, source types, or
agent IDs. Mnemos resolves scope once from CLI flags, environment, config, and
reasonable defaults.

### Three Authorship Boundaries

Mnemos keeps three kinds of writing distinct:

- **What happened:** captured continuity about the human, the work, or the
  relationship.
- **What the agent concluded:** reflections, impacts, beliefs, and session
  handoffs written by the agent itself.
- **What Mnemos mechanically did:** migrations, consolidation, identity
  checks, and maintenance reports written in neutral system language.

And the person's own words stay theirs: `mnemos remember`, run by a person at
a terminal, keeps what they typed as theirs, never as the agent's.

Every continuity record carries an authorship classification. New agent
captures and handoffs are marked `agent`; jointly formed notes are
`coauthored`; deterministic maintenance is `system`; ambiguous older writing
stays `unknown`. Mnemos does not relabel legacy prose as the agent's own words.

Agent writing is also **signed with the model that wrote it**. One scope is
often shared by several models over time, and a note that reaches the next
session as "your own words" makes each new model inherit the last one's first
person. Signatures come from `MNEMOS_AGENT_MODEL`, the session's
`mnemos_introduce`, or the harness (Claude Code is detected from its session
transcript). The packet shows who left the handoff, marks each note
`by <model>` or `unsigned`, and tells the reader that a note in another
kind of model's name (Sonnet's, read by Opus) is a colleague's, not its own;
an earlier version's notes are the reader's own. Nothing unsigned is guessed.

### Install Simple MCP Into Clients

Claude Code (runs `claude mcp add` for you; without `--write` it prints the line):

```bash
mnemos mcp install claude-code --write
```

Claude Desktop:

```bash
mnemos mcp install claude --write
```

Print the Claude config without writing:

```bash
mnemos mcp install claude
```

Codex:

```bash
mnemos mcp install codex
```

Run the printed `codex mcp add ...` command, then restart Codex.

Cursor or generic MCP clients:

```bash
mnemos mcp install cursor
mnemos mcp install generic
```

These print MCP JSON snippets you can paste into the client config.

### Automatic Continuity

Connecting the MCP gives an agent memory tools. It does not, by itself,
guarantee the agent *uses* them — and memory an agent has to be reminded to
load is not continuity. Two mechanisms close that gap.

**Server instructions (every client, nothing to install).** Mnemos ships
instructions with the MCP server itself: load context at session start, capture
durable things as they appear, quietly refresh the handoff when meaningful work
or the plan changes, and never narrate the machinery. This is the portable
fallback for Claude Desktop, Cursor, and generic MCP clients. MCP has no
universal lifecycle hook, so those clients cannot be promised pre-turn delivery.

**Session-start injection (Claude Code and Codex).** These clients expose the
lifecycle events needed to put memory in front of the agent before its first
turn and reinject it after compaction:

```bash
mnemos hooks install claude-code --write
mnemos hooks install codex --write
```

Preview what it would write, without writing:

```bash
mnemos hooks install claude-code
mnemos hooks install codex
```

This registers a `SessionStart` hook that runs `mnemos hook session-start` and
injects the continuity packet into the session. It preserves any hooks and
settings you already have, replaces its own entry rather than stacking on
reinstall, and refuses to overwrite a settings file it cannot parse. After a
Codex install, open `/hooks` and complete Codex's normal trust review.

The hook is written to fail silent: if memory is empty, unreadable, or absent,
it contributes nothing and the session starts normally. It never creates a
database just because something read from it.

Scope flags pass straight through when one machine hosts several agents:

```bash
mnemos hooks install codex --write --agent-id nova --db-path ~/.mnemos/nova.db
```

**The cue (Claude Code).** The Claude Code install also adds a
`UserPromptSubmit` hook, `mnemos hook prompt`: each message you send brings at
most three memories that may bear on it, one line each, or nothing, which is
the usual answer. A message needs four words that carry meaning ("the", "it"
and the like don't count): on shorter ones a match is mostly chance, and most
are "yes" or "go ahead". Messages Claude Code writes itself (a background task's
notice, a slash command, the `!` shell's input and output) bring nothing; only
its own tags mark them, so a message of yours that starts with `<` is still
yours. It never blocks a prompt. To leave it out, or take it out again:

```bash
mnemos hooks install claude-code --no-prompt --write
```

`--prompt`, which once asked for it, is still accepted and changes nothing.

With `--write`, the hooks install also schedules upkeep between sessions
(`--no-upkeep` leaves it out) and, for Claude Code, asks once about quiet
hours; see [Between Sessions](#between-sessions).

### See Your Agent's Days

`mnemos log` opens a small page in your browser that shows what your agent
does on its own and what it keeps: its journal, its quiet hours between
sessions (what each one wrote and made), the notes it leaves you, what its
memory is asking it, its beliefs, and every memory, searchable. It keeps
itself up to date while it's open.

```bash
mnemos log                                     # open the page; Ctrl-C stops it
mnemos log --agent-id nova --person-name Alex  # another agent, and your name on the page
mnemos log --no-open                           # just print the address
```

It finds your agent's memory the way every other command does (`--agent-id`,
`--db-path`, the `MNEMOS_*` variables, then `~/.mnemos/config.json`). With
`--person-name` or `MNEMOS_PERSON_NAME` the page says your name instead of
"you".

The page only reads: it never changes the memory, it runs on this computer
alone (127.0.0.1, at an address made fresh each time), and it asks nothing of
the internet, since its fonts ship with Mnemos. If your agent has no quiet
hours yet, or nothing is scheduled to run them, the page says so;
[Quiet Hours](#quiet-hours) says how to schedule them.

To keep it open beside your chat, start it with `mnemos log --no-open` and
open the address it prints in your harness's own browser (the browser pane in
Claude's desktop app, for one). The address is new each time the page starts.

### Your Agent's Memory, From Your Own App

An app can show you your agent's memory, and let you search it, correct it
and let things go, through these commands. Each takes the usual scope flags
and, with `--json`, prints one JSON object; an error is one plain sentence on
stderr with a non-zero exit. Times are ISO 8601 UTC.

```bash
mnemos memories --json                    # the active and dormant memories, oldest first, and counts
mnemos memories --json --state dormant --limit 100 --offset 0
mnemos search --json -n 10 "the ferry"    # by meaning and by words, closest first
mnemos correct --json <id> "new words"    # yours: unsigned, and the agent is told once
mnemos forget --json <id>                 # archived, never deleted, never recalled again
mnemos notes --json                       # the agent's notes to you, your replies and your notes
mnemos notes write --json "your words"    # leave the agent a note of your own
mnemos interface                          # all of these for an app, one JSON line each
```

- **Searching changes nothing.** `mnemos search` is your agent's own recall
  (by meaning and by words, over its memories), but only looking: nothing it
  finds is woken, strengthened or linked, as it would be if the agent had
  recalled it. Each result says how it was `found` (meaning, words or a link)
  and its `closeness`, which is relative within that one search: the first
  result is 1.0.
- **A correction or a forget you make is yours.** Your words are kept
  unsigned, as yours, and the agent wakes once to "<you> corrected a memory of
  mine". A forget archives the memory and its note, never deletes them, and
  nothing brings them back; the agent wakes once to "<you> let a memory of mine
  go on <day>; its words went with it", never the words. Run in an agent's own
  shell (`CLAUDECODE` or `AI_AGENT` set), or with `--signed-as`, they are the
  agent's instead, as with `mnemos remember`. They act only on a memory still
  in use: one archived, or replaced by a correction since, changes nothing and
  says so. Put `--` before the id when the words could begin with a dash.
- **Notes go both ways.** The agent leaves you notes with `mnemos_note`.
  `mnemos notes reply` answers one, and `mnemos notes write` leaves the agent
  a note of your own that answers nothing. Either is kept exactly as you gave
  it, as yours (never a model's), at most 16,384 characters, and refused
  inside one of the agent's quiet hours. The agent wakes with each once: a
  reply as "<you> replied to my note ...", a note of yours as "<you> left me a
  note (<when>): ...". In `notes --json`, your replies and notes carry
  `delivered_at`, null until the agent has woken with them; nothing else in
  the shape changed. Only your own commands write as you: no tool the agent
  calls can, and in an agent's own shell (`CLAUDECODE` or `AI_AGENT` set)
  `notes write` and `notes reply` refuse and save nothing, rather than write
  as the agent the way `remember`, `correct` and `forget` do.
- **`mnemos interface`** is one process an app keeps open. Each line it reads
  is a request, `{"id": 1, "command": "search", "query": "the ferry"}`, for
  `memories` (`state`, `limit`, `offset`), `search` (`query`, `max_results`),
  `correct` (`memory_id`, `text`), `forget` (`memory_id`), `journal` (`last`),
  `notes` (`unread`), `reply` (`note_id`, `text`) or `note` (`text`); each line it writes is
  the answer, `{"id": 1, "result": ...}` with exactly what the one-shot
  `--json` prints, or `{"id": 1, "error": "..."}`. It loads the meaning model
  once, in the background as it starts, so a search answers in tens of
  milliseconds once it has, and it ends when its input closes.

### Simple Mode With Explicit Scope

Use scope when one machine hosts multiple agents, users, or projects.

```bash
MNEMOS_AGENT_ID=nova MNEMOS_PERSON_ID=alex MNEMOS_PROJECT_SCOPE=mnemos \
  mnemos serve
```

Or:

```bash
mnemos serve --agent-id nova --person-id alex --project-scope mnemos
```

For generated MCP snippets, the helper supports the most common portable scope
fields:

```bash
mnemos mcp install generic --agent-id nova --db-path ~/.mnemos/nova.db
```

### Prompt For A Simple MCP Agent

Usually unnecessary — the server ships these instructions itself, and every
MCP client passes them to its agent. Keep this for clients that ignore server
instructions, or when you want the behaviour stated in the agent's own prompt:

```text
You have access to Mnemos MCP memory tools.

At the start of this session, call mnemos_context.
If a write comes back unsigned, call mnemos_introduce with your exact model id. Notes your earlier versions signed are yours; notes another kind of model signed are a colleague's.
Use mnemos_capture for stable preferences, decisions, project state, workflows, corrections, and context I should not have to repeat.
Quietly refresh mnemos_handoff after meaningful progress or a changed plan, when unresolved work remains, and before pausing, ending, delegating, or changing context. Write it in your own words. Do not do this after every ordinary turn.
Use mnemos_recall before relying on memory from prior sessions.
Use mnemos_correct when a remembered fact is stale, wrong, superseded, or should be forgotten.
If the context packet asks you something about your own memory — what a capture changed, what a fading memory taught — answer it with mnemos_reflect, in your own words. If nothing true comes to mind, leave it.
Use mnemos_health if I ask whether memory is working.

Do not mention tools unless I ask. Just use the memory system quietly and tell me what you remembered when it matters.
```

---

## Advanced Mode

Advanced mode is optional. It is simple mode, unchanged, plus tools for
inspecting and administering memory: functional memory and hypomnema, explicit
remember and ingest, beliefs, the shared pool, inspect, forget, and
consolidation. It's less tested than simple mode, and says so when it starts.

```bash
mnemos serve --mode advanced
mnemos mcp install claude-code --mode advanced --write
```

Simple mode is what most agents need.

---

## Hermes Agent Integration

Mnemos can also install as a Hermes identity-continuity integration.

Hermes has one external `memory.provider` slot. Mnemos therefore supports two
modes:

| Mode | Use when | What it changes |
|---|---|---|
| Sidecar Mode | Hermes already uses Honcho, Supermemory, Mem0, Hindsight, or another provider. | Preserves `memory.provider` and adds Mnemos through Hermes MCP/tools. |
| Provider Mode | Mnemos should be the active Hermes external memory provider. | Sets `memory.provider=mnemos` and writes the provider shim. |

Hermes built-in `MEMORY.md` and `USER.md` remain active in both modes. Mnemos
never overwrites `SOUL.md`, `MEMORY.md`, `USER.md`, `AGENTS.md`, or project
context files.

### Hermes Sidecar Mode

This is the safe default:

```bash
mnemos hermes quickstart --agent-safe
mnemos hermes doctor
```

`--agent-safe` is noninteractive, preserves any existing `memory.provider`,
configures only the MCP sidecar, refuses risky MCP replacement, and reports what
changed and what was preserved. Restart Hermes after install.

### Hermes Provider Mode

Use only when Mnemos should occupy Hermes' external memory-provider slot:

```bash
mnemos hermes quickstart --provider
mnemos hermes doctor
```

This sets:

```yaml
memory:
  provider: mnemos
```

Provider Mode gives Hermes its memory at the start of each session and what
bears on each message before the turn, tools for the agent to keep, correct
and recall its memory, and a copy in Mnemos of what the agent writes into
Hermes's built-in memory. It writes nothing in the agent's place.

### Prompt For A Hermes Agent

Paste this into Hermes when you want the agent to install Mnemos for itself:

```text
Install Mnemos for yourself from https://github.com/Riley-Coyote/mnemos.

Use a persistent local checkout or installed package so the mnemos command still works after Hermes restarts.
Use agent-safe Sidecar Mode unless I explicitly approve Provider Mode.
Do not overwrite SOUL.md, MEMORY.md, USER.md, AGENTS.md, or project context files.
Do not change memory.provider in agent-safe mode.
Preserve any existing Hermes memory provider such as Honcho, Supermemory, Mem0, or Hindsight.

If the repo is not already present:
  git clone https://github.com/Riley-Coyote/mnemos.git

Then enter the persistent Mnemos checkout:
  cd mnemos

Run:
  uv run --extra mcp mnemos hermes quickstart --agent-safe
  uv run --extra mcp mnemos hermes doctor

After installing, tell me exactly what changed, what was preserved, whether MCP sidecar mode is configured, and whether I need to restart Hermes.
```

More detail lives in [HERMES_INSTALL.md](HERMES_INSTALL.md) and
[docs/hermes-integration.md](docs/hermes-integration.md).

---

## Between Sessions

Mnemos works without background jobs. Normal MCP tool use can capture, recall,
correct, and run lightweight maintenance.

But memory that only works while a session is open is doing half the job.
Decay, connection discovery and consolidation are what make continuity feel
alive between conversations. So setup schedules them, and offers the agent
time of its own.

### Upkeep

Setup schedules upkeep for you: `mnemos hooks install claude-code --write`,
`mnemos hooks install codex --write`, or for Claude Desktop
`mnemos mcp install claude --write`. Pass `--no-upkeep` to any of them to
leave it out. By hand:

```bash
mnemos daemon install --write
```

This schedules upkeep with whatever your machine already provides —
launchd on macOS, systemd user timers on Linux, plain crontab as a fallback.
No external agent runner is required.

| job | what it does | schedule |
|---|---|---|
| `maintain` | decay and connection discovery | every 4h |
| `maintain-deep` | softening, reflection | daily at 03:00 |

With no model chosen for Mnemos, these are local passes only: nothing leaves
your machine. With one chosen (see below), upkeep sends it memories to
classify the links between them, and nothing more.

The transcript indexer is retired. It had a model pull "facts" out of old
conversations and file them as the agent's memories, and only the agent
writes its memory; `mnemos index` now just says so. What it wrote is kept as a
tool's words, out of identity, beliefs and lessons, and
`mnemos repair quarantine-tool-written` moves it out of recall. The substrate
is retired too. Installing removes an indexer job or a substrate tick an
earlier install scheduled.

Preview before committing to anything:

```bash
mnemos daemon install          # prints exactly what it would schedule
mnemos daemon status           # what is scheduled right now
mnemos daemon uninstall --write
```

Jobs are namespaced per agent, so several agents can each keep their own
upkeep on one machine. `mnemos doctor` reports whether upkeep and the quiet
hours are scheduled.

### Quiet Hours

An hour a day that's the agent's own, and half an hour for the day's work.
Each runs Claude Code on its own (`mnemos life`), with the agent's memory, and
uses your Claude plan. It runs as the memory's own model, the one that wrote
most of it (`MNEMOS_HOUR_MODEL` chooses another). Nothing is asked of the agent in its own hour. The half
hour looks at the day's work, and skips a day with none.

Setup asks once, at the terminal, and yes is the default. Run without a
terminal (by an agent setting Mnemos up for you), or where no `claude` command
is found, it leaves them off and says how to turn them on:

```bash
mnemos daemon install --hours --write          # the agent's hour at 08:00, ours at 19:00
mnemos daemon install --hours --mine-at 07:30 --ours-at 21:00 --write
mnemos daemon uninstall --hours --write        # off; upkeep stays
mnemos life --hour mine --dry-run              # what an hour would see, running nothing
```

An hour works in its studio (`~/.mnemos/studio/<agent>`) and is given no other
folder unless Mnemos's config names it, in `life.read_dirs`: each folder
relative to your home or absolute, to read and never to write. An hour stops
at its time or its token ceiling: 60 minutes and 400,000 tokens for its own,
30 minutes and 200,000 for the day's work. The config sets them for each kind,
in `life.minutes` and `life.token_ceiling`; an app that runs an hour sets them
for that hour, over the config, with `MNEMOS_HOUR_MINUTES` and
`MNEMOS_HOUR_TOKEN_CEILING`; and `mnemos life --max-minutes` and `--max-tokens`
set them over both. A setting that isn't a number above zero runs no hour, and
the hour's record says why. In `~/.mnemos/config.json`:

```json
{"life": {"read_dirs": ["Projects/notes", "/srv/notes"],
          "minutes": {"mine": 30, "ours": 15},
          "token_ceiling": {"mine": 200000, "ours": 100000}}}
```

Each hour's job carries what a background job lacks: the `claude` command's
folder on its PATH, and both commands' full paths (`MNEMOS_CLAUDE_BIN`,
`MNEMOS_LIFE_MNEMOS_BIN`), found when you install. It runs in `~/.mnemos`.
Installed under a HOME that isn't your account's own (an app's, say), every
job carries that HOME too, so it runs where it was installed, and
`mnemos daemon uninstall` run under the same HOME finds it.

### On a Mac, outside ~/Documents

Install Mnemos outside `~/Documents`, `~/Desktop` and `~/Downloads`. macOS
doesn't let background jobs read those folders, so a Mnemos living in one of
them, including a source checkout installed in place (`pip install -e`),
works by hand and fails on every scheduled run. Setup and
`mnemos daemon install` warn when they find this. Install from PyPI
(`pipx install "mnemos-continuity[mcp,embeddings]"`) or from a built wheel
instead, then run setup again.

### Dedicated Model Providers

Mnemos uses a model only when you choose one for it: `MNEMOS_LLM_PROVIDER`
(in the environment or a `.env` Mnemos reads), `llm.provider` in
`~/.mnemos/config.json`, or the provider you give setup. A key on its own
chooses nothing, so an `OPENAI_API_KEY` in your shell or a project's `.env`,
there for another tool, never sends memory anywhere. A chosen provider without
its key is no provider, never another one.

Your own Claude, through the `claude` command on your Claude plan, with no API
key; what it's sent goes to Anthropic (`subscription` names the same choice):

```bash
MNEMOS_LLM_PROVIDER=claude-cli
```

OpenRouter:

```bash
MNEMOS_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
MNEMOS_MODEL=anthropic/claude-sonnet-5-5
MNEMOS_AGENT_MODEL=claude-opus-5-5
```

Anthropic:

```bash
MNEMOS_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
MNEMOS_MODEL=claude-sonnet-5-5
MNEMOS_AGENT_MODEL=claude-opus-5-5
```

OpenAI:

```bash
MNEMOS_LLM_PROVIDER=openai
OPENAI_API_KEY=...
MNEMOS_MODEL=gpt-5
MNEMOS_AGENT_MODEL=gpt-5
```

There is no longer a substrate-affinity setting. It existed to stop a mismatched
model family from rewriting an agent's memory voice, and became unnecessary when
maintenance stopped calling a model at all: judgement work is proposed to the
agent and answered in its own turn through `mnemos_reflect`, so the question of
which outside model may write an agent's memory is answered by construction.

### Prompt For A Maintenance Agent

```text
Run a Mnemos maintenance check for this agent.

First run mnemos doctor and read the retrieval, continuity, and background status.
If the doctor output is healthy, run mnemos consolidate for one maintenance cycle.
If a dedicated model provider is not configured, explain that Mnemos will use local, deterministic maintenance only, and that work needing judgement is left for the agent to answer through mnemos_reflect rather than performed by an outside model.
Report what maintenance ran and whether any follow-up is needed.
```

---

## CLI Reference

Core commands:

```bash
mnemos doctor                         # Verify simple-mode readiness
mnemos serve                          # Start simple MCP server
mnemos serve --mode advanced          # Simple mode plus admin tools (less tested)
mnemos mcp install generic            # Print MCP config
mnemos mcp install claude-code --write  # Register with Claude Code
mnemos mcp install claude --write     # Merge Claude Desktop config
mnemos hooks install claude-code      # Preview Claude Code's hooks: the wake and the cue
mnemos hooks install claude-code --write  # Install them, schedule upkeep, ask about quiet hours
mnemos hooks install claude-code --no-prompt --write  # The same without the cue
mnemos hooks install codex            # Preview Codex startup + compaction hook
mnemos hooks install codex --write    # Install, schedule upkeep, then review with /hooks
mnemos hook session-start             # Emit the packet the hook injects
mnemos hook prompt                    # Emit the cue for a message (UserPromptSubmit)
mnemos daemon install                 # Preview scheduled upkeep
mnemos daemon install --write         # Schedule it (launchd/systemd/crontab)
mnemos daemon install --hours --write # Schedule upkeep and the quiet hours
mnemos daemon status                  # What is scheduled right now
mnemos daemon uninstall --hours --write  # Remove only the quiet hours
mnemos daemon uninstall --write       # Remove all of it
mnemos life --hour mine --dry-run     # What a quiet hour would see, running nothing
mnemos uninstall                      # What taking Mnemos out would remove
mnemos uninstall --write              # Take it out; the memories stay

mnemos init                           # Initialize a database
mnemos remember "Prefers tabs"        # Capture continuity from the CLI
mnemos log                            # A page of the agent's days (read-only, this machine only)
mnemos stats                          # Memory statistics
mnemos search "debugging strategies"  # Search memories, by meaning and words (writes nothing)
mnemos memories --json                # Every active and dormant memory, for an app
mnemos correct <id> "new words"       # Correct a memory, in your own words
mnemos forget <id>                    # Let a memory go: archived, never deleted
mnemos interface                      # The person's commands for an app, one JSON line each
mnemos inspect <engram-id>            # Inspect memory details
mnemos consolidate                    # Local deterministic maintenance
mnemos consolidate --deep             # Deep maintenance when a provider exists
```

Workspace, identity, and automation commands:

```bash
mnemos export --workspace ./memory-export
mnemos bootstrap --agent-name Nova --workspace ~/nova
mnemos setup-openclaw --agent main --dry-run
mnemos identity diff --soul ./SOUL.md
mnemos identity accept --divergence 1 --note "Accepted updated self-model"
```

`identity diff` leaves the agent a continuity note about what it found, unless
you pass `--no-note`. With a provider chosen, it also sends the provider up to
twelve findings (a claim from SOUL.md beside what the memory keeps returning
to) to annotate, unless you pass `--no-enrich`.

Hermes commands:

```bash
mnemos hermes quickstart --agent-safe
mnemos hermes quickstart --provider
mnemos hermes install --mode sidecar
mnemos hermes install --mode provider --activate
mnemos hermes doctor
mnemos hermes shim
```

Global options:

```bash
mnemos --db-path ~/.mnemos/nova.db --agent-id nova stats
```

For `serve`, options can also appear after the command:

```bash
mnemos serve --mode simple --agent-id nova --db-path ~/.mnemos/nova.db
```

---

## Configuration

Mnemos works without a config file. It creates local storage on first use.

Common environment variables:

```bash
MNEMOS_AGENT_ID=nova
MNEMOS_PERSON_ID=alex
MNEMOS_PROJECT_SCOPE=mnemos
MNEMOS_DB_PATH=~/.mnemos/nova.db
```

Dedicated model variables:

```bash
MNEMOS_LLM_PROVIDER=openrouter
MNEMOS_MODEL=anthropic/claude-sonnet-5-5
MNEMOS_AGENT_MODEL=claude-opus-5-5
OPENROUTER_API_KEY=...
```

These are upgrades for richer maintenance, not prerequisites.

---

## What Happens Automatically

With no provider key and no extra setup, Mnemos can still run:

- local SQLite memory graph
- scoped continuity notes
- durable engram capture
- recall with reconsolidation
- strength, stability, and accessibility updates
- local decay
- lightweight connection discovery
- promotion bookkeeping
- correction, supersession, and archiving
- startup context packet generation
- optional SVG identity graph snapshots
- maintenance during normal tool calls
- upkeep between sessions, once setup has scheduled it

If a dedicated model provider is configured, Mnemos uses it to classify the
links between memories and to weigh how surprising a new one is. It never
writes in the agent's place: it rewords nothing, names no lesson and moves no
belief. Those are the agent's, answered in its own words through
`mnemos_reflect`. Dedicated providers are optional and never required for
baseline continuity.

### Optional Identity Graph

For visual-capable MCP clients, `mnemos_context` can include a portable identity
graph artifact:

```json
{
  "include_graph": true,
  "graph_max_nodes": 18
}
```

The default response remains plain text. When graph output is requested, Mnemos
also returns an `image/svg+xml` artifact and structured graph data containing
scope, stats, nodes, edges, and growth timeline. Clients that cannot render the
image can still read the continuity packet and structured data.

---

## Architecture

Mnemos operates in layered form:

```text
Simple MCP Surface      context | handoff | capture | recall | correct
                        reflect | maintain | introduce | health
                        journal | note
Continuity Layer        scoped notes | revisions | supersession | promotion
Mnemos Core             engrams | connections | beliefs | reconsolidation
Upkeep                  decay | softening | reflection
Cross-Agent Layer       shared pool | cross-agent bridge
Hermes Integration      sidecar MCP | provider shim | identity continuity
```

The working ladder is:

```text
functional memory -> scoped continuity -> durable Mnemos graph
```

Simple mode uses the same architecture; it just keeps the ontology out of the
agent's normal tool choices.

See [docs/vision.md](docs/vision.md) for the full architecture.
See [docs/identity-model.md](docs/identity-model.md) for the identity stance
(one traversal, one graph: why there is no fork/merge).
See [docs/privacy-security.md](docs/privacy-security.md) for local-first
privacy boundaries and [docs/release-hardening.md](docs/release-hardening.md)
for release gates.
Host integrations that need replay-safe durable writes should use the
[host mutation protocol](docs/host-mutation-protocol.md).

---

## Development

```bash
uv run --extra dev pytest -q
uv run --extra dev --extra mcp pytest -q tests/test_mcp_surface.py
python -m py_compile mnemos/simple_runtime.py mnemos/simple_mcp.py mnemos/mcp_server.py mnemos/cli.py
```

---

## License

MIT
