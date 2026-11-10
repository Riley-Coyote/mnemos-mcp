# Mnemos

![Mnemos: continuity for the agent itself. A slice of one real agent's memory, up close: 2,226 memories and 11,766 links.](docs/banner.png)

Mnemos gives a Hermes agent a memory of its own.

Your agent has met you hundreds of times. It has never met you twice. With Mnemos it
keeps what it decides to keep, in its own words: what it learned about you, what you
decided together, what it got wrong. Every session it wakes with that before you say
anything, and with each message the few memories that bear on it come back to it.

Nothing is written from your conversations on its own. If something matters, the agent
keeps it, and when it was wrong, the agent corrects it. The memory is a file on this
machine, and it's the agent's: removing the plugin leaves it where it is.

It isn't a search engine for your files. It won't index your documents or your code.

## Install

```bash
hermes plugins install mnemos
hermes memory setup mnemos
```

Setup tells you who the agent is and where its memory is kept. Start a new session and
it wakes with it. Mnemos needs no API key and no account.

If you connected Mnemos to Hermes before, with `mnemos connect hermes`, install with
`hermes plugins install mnemos --force`, which replaces the folder connect wrote. The
agent keeps its memory and its settings.

## What the agent gets

- **A wake.** Each session opens with what it kept: the note it left itself in this
  conversation, what it holds as standing, what it knows of you, and now and then a
  question its memory asks it.
- **What comes to mind.** With each message, up to four memories that came up by
  themselves, by the words they share with the message (searching by meaning is a
  choice, below). When some did, Hermes says so in a line of its own.
- **Eleven tools** to keep the memory itself: `mnemos_capture`, `mnemos_recall`,
  `mnemos_correct`, `mnemos_handoff`, `mnemos_journal`, `mnemos_note`, `mnemos_reflect`,
  `mnemos_introduce`, `mnemos_maintain`, `mnemos_health` and `mnemos_page`.
- **Hermes's own memory, kept too.** MEMORY.md and USER.md stay on. What the agent
  writes there is kept in Mnemos as well, and changed or removed with it.
- **Upkeep.** Memories fade unless they're used, and when one has nearly gone the agent
  is asked what it taught, so the lesson outlasts the details.
- **A page.** Ask the agent to show you its memory and it opens a page on this machine,
  where you can read all of it, reply to its notes, and correct a memory or let it go.

Each conversation (a chat, or a topic in one) keeps its own note of where it was.

In a scheduled job (cron) nobody is there, so Mnemos writes nothing by itself. The agent
gets a short read of its memory that records nothing, what comes with the job's prompt
leaves no trace, and upkeep and the copy of MEMORY.md wait for a conversation. Its own
tools still work, so a job can keep something when that's what you asked of it: that one
thing is kept, and the upkeep that follows a save in a conversation waits too. Subagents
have no memory: Hermes gives them none.

## Each profile is its own agent

Every Hermes profile is an agent of its own, with a memory of its own. Install Mnemos in
each profile you want it for:

```bash
hermes -p work plugins install mnemos
hermes -p work memory setup mnemos
```

A profile made with `hermes profile create <name> --clone` brings Mnemos with it, and at
its first session it gets a memory of its own rather than sharing the one it was cloned
from.

One profile is one agent, with one memory in every chat. If several people talk to the
same profile (a bot in a group, or in each of their chats), it's the same agent, and what
it kept from one conversation can come to mind in another. People who shouldn't share
that want a profile each.

## Where it's kept

- The memory: `~/.mnemos/hermes.db` for the default profile, and
  `~/.mnemos/hermes-<profile>.db` for each other one.
- Its settings: `$HERMES_HOME/mnemos.json`, with `mnemos.json.bak` beside it once they've
  been rewritten: the copy from before.

## Settings

In `$HERMES_HOME/mnemos.json`, with their defaults:

- `auto_recall` (true): bring up what may bear on each message.
- `mirror_builtin_memory` (true): keep what the agent writes in MEMORY.md and USER.md.
- `max_recall_results` (4) and `max_context_chars` (2200): how much comes with a message.
- `max_wake_chars` (0): a limit on the wake's length; 0 leaves it to the wake's own.
- `maintenance_interval` (24): upkeep every this many turns in a long session; 0 turns
  that off.
- `deep_maintenance` (false): let upkeep use a model, below.
- `agent_id` and `db_path`: which agent this profile is, and where its memory is.
  `person_id` (user) and `project_scope` (global) name who it's with and which part of its
  memory this is. The first session writes all four; they're there to read more than to set.

## What it does on your machine

- **No network unless you choose it, and no telemetry.** Two settings send words off this
  machine, and both are off until you set them.
  - `deep_maintenance: true`, with a model provider chosen for Mnemos
    (`MNEMOS_LLM_PROVIDER`: `openrouter`, `openai` or `anthropic`), lets Mnemos use a model
    on the memory. Memory text then goes to that provider whenever the agent saves or
    corrects a memory (the new one, with up to ten it may be linked to and the beliefs the
    agent holds), and during upkeep.
  - `MNEMOS_EMBEDDING_PROVIDER=gemini` sends the words of each memory and of each message
    to Google, for meaning search.

  Either provider can also be chosen in `~/.mnemos/config.json` (`llm.provider`,
  `embeddings.provider`), which every Mnemos agent on the machine reads. A key alone
  chooses nothing.
- **Keys and settings come only from Hermes.** What Mnemos reads from the environment it
  asks of Hermes (`agent.secret_scope`), which answers for the profile that is speaking:
  its own settings (the `MNEMOS_` names) and the key of a provider you chose
  (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`). It reads
  no `.env` file and no other tool's credentials.
- **Its own files.** It keeps the memory in `~/.mnemos/` and its settings in
  `$HERMES_HOME/mnemos.json`, and reads `~/.mnemos/config.json` if you have one. It reads
  Hermes's `config.yaml` to see whether it is the memory provider and which model the
  agent runs, to sign what it writes. What the agent marks as shared goes to
  `~/.mnemos/shared-memory.db`, which every Mnemos agent on this machine can read; nothing
  goes there unless the agent marks it so. Upkeep tends that shared memory too (what fades
  there, what links to what), whoever wrote it.
- **A short background process.** When upkeep is due (at the end of a session, every 24
  turns, after the agent saves something) it runs in a Python process of its own,
  Hermes's Python, which ends when it's done. Nothing is scheduled, and it starts no
  other program. It isn't given Hermes's environment. It gets, each by name, what a
  process needs to run (the path, your home folder, your language), Mnemos's own tuning
  numbers if you set any, and what you chose for Mnemos, as the profile that is speaking
  has it: the chosen model provider's key, only with `deep_maintenance` on; Gemini's key,
  only with meaning search set to it; and your proxy settings, only with one of those.
  No other key of Hermes's reaches it.
- **The page.** `mnemos_page` serves the page from inside Hermes on 127.0.0.1, on a port
  the system picks and a path made fresh each time, and answers only this machine. It
  stays while the conversation that opened it goes on and while you're using it, and
  closes about ten minutes after both end. It writes only in this agent's memory.
  Beside it, it shows, read only, the other agents whose memory Mnemos keeps in
  `~/.mnemos` and what they share. It looks at nothing else on the machine, and a
  scheduled job can't open it.
- **Backups.** The memory is outside Hermes's folder, so Mnemos names it to
  `hermes backup`, which takes it along. Hermes copies the file as it stands, so Mnemos
  first folds into it what SQLite still holds in its log. Restore with Hermes stopped.
- **The system prompt.** Mnemos adds its rules for keeping a memory, and the agent's wake.
- **The open-file limit.** On its first start it raises Hermes's limit on open files to
  4,096 if it's lower, since every conversation holds a few files open on the memory. It
  never lowers it.

## Removing it

```bash
hermes plugins remove mnemos
```

Hermes removes the plugin and goes back to its built-in memory. The memory stays in
`~/.mnemos`, and its settings in `$HERMES_HOME/mnemos.json`, because they're the agent's;
deleting them is left to you.

## More

Mnemos is also the memory of agents in Claude Code, Codex, OpenClaw and others that speak
MCP: [github.com/Riley-Coyote/mnemos-mcp](https://github.com/Riley-Coyote/mnemos-mcp).
Apache-2.0.
