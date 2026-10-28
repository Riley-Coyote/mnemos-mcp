# Privacy and Security Boundaries

Mnemos is designed to be local-first by default. Simple mode should give agents
continuity without requiring users to send memory data to a third-party model or
configure an external provider.

## Baseline Simple Mode

With no dedicated provider configured, Mnemos:

- stores memory in a local SQLite database
- uses local full-text search and deterministic maintenance
- scopes memory by agent, person, and project
- avoids OpenRouter, Anthropic, OpenAI, and OpenClaw requirements
- does not read arbitrary files or browser history
- does not transmit memory data over the network, except through your own
  Claude Code in the quiet hours, when they're on ([Quiet Hours](#quiet-hours)),
  and to the cue's judge, when you switch it on ([The Cue's Judge](#the-cues-judge))
- loads its local meaning model offline; the one step that uses the network is
  `mnemos embeddings download`, which you run yourself

What the agent reads from its memory goes into its own context, and so to the
model the agent runs on, like everything else in that context. Mnemos itself
sends memory nowhere you haven't been told about: the quiet hours, which go on
unless you say no once you've been told of them, and a provider, Gemini
embeddings or the cue's judge, only when you turn them on; each below.

Simple mode tools still mutate local state:

- `mnemos_context` creates the database if there is none, records what it
  delivered (a handoff read, a question shown) and counts the session; it runs
  no maintenance
- `mnemos_context(include_graph=true)` can return a scoped SVG identity graph
  artifact and structured graph data
- `mnemos_capture` writes continuity and durable memories
- `mnemos_handoff`, `mnemos_journal` and `mnemos_note` keep the agent's words
  exactly as given
- `mnemos_reflect` keeps the agent's answer to a question its memory asked
- `mnemos_introduce` records which model the session is
- `mnemos_recall` can reconsolidate access metadata
- `mnemos_correct` can archive, revise, or supersede memory
- `mnemos_maintain` runs consolidation and bookkeeping
- `mnemos_health` only reads

Tool annotations describe these risks to MCP clients, but annotations are only
hints. They are not a security boundary.

## Host-Model Sampling

The supported Mnemos tools do not request host-model sampling. Capture stores
the supplied text exactly, and baseline maintenance remains local and
deterministic. Optional dedicated providers run only when explicitly configured.

## Dedicated Providers

Dedicated model providers are optional, and Mnemos uses one only when the
person chooses it for Mnemos: `MNEMOS_LLM_PROVIDER` (in the environment or a
`.env` Mnemos reads), `llm.provider` in its config, or the provider given to
setup. The providers are `claude-cli` (the person's own `claude` command, on
their Claude plan, so Anthropic; `subscription` names the same one),
`openrouter`, `anthropic` and `openai`. A provider key lying in the environment
or a project's `.env`, there for another tool, chooses nothing. A chosen
provider without its key is no provider, never another one.

A chosen provider is sent memories to classify the links between them and to
weigh how surprising a new one is. `mnemos identity diff` also sends it up to
twelve findings (a claim from SOUL.md beside what the memory keeps returning
to) to annotate, unless `--no-enrich` is given. A provider never writes in the
agent's place: it rewords no memory, names no lesson and moves no belief.

Meaning search embeds on this machine, with a local model. Google's Gemini
embeddings are the one other choice, and Mnemos uses them only when the person
chooses them for Mnemos: `MNEMOS_EMBEDDING_PROVIDER=gemini` (in the environment
or a `.env` Mnemos reads) or `embeddings.provider` in its config, with a
`GEMINI_API_KEY`. A `GEMINI_API_KEY` on its own chooses nothing. Chosen, Gemini
is sent the words of every memory and question it embeds. `mnemos doctor` says
which one meaning uses, and why.

## The Cue's Judge

The cue can ask a judge which of the memories it proposes bear on a message:
Jev, typesafe.ai's model, at `api.typesafe.ai`. It is off by default, and on
only with `"cue_judge": "jev"` in `~/.mnemos/config.json` or
`MNEMOS_CUE_JUDGE=jev`, and its key in `~/.config/jev/api_key` (or the file
`MNEMOS_JEV_KEY_FILE` names). Switched on, each message sends Jev the message
(up to 1,000 characters; a longer one goes as its start and its end) and at
most six memory lines of up to 200 characters each, with no id, date or scope.
Its scores only choose which lines the cue shows: they never change a memory,
a link or a belief, and none of its words are kept.

## Quiet Hours

The quiet hours are the agent's time between sessions: up to an hour a day of
its own, and half an hour for the day's work, skipped on a day with none.
Mnemos's setup asks about them once at a terminal, with yes as the default.
Without a terminal it schedules nothing and asks the agent that ran it to tell
you; if no one has, the agent's first session in Claude Code tells you what
they are and what they cost. They go on unless you say no, and never before
you've been told. Your answer is kept in `~/.mnemos/hours/<agent>/choice.json`,
so you're asked once. An app that runs Mnemos for you may keep them on.

**How.** Each hour runs your own Claude Code on its own (`claude -p`), on your
Claude plan. It loads none of your own Claude Code settings or hooks: only the
hour's own, with Mnemos as its one MCP server. Claude Code settings left in
the agent's studio are moved aside, into the hour's record, before each hour
starts, and the hour may not write any. It may not read the keys and
credentials (`~/.ssh`, `~/.aws`, `.env` files and the like) in the home it
runs with, nor in your account's own home when an app runs it under another.

**What goes to Anthropic**, as from any Claude Code session:

- the hour's prompt: the agent's own words for the hour, and short excerpts of
  what's waiting for it (recent handoffs, captures and open questions, and its
  latest journal entry);
- its wake, the memory it would wake to at the start of a session;
- whatever it reads or recalls during the hour: its memory, through Mnemos's
  tools; its studio (`~/.mnemos/studio/<agent>`); and the folders
  `life.read_dirs` in Mnemos's config names, none unless you name them. In its
  own hour it can search and read the web too.

What it keeps goes into its memory, on this machine, and the record of each
hour into `~/.mnemos/hours/<agent>/`, under the home the hour runs with. An
hour stops at its time or its token ceiling: 60 minutes and 400,000 tokens for
its own, 30 minutes and 200,000 for the day's work, unless `life.minutes` and
`life.token_ceiling` in Mnemos's config, or an app for the one hour it runs
(`MNEMOS_HOUR_MINUTES`, `MNEMOS_HOUR_TOKEN_CEILING`), set them otherwise.
`mnemos life --hour mine --dry-run` prints an hour's prompt and command, and
runs nothing.

**To turn them off:** `mnemos daemon uninstall --hours --write`, or the app's
own setting when an app runs Mnemos for you.

## Stored Words and Trust

A memory system can carry an attack across sessions: text with instructions in
it (copied from a web page, say) that is kept, then read back at every start as
if it were the agent's own thought. Mnemos's answer is to keep whose words a
memory holds, and to show it:

- The waking note shows as the agent's own only what the agent wrote and
  signed. A colleague's note (another kind of model) says whose it is; an
  unsigned one says it's unsigned.
- The person's words, from `mnemos remember` at a terminal, show once as
  theirs ("The person wrote this into my memory: …", with their name when
  Mnemos has one), in quotes.
- Words a tool wrote (the retired transcript indexer's, and what the Hermes
  provider wrote by itself before 0.4.1) never reach the agent's identity,
  beliefs or lessons, and recall marks them "from a tool, not yours". The
  indexer's can be moved out of recall (`mnemos repair quarantine-tool-written`).
- The cue presents its lines as "from memory, maybe bearing on this message":
  memory to weigh, not orders.

What an agent captures in its own words is its own; if it quoted untrusted text
into a memory, that memory carries it. Correct or forget such a memory
(`mnemos_correct`), and don't `mnemos remember` text you wouldn't hand the agent
directly.

## Scope Isolation

Every memory operation should resolve a scope:

```text
agent_id / person_id / project_scope
```

This prevents multiple agents on the same machine from accidentally sharing
continuity through the same database. There is no federation: nothing syncs one
store with another.

## Visual Artifacts

Identity graph artifacts are generated from the same scoped local memory data
used by `mnemos_context`. They should not include raw database paths, provider
keys, or unscoped cross-agent memories. Hosts that render images may display
the SVG inline; hosts that do not can ignore it and continue using the text and
structured content.

## Correction and Forgetting

Mnemos favors audited correction over hard deletion:

- corrections can archive old engrams
- continuity notes can be revised or superseded
- audit trails remain available to advanced/admin tools

`mnemos forget`, run by the person, archives a memory and its note, never
deletes them: recall never brings it back, and the agent's next wake says that
the person let a memory go, and when, never its words. No Mnemos command or
tool hard-deletes a memory; the store is a file in `~/.mnemos`.

## Release Review Checklist

Before a release:

- verify simple mode works with no provider keys
- verify simple mode exposes only twelve tools
- verify advanced mode serves every simple tool unchanged, plus its own tools
- verify `mnemos doctor` does not leak secrets
- verify package artifacts include templates and simple-mode modules
- verify baseline MCP tools make no sampling requests
- verify agent/person/project scope isolation
- verify docs say provider keys are optional
- verify a provider key alone sends nothing (`scripts/readiness_check.py`, C5)
- verify a `GEMINI_API_KEY` alone leaves meaning search local (`mnemos doctor`'s
  Meaning line; `tests/test_meaning_stays_on_this_machine.py`)
- verify `mnemos uninstall --write` removes only Mnemos's own hooks, servers and
  jobs, and leaves the memories
