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
  choice, below). A long message is looked up by its start and its end. When some came
  up, Hermes says so in a line of its own.
- **Eleven tools** to keep the memory itself: `mnemos_capture`, `mnemos_recall`,
  `mnemos_correct`, `mnemos_handoff`, `mnemos_journal`, `mnemos_note`, `mnemos_reflect`,
  `mnemos_introduce`, `mnemos_maintain`, `mnemos_health` and `mnemos_page`.
- **Hermes's own memory, kept too.** MEMORY.md and USER.md stay on. What the agent
  writes there is kept in Mnemos as well, and changed or removed with it. A line added
  there twice is kept once, as Hermes keeps it.
- **Upkeep.** Memories fade unless they're used, and when one has nearly gone the agent
  is asked what it taught, so the lesson outlasts the details.
- **A page.** Ask the agent to show you its memory and it opens a page on this machine,
  where you can read all of it, reply to its notes, and correct a memory or let it go.

Each conversation (a chat, or a topic in one) keeps its own note of where it was. On the
command line a conversation is one `hermes` session, through its compressions. Resumed
in a new `hermes` after Hermes compressed it, it counts as a new conversation: the note it
left is still there at the wake, as one from another session.

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
  `~/.mnemos/hermes-<profile>.db` for each other one, unless you name another file
  (`db_path`, below) before the first session.
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
  `person_id` and `project_scope` name who it's with and which part of its memory this is:
  user and global, or the person and project `~/.mnemos/config.json` names. The first
  session writes the ones you left empty and keeps the ones you set; once there's a memory,
  they're there to read more than to change. A home that already had a memory with them
  empty goes on as before: the person each chat names, and the chat's name or the folder
  Hermes was started in.

A conversation reads its settings when it starts. After changing one, restart Hermes (the
gateway, or the `hermes` you're in). If the file can't be read (cut short, or a comma
missing), Mnemos doesn't start for that home, and Hermes's log names the file and what's
wrong with it. It never writes over it, and starts no other memory meanwhile.

## What it does on your machine

- **No network unless you choose it, and no telemetry.** Two settings send words off this
  machine, and both are off until you set them.
  - `deep_maintenance: true`, with a model provider chosen for Mnemos
    (`MNEMOS_LLM_PROVIDER`: `openrouter` or `openai`), lets Mnemos use a model on the
    memory. Memory text then goes to that provider whenever the agent saves or corrects a
    memory (the new one, with up to ten it may be linked to and the beliefs the agent
    holds), and during upkeep. The model is Mnemos's own choice there
    (`anthropic/claude-sonnet-4-5` through OpenRouter, `gpt-4o-mini` at OpenAI) unless you
    name one (`MNEMOS_MODEL`). `anthropic` is a third provider only where Hermes's Python
    has the `anthropic` package; where it hasn't, Mnemos uses no model and says so in
    Hermes's log.
  - `MNEMOS_EMBEDDING_PROVIDER=gemini` sends words to Google, for meaning search: what the
    agent keeps and what it shares, as it keeps it (its memories and what they taught it,
    the notes it leaves itself and you, its journal), and each message and each search (of
    a long message, its start and its end).

  Either provider can also be chosen in `~/.mnemos/config.json` (`llm.provider`,
  `embeddings.provider`), which every Mnemos agent on the machine reads. A key alone
  chooses nothing.

  Without either, memories are found by their words. One case is neither: if Hermes's
  Python already has `sentence-transformers` and its small model (`all-MiniLM-L6-v2`) is
  already on this machine, Mnemos searches by meaning with that, here, sending nothing.
  It never downloads a model. For the moment that model loads, Hugging Face's libraries
  are switched offline in Hermes's process, and two loggers of those libraries are turned
  down there so they don't fill Hermes's log.
- **Keys and settings come only from Hermes.** What Mnemos reads from the environment it
  asks of Hermes (`agent.secret_scope`), which answers for the profile that is speaking:
  its own settings (every `MNEMOS_` name) and the key of a provider you chose
  (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`). So a
  setting goes in that profile's own `.env`, and one profile's never counts for another.
  It reads no `.env` file itself and no other tool's credentials, and inside Hermes it
  takes no notice of another agent's marks in the environment (Claude Code's, when Hermes
  was started from there).
- **Its own files.** It keeps the memory in `~/.mnemos/` and its settings in
  `$HERMES_HOME/mnemos.json`, and reads `~/.mnemos/config.json` if you have one (a new
  profile takes its person and project from there). It reads Hermes's `config.yaml` for
  three things: whether it is the memory provider, which model the agent runs (to sign what
  it writes), and whether Mnemos was connected there before as an MCP server (it then keeps
  that memory).
- **The machine's shared memory.** What the agent marks as shared goes to
  `~/.mnemos/shared-memory.db`, which every Mnemos agent on this machine can read; nothing
  goes there unless the agent marks it so. `mnemos_recall` searches it too, so what another
  agent here shared can come into this agent's answer, and a shared memory that is found
  is marked as used. Upkeep tends it (what fades there, what links to what), whoever wrote
  it. `MNEMOS_SHARED_MEMORY=off` in a profile's `.env` turns all of that off for that
  profile. Set in the shell or service that starts Hermes, it turns it off for every profile
  that doesn't set it itself: the only setting Mnemos reads from there, since it can only
  withhold.
- **A short background process.** When upkeep is due (at the end of a session, every 24
  turns, after the agent saves something) it runs in a Python process of its own,
  Hermes's Python, which ends when it's done. Nothing is scheduled, and it starts no
  other program. It runs in the memory's folder and runs nothing it finds there. It isn't
  given Hermes's environment. It gets, each by name, what a process needs to run (the
  path, your home folder, your language, where the machine's certificates and a model's
  cache are), Mnemos's own settings if you set any, and what you chose for Mnemos, as the
  profile that is speaking has it: the chosen model provider's key, only with
  `deep_maintenance` on; Gemini's key, only with meaning search set to it; and your proxy
  settings (an address there can hold a password), only with one of those. No other key
  of Hermes's reaches it.
- **The page.** `mnemos_page` serves the page from inside Hermes on 127.0.0.1, on a port
  the system picks and a path made fresh each time, and answers only this machine. It
  stays while the conversation that opened it goes on and while you're using it, and
  closes about ten minutes after both end. It shows this agent's memory and writes only
  there: not the other agents Mnemos keeps a memory for on this machine, and not what
  they share. It looks at nothing else on the machine, and a scheduled job can't open it.
  Outside Hermes's terminal (in Telegram, say), the first session tells the agent the page
  opens on the computer Hermes runs on, and not to offer it unless you ask.
- **Backups.** The memories are outside Hermes's folder, so Mnemos names them to
  `hermes backup`, which takes them along: this profile's and each other profile's, since
  a backup is of every profile. It finds each one as that profile opens it: by its
  `mnemos.json`, or else by `MNEMOS_DB_PATH` in the profile's own `.env`, which Mnemos asks
  Hermes for, for that profile. Only Mnemos memories are named: a file a profile's settings
  point at that isn't one is left out and untouched, and Hermes's log says which and why.
  Hermes copies a file as it stands, so Mnemos first folds into each what SQLite still
  holds in its log, and keeps it still for the copy. Three things a backup leaves out: the
  machine's shared memory, which isn't any one Hermes's; a memory you keep outside your
  home folder, which Hermes skips and says so; and all of it in a quick snapshot
  (`hermes backup --quick`, `/snapshot`), which takes only Hermes's own state files.
  Restore with Hermes stopped.
- **The system prompt.** Mnemos adds its rules for keeping a memory, and the agent's wake.
- **The open-file limit.** On its first start it raises Hermes's limit on open files to
  4,096 if it's lower, since every conversation holds a few files open on the memory. It
  never lowers it.

## Upgrading from 0.6.6

Settings are now read for each profile, through Hermes: from the profile's own `.env`, or
from its `mnemos.json`. A run of one profile also hears what's set in the shell or service
that starts Hermes, but a gateway that serves profiles doesn't pass that on to a profile.
If your memory was named only there (`MNEMOS_DB_PATH`, `MNEMOS_AGENT_ID`,
`MNEMOS_PERSON_ID`, `MNEMOS_PROJECT_SCOPE`), the profile starts a memory of its own and
records it in `mnemos.json`, and Hermes's log names the settings it passed over. The earlier
memory is untouched where it was. To go on with it:

1. Stop Hermes.
2. Put the same `MNEMOS_` lines in the profile's `.env` (`~/.hermes/.env`, or
   `~/.hermes/profiles/<name>/.env`).
3. In the profile's `mnemos.json`, take out `db_path`, `agent_id`, `person_id` and
   `project_scope`, which the first session filled in. Keep one you had set yourself
   (`mnemos.json.bak`, when it's there, is the file before its last rewrite).
4. Start Hermes. It wakes with the memory it had.

What the profile kept in its own memory meanwhile stays in that file.

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
