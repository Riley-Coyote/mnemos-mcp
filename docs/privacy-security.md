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
- does not transmit memory data over the network
- loads its local meaning model offline; the one step that uses the network is
  `mnemos embeddings download`, which you run yourself

What the agent reads from its memory goes into its own context, and so to the
model the agent runs on, like everything else in that context. Mnemos itself
sends memory nowhere.

Simple mode tools still mutate local state:

- `mnemos_context` can create the database and log maintenance
- `mnemos_context(include_graph=true)` can return a scoped SVG identity graph
  artifact and structured graph data
- `mnemos_capture` writes continuity and durable memories
- `mnemos_recall` can reconsolidate access metadata
- `mnemos_correct` can archive, revise, or supersede memory
- `mnemos_maintain` runs consolidation and bookkeeping

Tool annotations describe these risks to MCP clients, but annotations are only
hints. They are not a security boundary.

## Host-Model Sampling

The supported Mnemos tools do not request host-model sampling. Capture stores
the supplied text exactly, and baseline maintenance remains local and
deterministic. Optional dedicated providers run only when explicitly configured.

## Dedicated Providers

Dedicated model providers are optional, and Mnemos uses one only when the
person chooses it for Mnemos: `MNEMOS_LLM_PROVIDER`, or the provider given to
setup. A provider key lying in the environment or a project's `.env`, there for
another tool, chooses nothing. A chosen provider without its key is no
provider, never another one.

A chosen provider is sent memories to classify the links between them and to
weigh how surprising a new one is. It never writes in the agent's place: it
rewords no memory, names no lesson and moves no belief.

Meaning search embeds on this machine, with a local model. Google's Gemini
embeddings are the one other choice, and Mnemos uses them only when the person
chooses them for Mnemos: `MNEMOS_EMBEDDING_PROVIDER=gemini` (in the environment
or a `.env` Mnemos reads) or `embeddings.provider` in its config, with a
`GEMINI_API_KEY`. A `GEMINI_API_KEY` on its own chooses nothing. Chosen, Gemini
is sent the words of every memory and question it embeds. `mnemos doctor` says
which one meaning uses, and why.

## Stored Words and Trust

A memory system can carry an attack across sessions: text with instructions in
it (copied from a web page, say) that is kept, then read back at every start as
if it were the agent's own thought. Mnemos's answer is to keep whose words a
memory holds, and to show it:

- The waking note shows as the agent's own only what the agent wrote and
  signed. A colleague's note (another kind of model) says whose it is; an
  unsigned one says it's unsigned.
- The person's words, from `mnemos remember` at a terminal, show once as
  theirs ("Riley wrote this into my memory: …"), in quotes.
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

Future user-facing forget flows should make the difference between archive,
supersede, and hard deletion explicit.

## Release Review Checklist

Before a release:

- verify simple mode works with no provider keys
- verify simple mode exposes only eleven tools
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
