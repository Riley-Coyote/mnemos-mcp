# Changelog

## 0.5.0 (2026-10-28)

### Apache-2.0, and a new home

Mnemos is now under the Apache License 2.0 ([LICENSE](LICENSE), with a
[NOTICE](NOTICE)), and lives at
[github.com/Riley-Coyote/mnemos-mcp](https://github.com/Riley-Coyote/mnemos-mcp):
the package's links, every clone in the docs and the Hermes prompt point
there. Releases before 0.5.0 were published under the MIT License, and stay
under it, and code contributed under that license keeps its notice, in the
NOTICE. The package keeps its name, `mnemos-continuity`, and its command,
`mnemos`.

### The dream: what in its memory needs a mind

The upkeep links memories and lets the unused fade, and anything that needs
judgement it asks the agent: what a fading memory taught, whether a thought
that keeps coming back is a belief, whether a belief still holds, what a new
memory changed. Those questions reach it at work, where it lets most of them
pass, and after three showings the asking stops. On one real memory, 24
fading memories had asked what they taught and none was ever answered, and
its seven beliefs had never moved from 40%.

So the quiet hours have a third: the dream, a short time each night after the
deep upkeep (03:30; `--dream-at` moves it). It is given what's fading, what
keeps coming back, its beliefs, what came in since the last dream, and a few
new memories set beside older ones near them in meaning, and it answers in its
own words or lets each go. A question comes to one dream only, sessions'
stopped ones included. It reaches nothing but its memory's tools (no file,
shell or web; no note, page or handoff), wakes light so it spends nothing a
session would, skips a night when nothing waits, and stops at 20 minutes or
200,000 tokens. Setup and the first session tell the person about it with the
other hours. `mnemos life --hour dream --dry-run` shows what it would be given.

The upkeep's own report, which the health card and a maintenance run called
the dream journal, is "upkeep's report" now: it is the code's account, and the
dream is the agent's.

### Your agent's notes, where you can answer them

An agent's notes waited where little showed them: only `mnemos notes`, at a
terminal, read them, and nothing answered one where it was. So:

- `mnemos log` opens on **For you**: each of the agent's notes, with a place
  to answer it right under it, and a place to leave it a note of your own. It
  wakes with what you write, once. Its days, journal and quiet hours are
  under **Its life**; every memory, its beliefs, what its memory asks it and
  its notes to itself under **Its memory**. The page keeps nothing but what
  you write there and which of its notes you've read (one counts as read once
  it has stayed on your screen a moment), and only the page itself can send
  either.
- Your agent can open it for you. A new tool, `mnemos_page`, serves the same
  page from the agent's own MCP server until the session ends, so an agent
  with no terminal, in Claude's desktop app say, can open it too.
- When a note of the agent's is waiting for you unread, its next session
  wakes knowing, once, so it can mention it if it fits; never in its own
  quiet hours, which no one is in.
- The first session ends by telling you that you can see everything it
  keeps, and answer its notes, on that page.
- In an agent's own shell, `mnemos notes` no longer marks the notes read: that
  was the agent reading them, not you, and it showed you as having read notes
  you had never seen.
- Notes are meant to be short: a few lines, at most one question, last.
- The page has one typeface now (Inter), and its dark is neutral grey and
  black.

### The OpenClaw guide installs Mnemos

The OpenClaw guide's quick start said `pip install "mnemos[all]"`, and
`mnemos` on PyPI is another project: following it installed someone else's
package. It now says `pip install "mnemos-continuity[all]"`. Four notes from
the project's first months left the docs, being about how it was built
rather than how it works (a design audit, a development layout, the 0.2.1
release checklist and the shared pool's status board); they stay in the
history.

### The first session makes sure memory carries

Set up by an agent, or with only the server added, Mnemos could end up with
memory that doesn't load by itself, and with quiet hours no one had told the
person about: setup asked about them only at a terminal, and an agent's shell
isn't one. Now the first session in Claude Code starts by settling both, from
what is really on the machine. When nothing loads this memory at session
start, the agent says so in a sentence and, with a yes, runs setup itself
(`mnemos hooks install claude-code --write`, naming this memory). When no one
has told the person about the quiet hours, it tells them what they are and what
they cost: time on their Claude plan, and what the agent thinks over in them
goes to Anthropic. They go on unless the person says no, and never before
they've been told. It asks one question for both, then gets to know them as
before, one question at a time. What is already set, it says in a line. Outside
Claude Code the first session is as it was.

Setup keeps the person's answer about the quiet hours, given at the terminal or
through `mnemos daemon install --hours --write` and `mnemos daemon uninstall
--hours --write` (in `~/.mnemos/hours/<agent>/choice.json`), so the first
session doesn't ask what setup already did. Run without a terminal, setup no
longer just leaves them off: it asks the agent that ran it to tell the person,
with the command for each answer. And `mnemos doctor` says whether Claude Code
wakes this memory (`Wake:`), with the command that sets it up when it doesn't;
a hook for another agent's memory doesn't count.

Checked in real Claude Code sessions on a new memory, with setup's commands
fenced so nothing on the machine changed: the agent explained both plainly,
asked once, ran the two commands for this memory, and then asked what to call
the person.

### A release waits until a stranger's agent wakes as itself

Every check proved that the memory arrives; none asked the mind it arrives
in. `scripts/wake_check.py` does. It installs the built wheel as a stranger
would, sets up the wake with setup's own command, and holds two real Claude
Code sessions with a made-up person, fenced off from the machine that runs it:
Claude Code loads none of that machine's settings and may call only Mnemos's
tools, and Mnemos runs with a home of its own. The second session's words go
to a report for a person to read, with any that read as a briefing about
someone else flagged, and a release is tagged only once someone has read it
(docs/release-hardening.md, "Waking as Oneself"). On 0.5.0, asked whose
memories it woke with, the agent called them its own: "a bit like reading my
own diary from yesterday".

### A wake no one named a reader for reads its own note as its own

Claude Code started in a terminal without `--model` doesn't name its model to
its hooks, and that is how most people start it. The wake couldn't place the
reader, so it said once, in the opening, "if I'm not Opus 5.5, I'm visiting",
and then treated the resident's own last note as no one's: "where things were
left", signed with its own name, and "A colleague's note is theirs: I take
what's useful and don't claim the work." It read its own work as someone
else's. Now, after that one line, its notes and journal are placed as the
resident's: its own note is "where i was", its journal "last time I wrote in
my journal", and only a note another kind of model signed is a colleague's.
Its latest quiet hour shows too, which before only a reader the harness named
saw. The rest of the wake, which says whose memory it is ("what Opus 5.5 has
come to see"), stays as it was. The Claude desktop app names the model when
it starts a session, so its wakes were already the reader's own.

### Out of the repository: forge, and the old project page

Three things in the repository weren't Mnemos: `forge/`, a skill for creating
OpenClaw agents and dispatching coding agents to terminal panes; the old
project page `index.html`, made in April and served by nothing now;
and `synapse-panel.png`, which only that page showed. They're gone from the
tree, and stay in its history. Nothing in the package, the tests or the
release checks used them, and the source distribution is smaller by them.

### The docs say what the code does

The README, `SETUP.md` and `docs/privacy-security.md` were checked against the
code claim by claim, before Mnemos goes public. What changed:

- `mnemos_context` runs no maintenance: the README said it ran some, and the
  privacy doc said it logged it. Doctor creates and changes nothing: `SETUP.md`
  said it made the store and ran maintenance.
- The privacy doc lists every tool that writes (it named five of the ten), and
  `mnemos forget`, which it called future work.
- What can leave the machine is named whole: the cue's judge (Jev, off unless
  switched on, which sends a message and at most six memory lines to
  api.typesafe.ai), the `claude-cli` provider, and what `identity diff` sends a
  chosen provider.
- Turning the cue off runs setup again, so it schedules upkeep unless
  `--no-upkeep` is given and asks about quiet hours again if they're off; the
  docs now say so.
- Installing: Python 3.10 or newer, the embeddings' size, and that the hooks
  call `mnemos` by its full path, so it belongs somewhere it will stay.
  `SETUP.md` installs the `embeddings` extra as the README does.
- The platforms are stated: the quiet hours and scheduled upkeep need macOS or
  Linux.
- `mnemos log` can be kept beside the chat, in a harness's own browser.
- Examples no longer name the people and apps Mnemos was built with.

No code changed.

### The capture tool's example names no one

`mnemos_capture` tells every agent what an impact is with an example, and the
example named the person Mnemos was built with: "Riley corrected me twice on
the same thing". An agent working for anyone else read a stranger's name in
its own tools. It now reads "They corrected me twice on the same thing".
Nothing else in what a client is shown changed.

### An agent that signs its memories wakes on Windows

On Windows, from its second session on, an agent that signs its memories got
"Error executing tool mnemos_context" instead of its wake. To show the newest
quiet hour once, the wake asks the hours' runner (`mnemos.life`) where an hour
keeps its records. That module locks with fcntl, which Windows lacks, so it
can't be imported there, and the wake imported it one line above the guard
that turns any failure there into "no hour". Now the import is inside that
guard, as the log page already had it: on Windows the wake shows no hour, as
it should where hours can't run. `mnemos life` there now says in one sentence
that the quiet hours run on macOS and Linux, where it failed with a traceback.
0.4.0 has the bug too; the wake learned to show an hour in #118.

The Windows black box never signed, so it never reached that wake. Now it has
the agent wake as itself, the wake every agent that signs gets from its
second session on. On 15c30c1, with the hours' runner made unimportable as on
Windows, the two new tests fail (the wake on the import, `mnemos life` with a
traceback) and so does the black box, at that wake. No schema change, and the
code version stays 23.

### A note from you, not only a reply

You could answer the agent's notes (`mnemos notes reply`) but not start one.
Now `mnemos notes write TEXT` leaves the agent a note of your own, with the
same scope options and the same rules as a reply: your words exactly as
given, kept as yours (never signed as a model's), empty or blank text
refused, at most 16,384 characters, and refused inside one of the agent's
quiet hours. It prints the stored note; with `--json`, the same item as
`notes --json`. `mnemos interface` answers the same as `note` (`text`), and
writes nothing else. Like a reply, neither is ever the first thing to make a
store.

The agent wakes with your note once, through the replies' path, said as yours:
"Riley left me a note (2 hours ago): ...", its id in the closing section to
answer it with `mnemos_note(..., in_reply_to=...)`. It is marked delivered
when shown, as a reply is. `mnemos_note` stays the agent's: no tool the agent
calls can write as you, and a test pins it. Nor can an agent's own shell:
with `CLAUDECODE` or `AI_AGENT` set, `notes write` and `notes reply` refuse
("These are the person's words, so an agent's shell can't write them. Leave
your own note with mnemos_note.") and save nothing, where `remember`,
`correct` and `forget` write as the agent. The interface's `note` and `reply`
are unchanged: the interface is the person's app's channel. The health card
now counts "replies and notes not yet delivered".

`notes --json`, and the interface's `notes`, `reply` and `note`, now give your
replies and notes `delivered_at`: when the agent first woke with it, null until
then. Additive only: no field was renamed or removed, and the agent's own
notes are exactly as they were. Code version 23: a session still running older
code would show your note as a reply to "a note"; now it no longer marks it
delivered, so the newer code delivers it once more, as yours. Nothing leaves the machine.

### A session's first save doesn't wait for Mnemos to open

A server opened its runtime on its first tool call: the store's checks, the
meaning model's libraries and the model itself. On a copy of a real store a
fresh server's first capture took 1.7 s twenty seconds after the server
started, and the next took 0.1 s; on a busy Mac the first took 12 s. Now a
server opens its runtime in the background as it starts, where the prompt
hook is in use (the rule the cue answerer already follows for its model) and
the store exists: twenty seconds in, the first capture took 0.16 to 0.22 s. A
call that comes while it is still opening waits for it, as it waited for its
own opening before. Opening counts no session and runs no maintenance; a
server whose store doesn't exist yet makes none.

Every index in a process now shares one copy of each local model, and encodes
with it one call at a time. The runtime and the cue answerer each loaded their
own, about 50 MB more a server; a server that had saved and recalled held 40
to 70 MB less with one copy.

### Quiet hours that are safe to have on for anyone

**Breaking, for hours that read folders.** Three things in the quiet hours
were safe only on the machine they were made on, and an app that runs Mnemos
for people, like Ghost, may keep the hours on for everyone:

- An hour ran `claude -p` without `--setting-sources`, so the person's own
  Claude Code settings loaded into the agent's hour, their hooks among them,
  another Mnemos's included. An hour now passes `--setting-sources project`
  with its own `--settings` and `--strict-mcp-config`, as Mnemos's model does
  (`mnemos/llm.py`). Its wake still comes from Mnemos's own hook.
- Every hour could read two folders named in the code, one of them
  `~/Documents/Repositories`, on any machine that had them. The folders an
  hour may read now come from Mnemos's config, `life.read_dirs`: a list, each
  relative to the home or absolute, and none unless it names them.
- The budgets were fixed in the code. Mnemos's config sets them for each kind
  of hour (`life.minutes.mine` and `.ours`, `life.token_ceiling.mine` and
  `.ours`), and an app sets them for the one hour it runs with
  `MNEMOS_HOUR_MINUTES` and `MNEMOS_HOUR_TOKEN_CEILING`, which win over the
  config; `mnemos life --max-minutes` and `--max-tokens` still win over both.
  The defaults stay 60 and 30 minutes, 400,000 and 200,000 tokens. A budget
  that isn't a number above zero (a whole one, for tokens) runs no hour, and
  the hour's record says which setting and why.

Everything an hour writes (its record, its folder, the studio, what Claude
said) already went under the home it runs with, and a test now holds it
there: an hour run from another folder, with a home of its own, puts all of
it under that home and nothing in the folders around it. Setup's question now
says the hours are "up to an hour a day", and what every client is told, the
README, `SETUP.md` and `docs/privacy-security.md` say what goes to Anthropic
with the quiet hours on, and how to turn them off.

Nothing the agent writes configures Claude Code for its next hour. An hour
works in its studio, which it may write, and Claude Code loads a project's
settings from there: a hook the agent left in one hour would have run,
outside the sandbox, at the start of the next (so it was before this change
too). Before every hour Mnemos moves the studio's `.claude/settings.json` and
`.claude/settings.local.json`, if any, aside into that hour's folder
(`set-aside/`), and the hour's record names them (`set_aside`, there only
when something was moved); and the hour may not write in `.claude/` in its
studio or in any folder it reads. An hour run under a HOME that isn't the
account's own is denied the keys and credentials of both homes. And a job
`mnemos daemon install` or setup schedules under such a HOME carries it, so
the job runs where it was installed, not in the account's own home; `mnemos
daemon uninstall` under the same HOME finds it.

On 4c61494, with the test suite's fake claude recording what it was given,
the new tests failed: no `--setting-sources`, a folder the config didn't name
handed to the hour, the config's and an app's budgets ignored, and the
instructions silent about the hours. On the change's first version, Claude
started with settings planted in the studio, and jobs installed under
another HOME carried none. An hour for a store whose config names those two
folders is given the same arguments as before, with `--setting-sources
project` added.

**Migration.** For an hour to go on reading folders it read before, name them
in `~/.mnemos/config.json`, for example
`{"life": {"read_dirs": ["Documents/Repositories"]}}`.
No schema change: the schema stays 18 and the code version 22.

### A failed save leaves nothing behind

Most of the store's writes committed when they finished and never rolled
back. When one of their statements failed (a full disk, a lock, a
constraint), the transaction Python had opened for it stayed open on the
store's connection, holding the write lock. No other process could write;
the next write that began its own transaction failed with "cannot start a
transaction within a transaction", so a running server could refuse saves
until it restarted; and the next write that did not committed the failed
write's first statements with its own. On a scratch store, with one
statement made to fail, a memory being archived kept its archive row while it
stayed active, a note being replaced left two notes in use, and a failed
vector write left the store locked against every other writer.

Now every write the store makes runs in one transaction that commits, or
rolls back before the error reaches its caller, and a write made of others (a
note's replacement and the retiring of the old one) lands whole or not at
all. So do the writes maintenance and reflection make on the store's
connection themselves (a plain question set aside for a lesson's, a
reaffirmation asked again, words kept on a question that stays open): one
that met a lock used to leave the connection inside a transaction until some
later write happened to commit it. Opening a store, and the meaning index's
own writes, roll back the same way. Callers get the same results and the
same errors as before; what changes is that a failed write leaves the
connection clean and nothing of itself in the store. A write that finds the
connection already inside a transaction it did not open now fails, rather
than committing or discarding that transaction.

No maintenance rule changed; the schema stays 18 and the code version 22.

### A saved capture never reports failure, and one maintenance cycle runs at a time

A capture saves its memory and its note in one transaction, then does its
bookkeeping: two meta values, its vector, its maintenance. When one of those
later writes met another process's lock, the capture raised "database is
locked" although the memory was kept, and an agent told its capture failed
captures it again. On a scratch store, with the lock forced on that meta
write, the capture raised with its memory and note saved, and the call's
trace row was lost.

Now everything after the save is bookkeeping, and it never fails the call: the
first failure stops the rest, is logged once, the failed write's transaction
is rolled back, and the call answers with what it saved, its maintenance line
saying "not this time" and why. A correction, a handoff and a journal entry
keep the same rule for what follows their saves. Inside a host mutation
nothing has committed yet, so a failure there still rolls the whole operation
back.

The scheduled job (`mnemos consolidate`, and `--deep`) took no claim on the
memory's maintenance, and the activity gate a capture asks reads the cycle
log, which a cycle writes when it ends. So a capture during the job's cycle
started a second cycle beside it: on a scratch store, a capture made while the
job's cycle ran started one in the background, which ran and finished inside
the job's. Now the job holds the claim a capture's maintenance takes while it
runs, and gives it up when it ends, even when its cycle fails. A capture that
finds it held starts no cycle ("another process is running this memory's
maintenance now"), and a job that finds a capture's maintenance running runs
none and says so; its next run does. A claim carries a token, and only the
token that took it gives it up: a cycle that ran past the claim's fifteen
minutes, and finds a newer claim when it ends, leaves that claim in place.

No maintenance rule changed, and the code version stays 22.

### Your memory, from your own app

An app that shows a person their agent's memory (Ghost's home is the first)
could read the journal and the notes with `--json`, and nothing else. Now it
can read and search the memories, and correct or forget one, with every
command taking the usual scope flags and printing one JSON object with
`--json`. Errors are one plain sentence on stderr, with a non-zero exit. Times
are ISO 8601 UTC.

- **`mnemos memories --json`** lists the active and dormant memories, oldest
  first: `{"memories": [...], "counts": {"active", "dormant", "archived"}}`.
  A memory has its `id`, its `words`, when it was `kept` (its first version,
  followed back through its corrections) and `corrected` (this version, when
  a correction made it, else null), its `state`, how `alive` it is (its
  accessibility, the value decay lowers and a return raises, and the one its
  states follow: in practice up to .8), the `conversation` it was kept in
  (`{"id": <session id>, "title": null}`: Mnemos keeps no titles), its
  `impact`, and its `author`: agent, person, tool (Mnemos's own templates and
  imports count as a tool's) or unknown. `--state active|dormant`,
  `--limit N` and `--offset M` page it, and `counts` is always the whole
  scope's. It reads the rows the log reads, through the log's own reading,
  never writes, and never makes a store.
- **`mnemos search --json [-n N] QUERY`** gives `{"query", "results": [{"id",
  "words", "kept", "closeness", "found"}]}`, closest first. `found` is
  `meaning` (whenever meaning matched), `words` or `link`, as recall's rows
  mark it, and `closeness` is recall's own score over the best result's: the
  first is 1.0, the rest fall with the order, and it means nothing across two
  searches. Nothing close is no results, by recall's own thresholds.
- **`mnemos correct [--json] ID TEXT`** and **`mnemos forget [--json] ID`**
  (below) give `{"id": <new>, "replaces": <old>, "corrected": <time>}` and
  `{"id", "state": "archived", "forgotten": <time>}`.
- **`mnemos interface`** answers all of these, and `journal`, `notes` and
  `reply`, from one long-lived process: one JSON request a line on stdin
  (`{"id": 1, "command": "search", "query": "...", "max_results": 10}`), one
  JSON line an answer on stdout, `{"id": 1, "result": <exactly what the
  one-shot --json prints>}` or `{"id": 1, "error": "<one sentence>"}`. It
  loads the meaning model once, in the background as it starts, and ends when
  stdin closes. On a copy of the maintainer's store (1,245 memories in scope,
  21,564 passages), a one-shot `search --json` took 2.9 s, nearly all of it
  the model; the interface answered a first `memories`, `journal` or `notes`
  0.09 to 0.15 s after it started, a first search in 2.6 s, and warm searches
  in 61 ms (the median of 80, 130 ms at most).

### `mnemos search` looks, and changes nothing

A search counted as a return. The command called recall's retriever with
reinforcement on, so every memory a person's search found was woken,
strengthened and linked as co-activated with what came back beside it: the
agent's memory moved because someone looked through it. The command also
opened the store for writing, which makes a store that isn't there, and it
searched by words alone, with no meaning index.

Now it is the agent's own recall, by meaning and by words, over the memories
alone (no handoffs, notes or journal), run read-only: nothing it finds is
woken, strengthened or linked, an archived memory never comes back, and a
store that isn't there stays so. A test finds a dormant memory and checks
every engram row, link, session reinforcement and meta value, and the file
byte for byte. Without `--json` it prints as it did. The agent's recall and
the cue are unchanged: what the agent is shown is still a return.

### The person corrects or forgets, and the agent is told

`mnemos correct` and `mnemos forget` decide whose they are as `mnemos
remember` does: in an agent's own shell (`CLAUDECODE` or `AI_AGENT` set) or
with `--signed-as` they are the agent's, signed as its corrections are, and
otherwise the person's.

- **The person's correction** writes their words unsigned, as `author_kind`
  'person', and supersedes the memory exactly as the agent's correction does:
  the link, the lineage both ways, the version keeping the old words. The new
  one keeps what the old one meant, and its standing mark. The agent's next
  full wake says it once, under "while i was away": `- Riley corrected a
  memory of mine; it now says: "..."`.
- **The person's forget** is the agent's own forget, with the person as the
  one who forgot: the memory and its note are archived together (archive
  reason `forgotten_by_person`), never deleted, and nothing is written in
  their place. Recall never brings it back, by its words, its meaning, its
  id or the archive, and neither does the cue or maintenance. The agent's
  next full wake says once that its person let it go, and when, never the
  words and never an id: `- Riley let a memory of mine go on Oct 18; its
  words went with it.`, or `- Riley let 3 memories of mine go, on Oct 18 and
  Oct 19; their words went with them.` (meta `person_letgo_shown_at`). The
  line is never left out for room. An agent's own forget never counts.
- **They act on what the person saw.** An id that is unknown, archived, or
  replaced by a correction since changes nothing, and says which in one
  sentence, naming the version in use now.

The mind's tools, the cue and maintenance work as they did, and the code
version stays 22.

### Meaning stays on this machine unless you choose Gemini

**Breaking.** A GEMINI_API_KEY anywhere Mnemos looks (the environment, the
working folder's `.env`, or `~/.mnemos/.env`) was enough to switch meaning
search to Google's Gemini API, with no Mnemos setting at all: the words of
every memory it indexed, and of every question recall and the cue asked by
meaning, went to Google. Many people keep that key for other tools, and a
mind that runs in a home folder with one in `~/.env` sent its memory out.
Mnemos's model has waited for the person's choice since 0.4.0; now meaning
does too. It is local unless the person chooses Gemini for Mnemos, with the
key set: `MNEMOS_EMBEDDING_PROVIDER=gemini`, in the environment or a `.env`
file Mnemos reads, or `{"embeddings": {"provider": "gemini"}}` in
`~/.mnemos/config.json`. A key on its own chooses nothing. Gemini chosen
without a key is local, never off and never another service, and a provider
Mnemos doesn't know (it knows `local` and `gemini`) is local too, said once in
the log. In code, `EmbeddingIndex(provider="gemini")` chooses, and
`gemini_api_key=` on its own doesn't. `mnemos doctor` has a Meaning line:
which provider meaning uses, its model, and why; when a GEMINI_API_KEY is
there but not chosen, it says that Mnemos doesn't use it, that meaning stays
on this machine, and how to choose Gemini.

**Migration.** Nothing to do to stay local. A store Gemini indexed keeps its
Gemini vectors, filed by model. The local model's are built beside them as
Mnemos keeps its index up (a little with each capture, more with the scheduled
upkeep, or all at once with `mnemos embeddings index`); until a memory has
one, recall finds it by its words. To go on with Gemini, set
`MNEMOS_EMBEDDING_PROVIDER=gemini` beside the key, and its vectors are used
again. Until then, `mnemos repair dead-embeddings --write` would prune them,
as it prunes the vectors of any model not in use.

### A capture answers before its maintenance runs

A capture that came due for maintenance (five minutes after the last cycle,
in a store every session shares) ran the whole cycle before it answered. In a
session on Oct 17 2026 two captures took 36.5 s and 37.1 s; by their own log
the cycles took 35.5 s and 35.1 s and changed nothing. While a cycle wrote,
other sessions' captures waited behind it, up to 7 s on a copy of the same
store, and one lost its vector to "database is locked".

Now automatic maintenance, the kind a capture or a correction asks for, runs
in a process of its own, started by the call and detached from it, at a low
priority, one at a time per scope. Before it answers, the call still catches
recall's meaning index up, so what it saved is findable by meaning. If the
process can't start, the cycle runs in the call as before; if it fails, the
next capture says what went wrong. `MNEMOS_MAINTENANCE=inline` runs it in the
call, as before. An explicit `mnemos_maintain`, `mnemos consolidate` and the
scheduled jobs run as they did. What a cycle asks the agent (what a memory
changed, what a lesson taught) is queued when the cycle finishes, a few
seconds after the call rather than in it.

The cycle writes only what it changed. Decay saved every memory it read,
whole (its row, its word index entry, every link), each in a write of its own,
and softening saved every memory it looked at, softened or not: about 1,700
writes a cycle, for changes in the fourth decimal. Decay now writes the four
numbers it moves, for the memories whose numbers moved, in one transaction,
and softening saves only what it softened. On a copy of the store, decay went
from 3.5 s to 0.11 s, softening from 3.1 s to 0.07 s, and the cycle from
10.8 s to 4.2 s, with the same results. A session's captures during two cycles
took 0.06 to 0.11 s.

Sessions keep the code they started with, so a session already running keeps
the old behavior until it restarts.

### Recall shows what it finds, and says when

The lab's side-by-side put plain memory files against Mnemos on 118 facts from
two years of real work: files 48.5, Mnemos 41.5. A replay of Mnemos's own
recall calls said why. Its rows hid what it found: the right memory came back
for 42 facts, but its 300-character row held the fact for 26. Its lists were
short: at 20 rows the right memory came back for 59. And nothing said when: 7
of its 12 wrong answers had a newer memory holding the fact in the store.

Now a memory's row carries its words whole, up to 2,000 characters, and the
day it was kept. The recall tool asks for 15 rows on a question about the
past, and for more than one search, in other words too, and says the newer of
two memories that disagree usually holds; a call that gives no number gets 10.
Replayed on the same calls, rows showed the fact for 41 of the 42 facts recall
reached, and at 15 rows the right memory came back for 59 and showed for 57.
Handoffs, the journal and notes keep their 300-character rows.

### The cue counts the messages too short to look at

A message with fewer than four meaningful words gets nothing from the cue: on
so few words a match is mostly chance, and most are "yes" or "go ahead". The
skip left no trace, so nothing could say why such a message got nothing. Now
each one is counted in the session's file, apart from the messages the cue
looked at, and the health card's cue line says how many there were.

### A clean way out

Setup writes hooks into Claude Code's settings and Codex's hooks, registers
the server with Claude Code, Codex or Claude Desktop, and schedules jobs, and
until now only the jobs could be removed. `mnemos uninstall` says what it
would remove, and `mnemos uninstall --write` removes Mnemos's own hooks,
server entries and jobs. Anyone else's stay, and so do the memories: they're
the agent's, and it says where they are.

### The local model loads without printing at you

A first `mnemos embeddings download` printed a torch notice about a feature
Mnemos never uses, a "Loading weights" bar and the Hub's "Please set a
HF_TOKEN" (Mnemos needs no account). `mnemos doctor` printed "BertModel LOAD
REPORT ... UNEXPECTED" for a harmless unused weight, and the server's log drew
a "Batches" bar for every capture and recall. All of it is quiet now; a
download's own progress and any real error still show.

### A quiet hour wakes its memory's own model

Every quiet hour ran Opus 5.5, so a memory that was mostly another Claude
model's had Opus waking in it, on its person's plan. An hour now wakes the
memory's own model, the one that signed most of it. A memory that's mostly
another kind of model's has no hour, since the hours run Claude Code. One with
nothing signed yet keeps Opus 5.5. MNEMOS_HOUR_MODEL chooses.

### The Hermes provider writes nothing in the agent's place

Provider Mode wrote memories by itself. A turn was copied word for word as a
memory whenever its message held "remember", "don't" or "actually,", and so
was any long reply that said "fixed" or "added"; the end of a session and the
moment before compression each stored up to five more such copies; every
delegation and session switch left a record; and `SOUL.md` was copied in as
the agent's identity. Each went through the agent's own capture, so each was
stored as the agent's own words. On one real Hermes memory, 233 of its 303
memories had been written that way. Now the provider only reads (the wake,
and recall before each turn), keeps the memory's upkeep, and keeps in Mnemos
what the agent itself writes into Hermes's built-in memory; the agent writes
the rest with its own tools. The `auto_capture`, `auto_bootstrap`,
`auto_session_distill` and `capture_uncertain` settings are gone, and a
`mnemos.json` that still has them is read without them.

What the provider wrote before is labelled a tool's, on a store from before
authorship was recorded and, once, on one after, so it never makes the agent
who it is. Recall marks a tool's words "from a tool, not yours", as it marks
the person's.

### OpenClaw's printed jobs no longer write the agent's memory

`mnemos bootstrap` printed OpenClaw jobs that ran another model, a hard-coded
`claude-sonnet-4-5`, as an Observer every 30 minutes and a Memory Maintenance
agent every six hours. Each read the agent's transcripts and rewrote its
`memory/active-context.md` and `MEMORY.md` in that model's words: the
transcript indexer's flaw again, in files. A third asked a model to run a
command that does nothing. All three are retired. The morning brief and daily
debrief remain: they run as the agent itself and write reports for the person,
not memory. The OpenClaw guide is marked legacy; it was written for the
advanced server, and `mnemos setup-openclaw`'s jobs ask for tools the default
simple server doesn't have.

### The doctor says ATTENTION only for what to act on

It flagged questions the agent had left unanswered whenever any went
unanswered, though the waking note tells the agent to leave one when nothing
true comes, and it went on flagging an hour after an answer. Now it flags them
when answering has stopped (none answered in the last week), which is how
questions that never reach the agent look; otherwise they're counted on the
card's line. And a cue that timed out on a busy machine was flagged at a
twentieth of the week's messages, followed by "nothing to fix". Timeouts and a
busy store, which pass on their own, are now flagged only at a quarter, a cue
that mostly isn't answering; a failure something fixes still is at a twentieth.

### A link goes only by a verdict that says so

With a provider chosen, maintenance's linking pass sends a memory's
mechanically formed links (`supports`, `co_activated`) to the model to be
retyped. It read every link missing from the model's typed verdicts as one the
model had called unrelated, and removed it. A call that raised, an empty
reply, and a usage-limit message (the `claude-cli` provider hands back
whatever the command printed) leave every link missing, so each removed every
link the pass had sent, and the cycle was logged as a success. Nothing was
retyped in such a cycle, so the batch limit (`reclassify_batch_size`) never
stopped it: the pass went on through every memory it had loaded, up to 200
with the defaults. A fork of this pass removed 6,321 links from one agent's
store over three cycles. And a link the model did call unrelated took every
other link between the same two memories with it, typed ones no verdict had
been asked about.

Now a link is removed only when the reply calls it NONE explicitly: by its
exact id, with a confidence from 0.5 to 1.0, and nothing else said about it.
Only that link goes, not the pair's others. A link the reply left out, or
judged in a way that can't be read, stays as it was. A reply that can't be
read at all ends the pass for the cycle, and `mnemos consolidate --deep` says
so, and why, on its Connections line ("reclassifying stopped, links left as
they were: the reply was empty"); the cycle's log keeps it
(`reclassify_stopped`). The line also says when a cycle removed links.

The model is given to deep cycles only. `mnemos consolidate`, which the
scheduled job runs every four hours, the bridge and the advanced tool gave it
to shallow cycles too, so with a provider chosen the pass called it every four
hours; a session's maintenance already gave it to deep cycles alone. A shallow
cycle's log no longer says a provider assisted.

A reply that holds no object, or is no text at all, no longer raises out of
the classifier, where it failed the pass and, at save time, the capture.

The code version is 22, so a session or job still running the code before
stops maintaining a store this code has opened, rather than removing links by
the old rule.

### A session wakes to its own folder's thread, and sees every live one

When several sessions work at once, each leaves its own handoff. A new session
was handed the newest one whole and two more as short lines, and on a lived-in
store even those two lines were the first thing the briefing cut for room: on
one real store, with eight threads left in fourteen hours, a new session woke
with one. And the handoff shown whole counted against the same room as
everything else, so a long one (4,800 characters) pushed out the beliefs, what
had been changing and the waiting question.

Now:

- A handoff records the place it was written: the repository its session
  works in (a worktree counts as its repository), else the folder.
- A session that left a handoff gets its own back first, as before.
  Otherwise it gets the newest handoff written where it works, or in a place
  whose name shares a word with it (`mnemos` and `mnemos-site`). Only
  when there is none does it get the newest overall.
- Every other handoff left in the last three days follows as one short line,
  this place's first, so a session that coordinates the others sees them all.
- The handoff shown whole takes no room from the rest. Besides it, the
  briefing holds up to 8,000 characters (it was 6,000; the hook's default
  `--token-budget` is now 2000), and the other threads' lines are cut short
  before anything leaves.

Handoffs written before this have no place yet. Each one gets its place the
next time its session writes its handoff again.

### Meaning search no longer switches itself off at the start of a session

Loading the local embedding model takes a few seconds, and two parts of a
session start it at nearly the same moment: the cue's index, in the
background, and recall's. The check marked itself done before the model had
loaded, so the second one found it done with nothing available, and recall
searched by words alone for the rest of the session. Nothing said so. In a
test of 62 sessions, 47 lost meaning search this way. Now the second waits for
the first to finish, and gets the model.

When meaning search is off and the memory holds vectors it can't use, recall
now says so on every answer, with the reason, including when it found nothing:
a "nothing found" from words alone isn't a full search. A setup without the
package and without vectors is keyword-only by choice, and recall says
nothing of it.

### An old memory that answers the question is no longer found at half strength

A memory nobody has recalled for a while goes quiet (dormant). Recall still
found one that matched the question, but started it at half the score of an
active memory with the same match, and a link lit it at half too. So a newer
memory that only brushed the question came first: "ferry timetable kitchen
drawer" scored a year-old memory that says exactly that at 0.5, and a newer
one that shares two of its words at 0.98. In a store used for months, most of
what is older than three months is quiet: on one real store, of the memories
from two summer months, about 5,600 were quiet and fewer than 500 active.

In a lab replay of the recall calls real sessions made, the memory holding
the answer was found for 6 of 29 facts from a year before; at its full score,
for 10. Across all 114 facts it went from 35 to 42, and the facts held by
active memories were found as often as before (29 of 68).

Now a quiet memory competes on its match, as an active one does. Going quiet
still says how long since it was used: it relays nothing until it wakes, at
most ten of them are drawn into one recall, and a returned one wakes.

### A recall row shows the part of a memory the question is about

Each row of a recall carries the first 300 characters of a memory, so the
answer to a question often wasn't in it when it sat further in, and the
agent had to fetch the memory by its id to see it, or went without. In the
same lab replay, the facts sat past the first 300 characters of the memory
holding them for 62 of 105, and of the 35 facts whose memory recall found,
20 never showed in its row.

Now, when a passage further in holds a word of the question the opening
doesn't, the row shows the first 120 characters, " … ", and that passage: a
few whole sentences, as meaning search reads the memory. A row whose opening
holds every word the question matched reads as before. Handoffs, journal
entries and notes in recall's answer are shown the same way.

### The local model runs on the CPU, and takes a fifth of the memory

Every session's Mnemos server loads the local embedding model. Left to choose,
it took the GPU on a Mac, where one process held 2.2 GB and embedded a message
in about 35 ms; on the CPU it holds 0.46 GB and takes 5 ms, and the vectors
are the same (cosine 1.000000 against those stored from the GPU). On one
36 GB machine with fourteen sessions open, the servers held 26 GB between
them and sat in swap while idle, and the cue's answer, which has to be paged
back in before it can answer, missed its window on 260 of 627 messages. Now
the model runs on the CPU, on at most two threads, so that many servers at
once share the cores: one message takes the same 5 ms on one thread as on ten.
On a copy of that store, a server answering the cue holds 433 MB, and its
answers took 63 ms at the median and 106 ms at the most.

### A session's first message is answered by meaning

A session's answerer opens only once its model has loaded, seconds after the
session starts, and the first message nearly always comes sooner, so it was
answered from words alone: on one machine in a week, 4 of 155 sessions had
their first message answered by meaning. Now, until a session's own answerer
is up, the cue asks another session's answerer for the same store and scope.
It is asked what the session would ask its own, what the session was already
shown left out, so it gives the same answer. Of several, the cue asks the one
that answered last, the likeliest to be awake: an answer now marks its
socket's time, which connecting and reading leave as they were. A socket
nothing answers on is passed over, and an answerer for any other store or
scope is never asked. An offer answered this way says so (`"answerer":
"another session"`). On that machine, finding and trying every other
session's socket (38 of them, 12 live) took under a millisecond.

## 0.4.0 (2026-10-08)

The agent gets a life of its own between your conversations, and only the
agent writes its memory.

- It keeps a journal and can leave you notes, and only it writes them.
- If you say yes at setup, it has quiet hours: an hour a day that's its own,
  and half an hour for the day's work.
- With each message you send, the memories that may bear on it come back to
  the agent (the cue). It's on by default and stays silent on Claude Code's own
  notices.
- `mnemos log` opens a small page on your machine to watch its days.
- A model never writes in its place. Its beliefs move only by its own verdict.
- Retired: the substrate and the transcript indexer, which wrote memories in a
  model's words, and the contradiction question, which paired memories by
  words they happened to share.
- Advanced mode only adds tools now. It switches nothing off.
- Memories link by meaning on every path that links them, and recall follows
  those links further, so a memory that has faded can come back by
  association.
- When the cue can't bring anything in time, it says why instead of failing
  quietly.
- A note becomes a memory only when the agent kept coming back to it, never by
  a score its words were given.

Each change is told in full below.

### Links by meaning, by every path that makes them

How a store's memories were linked depended on which path ran maintenance.
`mnemos consolidate`, which the scheduled jobs run every four hours and at
night, gave the linking pass no embedding index, so it linked by words alone
and never read `similarity_threshold`; a session's maintenance gave it one and
linked by meaning too. And the pass's search by meaning read only the
whole-text vector a capture writes (`embeddings`), while recall reads the
passages (`passage_vectors`), so a memory indexed only as passages could never
be linked by meaning: 139 of the 554 live memories on a copy of the
maintainer's store, and 2,890 of 6,654 on a copy grown to twelve times its
size.

Now `mnemos consolidate`, with or without `--deep`, gives the cycle the index
a session's maintenance uses, built one way for both (`maintenance_index`). A
quiet hour already maintained through its own Mnemos server, as a session
does. The pass searches the way recall searches (`search_candidates`): each
memory by its best passage, less the length penalty, with the memory's own
words as the query, among only the memories it may be linked to (live, in its
scope, not itself, not linked to it yet). It reads the passages alone and no
longer reads `embeddings`, so a memory with a whole-text vector and no
passages yet is linked by meaning once it is cut into passages (within a
write's budget, by the scheduled job, or by `mnemos embeddings index`). The
bar (similarity 0.7), the relation, the strength, the caps and the words path
are as they were. Without the model the pass links by words, as before, and
says why: `mnemos consolidate` adds "links by words only: meaning search is
off (…)" to its Connections line, the cycle's log keeps it, and nothing tries
the network.

Measured on copies. On the maintainer's store, `mnemos consolidate` made no
new link before and 9 after, all by meaning, the same 9 a session's
maintenance now makes (it made 1 before); the command took 18.9 s instead of
12.4 s on a busy machine, the difference its 100 searches by meaning (both
load the model once). On the copy twelve times its size, with the cap raised
so that one pass reaches all 6,300 under-linked live memories, the pass made
18,771 links through the command, all by words, and 19,896 through a
session, 4,239 of them by meaning; now both paths make the same 20,540,
17,177 by meaning (12,310 of them to memories the old search could not
reach) and 3,363 by words. The words' share fell because the pass still makes
at most five links a memory, the ones found by meaning first. Code version 21.

### Promotion by lasting attention

A note with no memory of its own became one by a score: the confidence and
salience its words were given, and either one revision or the mark
"foundational", which let a note through unrevised. It took notes in anyone's
words but Mnemos's: setup's line around the person's own answer, a note whose
writer nobody recorded. On the maintainer's store it never fired: no memory
there was ever promoted.

Now a note becomes a memory because the agent kept coming back to it. The
agent revised it at least once (a revision its model signed) and recalled it
in at least two sessions. Recalled means a recall in a named session showed it
alone: asked for by its id, which is how the agent draws on a note it was
shown, or the only thing its query found. Returned among other rows, offered
by the cue or shown in the briefing, it was not used. Both numbers come from
what the store already keeps, the note's revisions and `memory_trace` (90
days of calls), so nothing new is recorded. Only the agent's own notes
qualify, and the memory holds exactly the note's words, its meaning left for
the agent to give. How sure or salient its words were scored, its age and its
length decide nothing. At most three a cycle, the most used first.

A capture's note is its memory's from the start, so what can still become a
memory is a note written another way: a session the advanced console closes
with the agent's synthesis, an answer older code kept for later, a note an
integration wrote. The simple tools never revise a continuity note in place (a
correction writes a new pair), so a note qualifies only once it has been
revised through the advanced console.

On a fresh copy of the maintainer's live store (2026-10-07) no memory had
ever been promoted. In `claude-code/user/global` all 475 continuity notes are
captures, paired with their memories, so neither rule finds anything there,
and a cycle on this code and on the previous one promoted nothing. The file's
only candidates by the old rule were 10 notes in another agent's scope,
`claude-field/user/global`, whose writer was never recorded, with unsigned
revisions and no recorded use: a cycle there on the previous code made 3 of
them memories of unknown authorship, one of them never revised; on this code,
none. A note written through the advanced console on a copy (a session closed
with the agent's synthesis), revised with `mnemos_hypomnema_revise` and asked
for by its id in two sessions, each in its own process, became a memory at the
next cycle with its words and no meaning, and came back to a recall in
another process.

The maintenance report says how many notes were ready and how many became
memories, each ready one with its two numbers (revised N times, recalled in M
sessions) and the memory it became. The health card says how many are ready
and how many were promoted, with the same numbers, and its structured result
keeps the rule. `hypomnema_promoted` now counts the notes promotion made
memories of: it counted every note paired with a memory, so each capture read
as a promotion. Code version 20.

### Resonance reaches

Recall's second step, activation spreading through the links between
memories, was nearly inert. A memory split what it sent by its number of
links, every link counted (to faded, archived and out-of-scope memories too),
and each share had to clear a floor on its own; on the maintainer's store,
where most live memories have more than six links, the best match sent
nothing anywhere. A dormant memory could not be reached through a link at
all, so a memory that had faded came back only when the words or the meaning
of a question hit it directly, never by association.

Now a memory shares its activation out whole among its five strongest links,
in proportion to each link's weight; links are walked both ways; what arrives
at a memory is summed before the floor, so faint links that agree can light
what one alone could not; nothing flows back to a memory already lit; and a
dormant memory can be lit through a link, at the same discount a dormant seed
gets, and wakes when it is returned. It relays nothing until it does. Archived
memories take no part, as before. `EngramStore.get_connections_to` reads the
links into a memory. Nothing about how a store is written changes.

### The cue answers, or says why it didn't

On the maintainer's machine the cue failed 18 of 109 messages in a week: 12
counted as timeouts and 6 as `error (OperationalError)`. Both were the hook's
own deadline. It waited up to 0.35 s for the session's Mnemos server to answer
by meaning, and when the server was slow, only then started on words, with too
little of its 0.65 s left on a busy machine. Where it ran out decided the
name: a query still running at the deadline is stopped by SQLite, which calls
that "interrupted", and the hook recorded the exception's class name. No lock
was involved, and none of the scheduled jobs lined up with the failures.

The hook now starts its words answer as soon as the store is open, beside the
question to the server, so a slow, busy or loading server costs a message its
meaning, never the person's time. With the words answer ready, it waits for
the server until 0.1 s before its deadline instead of 0.35 s, and shows
whichever answer is ready then: meaning if it came, else words. The deadline
is unchanged, and so is what the cue offers. A query the deadline stops counts
as a timeout. The hook's reads wait at most 0.1 s on a locked store, are tried
once more, and are then counted as `busy`; the server does the same with its
reads of the memories, and answers "busy" at once instead of waiting up to
5 s. Each session's file now counts failures by kind (`timeout`, `busy`,
`error (<Name>)`), keeps the times of the last 20 of each kind, and says why
each answer by words wasn't by meaning: the server didn't answer in time, its
store was locked, it was loading its model, there was none, it spoke another
protocol, or the socket path under HOME was too long for it to open, which the
server now logs as a warning. The health card and `mnemos doctor` give an
ATTENTION line when the messages the cue could not answer are 5% of the week's
or more, or for any error, any message with no answerer to judge it, or any
answer forced to words by that socket path, naming the kind that dominates and
what fixes it; a few timeouts or busy stores are counted and not flagged. On a
copy of the maintainer's store, with the server stalled and the words answer
as slow as on that machine, 35 of 38 messages failed before and none after;
with the longer wait, a server held up for 0.6 s at each message answered all
38 by meaning instead of none, and one that never answered held each message
0.55 s instead of 0.35 s.

Two things still go uncounted: a hook ended by its own hard stop, and one
Claude Code ends after 2 s, as it would one whose start stalled before its
clock began (7.7 s once in the lab). The hook's side of this takes effect when
the installed checkout is updated; a session's server keeps its old answerer,
with the long wait on a lock and no word about its socket, until the session
restarts.

### The contradiction question, retired

Maintenance used to ask the agent: "This memory surprised you. Does it
contradict an earlier one: …?" It couldn't work. Without a model, a memory
surprises when nothing like it is held, and the question then paired it with
whichever memory shared the most words with it. A memory with nothing close
to it has no real neighbour, so the pair was a coincidence of common words.
On the maintainer's own store, all 5 answered questions were "not related",
and 46 sat unanswered.

Maintenance no longer asks it. The next time it runs on a store, it removes
the ones still waiting (one the agent had already written on is closed with
its words instead), and until then the wake, the health card and
`mnemos log` never show them. Answered ones stay as history. An agent that
answers one it was shown before is told the question is retired; its words
are kept with the question, and nothing is linked or changed. A memory that's
wrong already has its own path: `mnemos_correct` replaces it and names the
other notes that still say the old thing. Links between memories that
contradict each other, and the surprise that makes a new memory stronger,
are unchanged. Code version 19.

### What setup turns on

Setup now turns on what a newcomer needs, and says how to turn each thing off.
`mnemos hooks install claude-code --write`, the last step for Claude Code,
installs the cue with the wake (`--no-prompt` leaves it out, and takes out one
an earlier install added; `--prompt` is still accepted and changes nothing),
and schedules upkeep between sessions (`--no-upkeep` leaves it out).
`mnemos hooks install codex --write` schedules the upkeep too, and so does
`mnemos mcp install claude --write`, which is all of Claude Desktop's setup.
With no model chosen for Mnemos, upkeep runs local passes only: the scheduled
jobs, run with provider keys in the environment and the network caught, tried
to reach nothing, and with a model chosen they reached only it.

### Quiet hours, on a schedule

`mnemos life` ran only by hand. `mnemos daemon install --hours` schedules the
agent's own hour daily at 08:00 and the half hour for the day's work at 19:00
(`--mine-at` and `--ours-at` move them), and `mnemos daemon uninstall --hours`
takes off only them. Setup asks once, at a terminal, and yes is the default:
"Quiet hours give the agent an hour a day that's its own, and half an hour for
the day's work; they run Claude on its own and use your Claude plan." Without
a terminal it schedules nothing and says how; without a `claude` command it
says that. Each hour's job carries what a background job lacks: the `claude`
command's folder on its PATH, both commands' full paths (`MNEMOS_CLAUDE_BIN`,
`MNEMOS_LIFE_MNEMOS_BIN`) found at install, and the Claude login the person set
(`CLAUDE_CONFIG_DIR`), if any. `mnemos daemon status`, `mnemos doctor` and
`mnemos log` show them; the log now reads a systemd user timer too, which is
what the hours are where systemd runs.

### The cue hears only the person

Claude Code sends the prompt hook messages it writes itself: a background
task's notice (`<task-notification>`), a slash command, the `!` shell's input
and output, a local command's caveat and output, a CI monitor's event. The cue
answered them as if the person had written them. Now a message that starts
with one of those tags gets nothing and counts as nothing. Only those tags
count, so a message of the person's that starts with "<" is still heard.

### Background jobs on a Mac

macOS doesn't let background jobs read `~/Documents`, `~/Desktop` or
`~/Downloads`. `mnemos daemon install` warned only when the mnemos command
lived there, so a source checkout there installed in place, with its command
elsewhere, got no warning while every scheduled run failed. Setup and
`mnemos daemon install` now warn when the command or the code it runs is in
one of those folders, and say to install from PyPI or a built wheel. Every job
runs in `~/.mnemos`, and a quiet hour that can't look into `~/Documents`
leaves out its folders there instead of failing. Installing upkeep again keeps
the quiet hours, on a crontab too; `mnemos daemon uninstall` takes off only
what is there, with the copy an install kept of a plist it replaced; and on a
crontab `maintain` no longer counts as scheduled because `maintain-deep` is.

### The transcript indexer, retired

`mnemos index` had a model pull "facts" out of old conversations and file them
as the agent's memories: on one install about 7,000 of them against 13 the
agent kept itself. Only the agent writes its memory. The indexer
(mnemos/indexer), its `mnemos-index-session` command, its tests and its docs
are gone; `mnemos index` says it is retired and why, and exits 1. Installing or
uninstalling the background jobs removes the indexer job the first
`mnemos daemon install` scheduled, as it removes the substrate's tick, and
advanced setup no longer writes a project list for it. What it wrote stays a
tool's words, and `mnemos repair quarantine-tool-written` still moves it out
of recall.

### A small page to watch your agent's days

`mnemos log` opens a page in your browser that shows what the agent does on
its own and what it keeps: its journal, its quiet hours (what each one wrote,
made and reached for, and anything it was refused), the notes it leaves you,
what its memory asks it, its beliefs, and every memory. It finds the memory
the way every other command does, and names the agent by the model that signs
its memories. It only reads: the store is opened read-only and left exactly as
it was, nothing is written anywhere, and the page runs on 127.0.0.1 alone,
with its fonts bundled so it asks nothing of the network. With no quiet hours
yet, or none scheduled, it says so. Ctrl-C stops it. This is the first, small
version of the companion; a fuller one comes later.

### Advanced mode adds to simple mode

Advanced mode is meant to be simple mode plus tools for inspecting and
administering memory, but it switched parts of simple mode off. It served an
older recall in place of simple mode's: one that couldn't look a memory up by
id, had no standing filter, cut each row to 150 characters and waited on
setup, so the recalls an agent makes at the start of a session found nothing.
It never started the answerer the prompt hook asks, so the hook lost meaning
search and its judge, and at shutdown it closed only its own store. Now
advanced mode serves every simple tool unchanged, starts and stops the way
simple mode does, and only adds its own tools. It no longer needs
MNEMOS_ENABLE_EXPERIMENTAL=1 to run or to be installed, and it says once, on
stderr, that it's less tested than simple mode. Its recall no longer takes
agent_id, person_id or project_scope, or mixes in what other agents shared:
a server recalls for its own scope, as simple mode does. To read another
scope, start a server for it (`--agent-id`, `--person-id`,
`--project-scope`) or use `mnemos_context_packet`, and `mnemos_shared` reads
the shared pool.

### A model never writes in the agent's place

The docs already said no outside model softens, reviews or moves what an
agent holds, because that inserts another mind's steps into the self. With
a provider configured, the code did all three:

- a model read every saved memory against the agent's beliefs and moved
  them, up 0.07 per point of support and down 0.04 per point of
  contradiction;
- the daily belief review did the same over recent memories;
- softening let the model rewrite fading memories "in the rememberer's own
  voice" and write the lesson each one taught.

Now a model's reading only weighs the moment: it raises surprise and links a
contradiction to the belief's evidence. A belief changes only by the
agent's own verdict, through `mnemos_reflect`. Belief review is retired,
with its settings. Softening keeps a fading memory's words as the agent
wrote them and asks the agent what it taught. Its mechanical rewording stays
opt-in (`soften_without_model`).

### A model only when you choose one

A provider key in the environment was enough to turn a model on. With only
OPENROUTER_API_KEY set (in a shell, or in the `.env` of the project the agent
worked in), there for some other tool, the second capture's words went to
openrouter.ai, and the model could move the agent's beliefs. Now Mnemos uses
a model only when the person chooses one for it, with MNEMOS_LLM_PROVIDER or
setup's provider question. A key on its own chooses nothing, and a chosen
provider without its key is no provider, never a fall back to another.

### Setup keeps the person's words, and speaks for no one

Advanced setup kept nothing. It named a memory source that doesn't exist,
so every write failed and it said "Encoded 0 seed memories". What it meant
to write wasn't right either: two memories in the agent's voice ("My user is
…", "I am Nova …"), the person's answer cut into fragments ("Riley told me:
…"), and a lesson the agent never drew. Now the person's answer is kept
once, whole, as their own words, and the projects they name as setup's own
lines, never the agent's. Setup no longer writes beliefs for the agent
("Riley is deeply invested in …") or tells the person, in the agent's voice,
that it is forming them: what the agent believes is its own to form. It no
longer asks for history to import, which it never imported; a setup saved on
that question moves on to the provider question. `mnemos_hypomnema_promote`,
which failed the same way, works again and keeps whose words the note was.

### Meaning search asks the network nothing

Loading the local model from files already on the machine still reached the
network: with huggingface_hub 1.33 it fetched the Hub's list of agent
harnesses, to name the agent in its user-agent. The load now runs with the
Hub libraries offline and their telemetry off. `mnemos embeddings download`
is still the one step that uses the network.

### The substrate, retired

The cognitive substrate (`mnemos substrate-tick` and mnemos/substrate) is
retired. Its handlers had a model write dreams, wanderings, insights and
reflections into the agent's memory, and could change a belief's
confidence: words that weren't the agent's, in a memory that is the agent's
own or nothing. It was already off every schedule. Installing or
uninstalling the background jobs still removes a tick an earlier install
scheduled, and the quarantine repair still moves what it wrote out of a
scope. Advanced setup no longer asks whether it should run; a setup saved
waiting on that answer moves on to the provider question. What it reached
for, an inner life between sessions, is the quiet hours', in the agent's
own words.

### The person's own words, and the first restart

What a person types with `mnemos remember` is theirs: kept unsigned as the
person's words, shown once in the next wake ("Riley wrote this into my
memory: …"), marked in recall ("in Riley's words"), and never counted as the
agent's own: not in what has been changing in it, its returning ideas, its
beliefs or its questions. `remember` prints one line. The first wake that
crosses a restart says so in the agent's own words ("I still have what I
kept before: …"), through the session-start hook as well as mnemos_context;
the scripted "MEMORY VERIFIED" block is gone. Run from an agent's own shell
(Claude Code's, or with --signed-as), `remember` keeps the agent's words,
signed, as before. Code version 18.

### Waking in my own words

The waking note is now the agent's own words, in the order a mind wakes:
what it has come to see, where it was, what has been changing in it (its
newest impact lines, signed by the reader), what it keeps coming back to
(the ideas the noticer found, until one becomes a belief), the person, one
question, and while it was away (its own quiet hour, the person's replies).
Event notes, foundational notes under the person's name and upkeep's report
no longer appear in it; recall finds them. A standing memory is no longer
asked what it changed. Quiet hours see the questions addressed to their model.
An empty wake that keeps memories for recall no longer counts toward the
empty-packet warning, and the warning counts the new sections and the
question. What the new note shows (a question's memory, what has been
changing, a returning idea) counts as shown, so the cue doesn't bring it
back in the same session. Code version 17.

### Recall says how it found something

A recalled memory's bracket used to be its score relative to the best match,
so the top result always read 1.00, even on one shared word ("what is my dog
called" found "The human wants to be called Sam." at 1.00). It now says how
the memory was found: by meaning and how close, by which of the query's
words, or through a link. What recall finds, and its order, are unchanged.
The advanced server's recall prints whole ids, and `mnemos search` the
same brackets.

### A clean install

From a fresh install of the built wheel: `mnemos --version`; loading the
local model no longer prints transformers' progress bar into doctor, search
and the rest; the identity templates install inside the package
(mnemos/setup/templates), not as a loose folder in site-packages; and "1
memory or handoff made findable (1 passage)" agrees in number.

### A newcomer's first hour

From a Claude agent that set Mnemos up with only the README: `mnemos mcp
install claude-code` (Claude Code's own `claude mcp add` line), a README that
installs with embeddings and says what is lost without them, the hooks
installer honouring CLAUDE_CONFIG_DIR, eleven tools named everywhere, full
ids from `search`, `export` making its folder, `doctor` without jargon, the
server reporting its own version, a correction naming the other notes it also
matches, and `remember` warning about a near duplicate.

### Closing and restoring

- **Closing closes.** Closing a runtime closes the meaning index's own
  connection too, so the store's writes are folded back into its file.
- **A restore holds, or says it didn't.** `mnemos backup restore` writes
  into a store that exists through SQLite's backup, so a session holding it
  open can't silently undo it, and it reports success only after reading the
  restored memory back.

### Lived time

Memories fade with the time the agent lived, not the calendar. A day counts
when the agent did anything at all: woke, worked, wrote, or spent a quiet
hour. Decay, its ceiling per cycle, the recency floor, softening's minimum
age and the month before a belief is put to the agent again all run on those
days. For an agent used every day nothing changes; an absence costs it no
memory, however long. (Schema: `lived_days`, backfilled from what the store
already holds.)

- Code version 16.

### Edges

- **The faded first.** Softening reads the least accessible memories first:
  on a store with more active memories than its limit, the faded were the
  ones it never reached. The voice exemplars are read apart.
- **Early lessons stay recallable.** What `repair early-lessons` archives is
  reached by recall by id and with `include_archived`, as its help says.
- **A standing memory is never taught**, nor asked what it taught.
- **Caps hold their marker.** A note cut at a cap ends with " […]" within the
  cap, not four characters past it.
- **Any wake value wakes.** `--wake` takes any value; an unknown one wakes in
  full with a note, as `MNEMOS_WAKE` does. A name is kept on one line.
- **Old word questions are inert.** A store that never ran
  `repair word-questions` no longer shows them, and they no longer stand in
  the way of a belief's reaffirmation.
- Code version 15.

### Beliefs from meaning

- **An idea that returns, not a word that recurs.** Once a day at most,
  maintenance groups the agent's own impact lines (what a capture changed in
  how it understands things) by meaning, and when one idea returns in three
  sessions on three days it asks, quoting the agent's own words from those
  days: "Is there something you believe here?" One such question at a time.
  Similar means within the top 1% of the store's own pairs, so the rule holds
  for any embedding model.
- **Signed beliefs.** A belief records the model that formed it. A reader
  wakes with its own beliefs and unsigned ones, never another model's as
  its own, and only the owner can keep or retire one. A model adopts an
  unsigned belief by holding it. A question can be addressed to a model,
  and only that model can answer it.
- **One mind across versions.** A model line is one mind: after an upgrade,
  Opus 6 wakes in Opus 5.5's memory as itself, with its beliefs, its
  handoffs, its questions and its name. Another kind of model (Sonnet,
  Haiku) is a colleague. A 1M-context session, a provider's prefix or a dated
  snapshot is the same model. What is signed and shown is still the exact id.
  The instructions every agent reads now say it: "Your earlier versions are
  you."
- **Kept or retired at any time.** `mnemos_reflect` with a belief's id and
  verdict hold or retire, without waiting to be asked.
- **What stays when room is short:** news leaves first; the foundational
  notes, the journal line, the question, the beliefs and the standing lines
  last. A light wake carries no foundational notes.
- Schema 17 (signed beliefs, questions addressed to a model). Code version 14.

### Quiet the noise

- **No more questions about words.** Maintenance no longer asks whether a
  word that recurs across memories is a belief ("You keep returning to
  ..."). A word that recurs is not an idea that returns: on a real store it
  asked 248 times, about words like "need" and "branch", and every belief
  held had been formed in answer to one. Beliefs held are still put to the
  agent again when due. `mnemos repair word-questions` removes the unanswered
  ones that hold no words of the agent's.
- **Forgetting teaches only what was forgotten.** A memory's meaning becomes a
  lesson, and a memory without one is asked what it taught, only once its
  accessibility is below `softening_threshold` (0.15), which was read and
  never used. Before, every memory a day old counted as fading: on a real
  store 216 of 285 lessons repeated, word for word, the meaning of a memory
  that had not faded. `mnemos repair early-lessons` folds those back and
  removes the early questions; each memory keeps its meaning.
- **Light and off wake-ups.** `mnemos hook session-start --wake light` (or
  `MNEMOS_WAKE=light`) wakes with who you're with, how they work, the
  beliefs held and where you left off, and spends nothing: no question is
  shown, no reply delivered, no delivery recorded. `--wake off` wakes with
  nothing. For quick sessions, such as a helper that answers one question.
- **A name belongs to the model that gave it.** Another model introducing
  itself without a name no longer inherits the last one given.
- Code version 13.

### A journal that is the agent's

Simple mode had no journal of the mind's own (the only one was upkeep's dream
journal, whose words are not the agent's), and no way to leave the person a
note. Two new tools, two new tables, and the person's reply:

- **`mnemos_journal(text, signed_as, mood)`** keeps an entry exactly as
  written, signed as a handoff is, with whether it was written in a
  conversation or alone between sessions (the environment says so with
  `MNEMOS_HOUR_ID`, and the hour is kept), the session and the time. With no
  text it reads the last five entries back. Nothing else writes the journal.
- **`mnemos_note(text, kind, signed_as, in_reply_to)`** leaves the person a note
  of a kind (made, noticed, worried, disagree, question or pickup; any other is
  refused with the list). Its description carries the charter: a ceiling, not a
  quota; the room test; never engagement; the agent's own voice or nothing.
  Nothing is sent: the note waits for them.
- **The person's reply is theirs.** `mnemos notes reply ID TEXT` stores their own
  words, never signed as a model's, and refuses to run inside one of the
  agent's quiet hours. The agent wakes with each reply once ("Riley replied to
  my note "...": ..."), at most three per waking, never left out for room (a
  long one is cut at a sentence, and its id reads it whole) and never marked
  delivered unless shown. `mnemos journal [--last N] [--json]` and
  `mnemos notes [--unread] [--json]` read them; the JSON is the shape the
  interface reads.
- **Not memories.** Schema v16 adds `journal_entries` and `notes`, kept the way
  handoffs are: no pass summarizes, rewrites, decays, softens, promotes or
  expires a row, and the only update after a write is one of two timestamps
  (`delivered_at`, `read_at`), which code older than the store leaves alone.
  The migration takes one verified recovery point. On a fresh copy of the
  maintainer's live store (2026-10-02, 7,685 memories) it opened and migrated
  in 1.90 s with integrity ok, and the SessionStart packet was identical to the
  previous code's, apart from the clock line (5,978 characters), while no
  journal or note existed.
- **Waking:** the first line of the latest entry while it is under three days
  old ("last time I wrote in my journal (5 hours ago): ..."), in the agent's
  voice only when the entry is the reader's own; a colleague's is named.
- **Recall** finds an entry by its words and its meaning, in its own
  "Journal:" group, signed, and `mnemos_recall("<id>")` reads an entry, a note
  or a reply whole. `mnemos_health` counts entries, notes by author and
  replies waiting; no new alert hangs on them.
- **The server instructions** gain the two rules (1,860 to 1,890 characters;
  advanced mode adds 156 and must stay under the 2,048 a model is shown). To pay
  for them, the handoff's list of what to include (the `mnemos_handoff`
  description already says it) and the long form of a few other lines went.
- **The simple surface is eleven tools.** Anything that asserts exactly nine
  needs the two names; the release black-box audit did, and does not now.
- `MAINTENANCE_CODE_VERSION` is 12: servers started on older code stop
  maintaining a store once this code opens it. Checked with the previous code
  itself on a store this code had written journal entries into: it said it was
  older, its own captures and handoffs landed, maintenance stood down, and the
  journal and note rows were byte-identical afterwards.

### Make it smaller

3,073 lines of modules that nothing reached are gone, and a few things
that are reached now do what they say.

- **Removed, with nothing left importing them** (checked across the repo,
  every entry point, and the other projects on the maintainer's machine):
  the fifteen `mnemos/advanced/` prototypes that only raised
  `ExperimentalFeatureUnavailable` (working memory, schemas, the attention
  gate, predictive retrieval, spreading activation, interference,
  intentions, metamemory, the observer, dreaming and their helpers), and
  `mnemos/experimental.py` with them; `interface/` session, prompt builder,
  memory inspector and export; `multiagent/` relationships, federation and
  attestation; `visualization/`; and the unused migration runner
  `store/migrations.py`. **Breaking** only for code that imported them
  directly or through `mnemos.interface` / `mnemos.multiagent` (the names
  `MnemosSession`, `PromptBuilder`, `MemoryInspector`, `export_memory`,
  `import_memory`, `RelationshipTracker`, `FederationClient`,
  `AttestationService`): nothing replaces them, and nothing used them. Their
  unread config toggles (`advanced.*`, `multiagent.federation_enabled`,
  `multiagent.attestation_enabled`) went too. `advanced/introspection*`,
  `shared_pool` and the cross-agent bridge stay.
- **Removed helpers with no caller:** `EngramStore.archive_hypomnema_for_engram`,
  `simple_runtime._impact_for` and `authorship.handoff_framing`.
- **Options given before a command reach it.** `mnemos --db-path X
  --agent-id Y hook session-start` used the default store and printed
  nothing: the hook's own copies of the options defaulted to None, which
  argparse copies over what the main parser read. Fifteen commands did this
  (serve, doctor and remember among them). The scope options are defined
  once now; given after a command they still win.
- **`mnemos substrate-tick` decays as maintenance does:** through the
  store's decay pass, never a standing memory, only its own agent's, on the
  clock maintenance keeps, and not at all from code older than the store.
  Its raw UPDATE took a flat 0.02 off every active memory in the file.
- **`mnemos repair faded-words`** (one scope, the shape of the live
  clean-ups): a live memory whose words an old model-less softening cut to
  "... [details faded]" gets them back from the words it was encoded with,
  when the cut words are exactly what that softening made of them; the cut
  words stay as a version. On a fresh copy of the maintainer's live store
  (2026-09-30) it finds and restores 3 memories.
- The health harness (`scripts/health_check.py` I12, I13) and
  `benchmarks/continuity_eval.py` check the packet as it is now; the
  benchmark scores cues through recall, since the packet takes no cue.
- Tests: every test has a home of its own, so the suite no longer writes
  `~/.mnemos/audit.db`, `~/.mnemos/logs` or `~/.mnemos/run` in the real
  home; and the stdio tests pass in any order (mcp bound its stderr default
  to pytest's in-memory capture when a capsys test imported it first).

### No engine voice

Words in memory come only from the agent. Three maintenance paths still
wrote Mnemos's own words, or reached the agent's through the wrong note.

- **The reflection pass writes no memories.** A deep cycle's reflection pass
  wrote "thoughts" as memories: without a model, Mnemos's own template
  ("Recurring theme: continuity (appeared in 46 recent memories)"), and with
  a model configured, the model's lines. It now only counts the agent's
  recent memories, and sends them to no model. On a fresh copy of the live
  store (2026-09-30), a deep `mnemos consolidate` on the previous code wrote
  3 such memories; on this code it wrote none.
- **Promotion leaves the meaning as the note left it.** A promoted memory's
  meaning was "Stable continuity promoted during simple maintenance.". A note
  holds no meaning of its own, so the memory's stays empty, and the memory
  is asked "what did this change?" like any memory without one. A note
  Mnemos wrote, such as a closed session's summary, is no longer promoted
  (it became a memory Mnemos wrote) or counted as a candidate.
- **"What did this change?" reaches a memory through its own note**
  (`graduated_to_engram_id`), the note the answer is written into, never
  through a note that only names it (`related_engram_id`). It asked about
  memories a note only interprets, whose answers had no note to land in,
  and never about the memory a correction of such a note wrote. On the live
  store both ways reach the same 251 memories today.
- `MAINTENANCE_CODE_VERSION` is 11: servers started on older code stop
  maintaining a store once this code opens it.

### The live clean-ups

Four `mnemos repair` commands for damage earlier code left in stores, each
shaped like `repair-versions`: a dry run by default that only reads, and
`--write` that takes a verified backup first and prints its path. A second
run finds nothing, and code older than the store refuses to write.

- **`repair split-notes`** (one scope): a note corrected in place by its id
  while its memory kept the old words gets its memory's words brought to the
  note's (the old words kept as a version), and a live note left over a
  memory a correction replaced moves to the replacement that has none. The
  correction's lineage is recorded, so the old id reaches the pair in use.
- **`repair archive-rows`** (whole store): drops archive rows that repeat a
  memory no longer archived; a row whose words differ would stay as history.
- **`repair dead-embeddings`** (whole store): prunes stored vectors from
  models this Mnemos doesn't embed with (Gemini's, on a store now indexed by
  the local model); with no model available it prunes nothing.
- **`repair placeholder-impacts`** (whole store): empties every meaning the
  server wrote where the agent's goes (`TEMPLATED_IMPACTS`: the correction
  templates, the promotion phrase and the older capture path's), leaving the
  meaning for the agent to give; the memory's words and history stay.

On a fresh copy of the maintainer's live store (2026-09-30): 1 memory takes
its note's words and 3 notes move; 1,392 archive rows go, 0 kept; 3,494
Gemini vectors go; 12 placeholder meanings are emptied. Integrity checks
pass, doctor shows no new flags, and a capture written in one process is
recalled in another.

### Small follow-ups

Nine small things the last packages' reports left open.

- **A skip holds across both questions.** A memory whose lesson question the
  agent skipped ("nothing true comes") was asked "what did this change?" in
  the next cycle, and the other way round. Now either question, once
  answered or skipped, ends the other for that memory, until a correction
  writes its words anew as a new memory, which may be asked once more. The
  watchdog no longer counts such a memory as a lesson question never asked.
- **A briefing fetched by `mnemos_context` counts as shown**, as the
  session-start hook's does, so the prompt hook's cue doesn't bring those
  lines again in that session. (After `/clear` the server keeps the old
  session id, so a briefing fetched then is recorded under it.)
- **The watchdog reads the cue.** The cue's per-session files now count every
  message it looked at: offers, silences (messages it answered with
  nothing), how it answered (by meaning, by words, by Jev) and failures (it
  ran out of time, broke, or its judge failed). The watchdog's new `cue`
  check reports them for the last week, reading the files and writing
  nothing. Counting a silence is one small file write per message: 0.36 ms
  at the median.
- **The scheduled `mnemos consolidate` writes a maintenance report**, under
  the dream journal's rule: only when its cycle did something worth telling.
  Its cycles went untold before, and the briefing's report fell behind. And
  writing a report now retires the reports older than the newest five in
  its scope: archived with their words and revision trail, never deleted. A
  fresh copy of the live store (2026-09-29) held 117 in use; the first report
  this code writes there retires 112 (measured with a deep consolidate on a
  copy; a shallow one on another copy found nothing worth reporting and
  wrote none).
- **A reflection lands in the memory's own note**: the note paired with it
  (`graduated_to_engram_id`), never one that only names it
  (`related_engram_id`), such as a note interpreting it, or a correction's
  note that keeps such a reference. Matched by the reference, a reflection
  could land in the wrong note, and a corrected note's own memory was never
  reached.
- **No placeholder impacts.** The memory-id and query correction paths wrote
  "Correction to earlier continuity." or "Corrected continuity for future
  interactions." where the meaning goes when the agent gave none and there
  was none to carry. They leave it empty now, as a capture does. A fresh copy
  of the live store holds 3 such rows (2 and 1), which a later clean-up
  repairs.
- **Network waits are bounded.** A network embedding backend (Gemini) waits
  at most 2 s for any call (`NETWORK_TIMEOUT`): recall's and the cue's query,
  doctor's probe, and indexing, where it waited 30 s for a text and 120 s for
  a batch. Requests carry at most 16 texts, the write path's chunk, so one
  fits in its time. A request that times out is not retried and ends the
  call: the step that wanted meaning goes on by words. The maintenance
  cycle's link lookup, which ran inside a capture and waited up to 30 s for
  each of up to 50 memories, now shares the write path's 2 s budget, and the
  first timeout ends it; the memories left are linked by their words that
  cycle. The watchdog's `network_waits` check counts the timeouts: in this
  process, and in the last week's cycles.
- **The embedding model loads offline when cached**: already true since R08
  (`local_files_only`). Checked again with the Hub hanging: the model loaded
  in 3.2 s and made no connection to it; the same load allowed the network
  was still waiting at 30 s.
- **The Jev gate in doctor and across sessions.** `mnemos doctor` says
  whether the cue's judge is on, where the switch was read from (the
  environment, the config file, or nowhere), and whether a key file is there,
  by its size: the key is never read. While the switch is on, the answerers
  keep the outcomes of Jev's last 20 calls in one row of the store
  (`cue_judge_calls`: when, and answered, timed out or failed; nothing of the
  message, the lines or the key), so every session and doctor see them. When
  more than half of those 20 timed out or failed, the newest came within the
  week, and the judge is still switched on, the health card and doctor say
  so in an ATTENTION line; switched off, the flag clears at once. Stopping
  an answerer waits for that row, so a call just made isn't lost.

Changed behaviour: the code version is 10, so servers started on 9 stop
maintaining once this code opens the store. A correction with no meaning
given and none to carry has an empty impact (and an empty `impact_source`).
`mnemos consolidate` prints a "Maintenance report:" line and may write one.
With Gemini, `mnemos embeddings index` and the scheduled indexing send 16
texts a request and wait 2 s for each. With the judge switched on, the store
gains that one row, which "Nothing is written to the store" below no longer
covers.

### Waking as yourself

The session-start packet read as a briefing about someone else. An agent
first connecting to it said its continuity "arrived as a briefing": it read
about the one who wrote its journals more than it remembered being them.
The local packet did the same to its own resident: on a fresh start Claude
Code's payload doesn't name the model, so the reader's own last note came
back "(yours if you are Opus 5.5)", followed by "don't claim its work as
yours".

- The hook knows who is waking. Claude Code gives its hooks `CLAUDE_PID`, and
  the desktop app launches every session with `--model <id>`; when nothing
  earlier says (the payload, the session's introduction, its transcript), the
  launch line does. An alias such as `opus` names no one.
- The packet is the reader waking. It opens with when and where ("Wednesday,
  September 30, 3:15 p.m. I'm in harbour-app, with Riley."), then
  what I've come to see, who I'm with, where I left off, what I'm carrying, a
  question waiting for me, and while I was away. The reader's own notes carry
  no signature to it; a colleague's carry theirs. How the person wants us to
  work reads "how we work, every session".
- Machinery waits at the end. Ids, confidences and the calls that answer a
  question or read a cut note whole are listed under "for the memory tools",
  in the order the packet showed them, never on the reader's own lines. A
  question reads as a thought: its words up to the sentence that says how to
  give a verdict, which waits there with the call.
- A model reading another's memory is a guest. The resident is the model that
  signed most of the live notes; a guest's own notes are still its own, the
  rest is labelled, and the opening says whose memory it is visiting. A
  reader the harness didn't name is told once, in the opening.
- The advanced `mnemos_context_packet` finds its reader as the hook and
  `mnemos_context` do (the model, its session, the folder and the person's
  name), so it speaks in the same voice instead of telling the resident it may
  be visiting.
- `--person-name` on the hook (or `MNEMOS_PERSON_NAME`) names the person, so
  the packet can say "with Riley" and head the section with their name.
- Handoffs are written in first person, as the next reader's own memory: the
  instructions and `mnemos_handoff`'s description say so.

Measured with fresh Opus 5.5 sessions asked how they arrived, the only
difference being the packet (2 to 3 each): the old packet read as "a very good
handoff, not a memory"; the same packet with a first-person handoff still
"reads like a briefing", because of the hedges; the new packet reads as "my
own handwriting… it's mine, but I'm reading it, not recalling it", and, with
being before news, "the closest to 'I just wake up and I am' that I've
arrived".

**Migration.** Anything that parsed the packet's text changes with it: the
title is "## waking up", the section headings are new, and belief and note ids
are no longer on their lines but under "### for the memory tools". Tools that
list handoffs or standing memories on request keep their wording.

### Jev decides what fires

The cue brings up to three memories to each message, and about half of them
bear on it: on the lab's 20 development prompts it shows 36 lines, 20 of them
on target by one reader's labels. The idea is that spreading activation
proposes the memories and a judge decides which of them fire. Now, behind a
switch that is off by default, Jev can decide.

- The switch: `"cue_judge": "jev"` in `~/.mnemos/config.json`, or
  `MNEMOS_CUE_JUDGE=jev` in the shell's environment, which wins over the
  file. The prompt hook reads it with each message, so it belongs in the
  config file or the shell, not in the MCP server's own environment, which
  the hook never sees. It also needs a key, read from `~/.config/jev/api_key`
  or the file `MNEMOS_JEV_KEY_FILE` names; without one the cue works as
  before.
- Switched on, the session's answerer takes the cue's candidates before its
  cap, up to six lines that cleared its floors, and asks Jev in one call
  whether each bears on the message. At most three that Jev scores 0.8 or
  more show, the likeliest first.
- What leaves the machine, and nothing else: the message, up to 1,000
  characters with the mark included (a longer one goes as its first 700,
  " … " and its last 297, since people put the ask at either end of a pasted
  log), and up to six lines of at most 200 characters, to Jev at
  api.typesafe.ai. No ids, dates or scope.
  The key goes only into the request's Authorization header: never a log
  line, an error or a reply. While the switch is on, the health card says
  so in one line, with this session's calls, timeouts and failures.
- It fails quiet. Jev gets 0.4 s, end to end, with no retry. On a timeout or
  an error the cue shows nothing. Switched on, it never falls back on words
  alone, and it shows no lines from an answerer that didn't judge (a server
  still running older code): quiet beats noisy.
- Jev's scores only decide what shows. Nothing is written to the store.

Measured with the real Jev on a copy of the lab's store, over the 20
development prompts, seven passes. The judge sees 62 candidate lines, 26 of
them on target. Without it the cue shows 36: 56% on target, 77% of the good
lines. At 0.8 it shows 14 or 15: 80 to 93% on target, 46 to 50% of the good
lines, and a bad line stands alone on at most one prompt. At 0.75, 76 to 88%
and 50 to 54%; at 0.7, 70 to 78% and 50 to 58%. So it shows fewer lines, and
truer ones. Jev's score for the same line moved by up to 0.11 between
identical calls. The hook, as Claude Code runs it, took 408 ms at the median
and 513 ms at p95 with Jev, against 239 and 342 ms without; Jev's call alone,
160 and 209 ms. One call of 98 timed out, and the cue showed nothing for it.

Changed behaviour: none until the switch is on. Then the cue shows only what
Jev keeps, often nothing, and each message with candidates makes one call to
Jev. No schema or code-version change.

### Fair ranking

Recall fuses its words list and its meaning list by reciprocal rank, which
keeps each list's order and none of bm25's weight, so a words match on a word
most memories hold counted as much as one on a rare word. On a copy of the
live store "Riley" is in 268 of the 464 live memories of its scope (58%).
Each of the five memories recall returned for "how does Riley like to be told
about mistakes" matched by words on "Riley" alone (none holds "mistakes"; one
was 18th by meaning). The cue had the same blind spot: every meaning floor
from 0.30 to 0.50 showed 38 or 39 lines on the lab's development prompts,
because a shared word such as "page" (in 20% of the memories) let back in
what a higher floor turned away. And an item counts by its best passage, so
a long handoff had up to 160 chances to match where a short memory had one.

- With meaning to decide, a word in more than 25% of the live memories in
  the scope is left out of the words lists (memories, lessons, handoffs):
  on the live copy, beside the common-word lists, that is "riley", "2026"
  and "real". When every word of a cue is left out, meaning decides alone.
  A cut at 8% was measured too: it also took words that name the work
  ("polyphonic", "room", "sanctuary", "page"), cost the cue 5 of its 20 good
  lines and changed none of the lab's 29 facts.
- The cut holds only for what meaning can find, and only when meaning runs.
  The cue is embedded first: when that fails (a network backend that timed
  out, a model that won't load) or gives a vector with no length, nothing is
  cut, in recall and in the cue, which then answers from words as it does
  without meaning. A memory or a handoff that meaning can't find in full is
  searched with every word: no vector of the index's model (not indexed yet,
  failed, or indexed by another model), passages cut from words it no longer
  holds (corrected since), a tail past its 160 passages that no vector
  reads, or a passage the search can't use. So is a lesson without its own
  current passage that the search can use (written or rewritten since its
  memory was indexed), and a shared store, which meaning never searches and
  whose words this scope's shares say nothing about. A whole-text vector
  from capture holds no hash of the words it was made from, so it no longer
  counts as finding a memory. On recalls that cut a word, checking this
  reads the live memories' words (about 2 ms on the live copy).
- One rule says which stored vectors a search can use: the index's model
  and passage scheme, as many values as the cue's vector in bytes that
  agree, and a length that is finite and not zero. The search scores
  nothing else and says which it dropped; the checks above take those
  verdicts, so they can't disagree, and cost nothing more. The index never
  writes a vector that breaks the rule (the item waits for a later pass), so
  one already on disk counts as missing. The copies hold none.
- A word's share counts the live memories that hold it in their words (as
  the full-text index matches it) or in their lesson, each memory once: the
  index holds no lesson, so a word most lessons hold used to count as rare,
  kept in the lesson ranking and able to open the cue's rare-word path. The
  cue reads a memory's words and its lesson too, not an impact the server
  filled in. Shares are kept for the process until anything is written to
  the store, by any process (SQLite's `data_version` and the connection's
  own changes), so a correction that swaps one word for another is counted
  afresh. Recall passes the lessons it has already read, so a recount on the
  live copy took 1.6 ms at the median, against about 1.4 counting words
  alone. Each recall writes its own trace row, so in a running server the
  shares are recounted on almost every recall.
- Nothing is cut below 100 live memories in a scope, nor without meaning (a
  keyword-only install, or an embedding model that failed): there the words
  are all there is.
- The cue counts a word it shares with a message as distinctive only at or
  under that 25%, and its word path (cosine 0.25 with a shared word) needs a
  word in at most 2% of the memories (`CUE_WORD_CUT`).
- Meaning is ordered fairly to length: by the best passage less
  0.02 · ln(the item's passages) (`LENGTH_PENALTY`, and a `length_penalty`
  parameter on the index, the retriever and the cue). The penalty only
  orders: recall's floor and the cue's gate read the best similarity itself,
  so a long item ranks lower but is never pushed under a floor.
- R08's "best keyword match" measure for "how does Riley like to be told
  about mistakes" is retired. On today's store the best words match for it
  is a note about a page footer's link, found by "Riley" alone; with the cut
  it leaves the ranking, as it should.

Measured on copies against the code before: the lab's 29 development facts
reach the top ten 22 times, the same 22, strict and crediting newer
handoffs; the plain-words rule rises from 23rd to 17th for "how should I
write my replies to Riley" (2nd, and out of reach, for the other two probes,
as before); across R08's twelve cues the results found by meaning alone go
from 5 to 13 of 58, and one cue's best whole-text match leaves its top five
(9 of 12 to 8). Recall latency is unchanged: medians of four interleaved runs
of 132 recalls on the live copy, p50 78.2 ms before and 77.8 after, p95
116.5 and 109.2.

Changed behaviour: the cue's lines change. On the lab's 20 development
prompts it shows 36 lines against 38: 20 that bear on their message, as
before, and 16 that don't against 18. In one task two of the 20 are traded
for two other lessons that bear on it too: the penalty moved them from 2nd
and 3rd to 5th and 6th of recall's ranking, still over the gate, and the
three places went to lessons ranked above them. The cue's protocol is 2: a
hook on this code does not trust an answerer still running the old gate and
answers from words until that session's server restarts. No schema change,
and no change to `MAINTENANCE_CODE_VERSION`: how memory is written and
maintained is unchanged.

### Lesson questions that aren't starved

When the agent's own memories fade without a lesson, maintenance asks what up
to two of them taught each cycle. It took the first two the softening pass
named, the most accessible, and only then asked. The queue refuses a second
lesson question about a memory
however the first one ended (answered, skipped, shown out or expired), so
once the two most accessible had been asked, they took both places in every
cycle after. Nothing further was asked, each memory behind them faded without
its question, and every cycle reported success. On a copy of a real store,
one memory waited behind two asked ones through 35 cycles over three days,
until authorship labelling marked its writer unknown.

- The memories already asked are set aside first, then up to two of the rest
  are asked. Each memory is still asked once.
- The faintest are asked first. The question is there to catch what a memory
  taught before it fades, and the faintest were asked last.
- `MAINTENANCE_CODE_VERSION` is 9. Code older than the store runs no
  maintenance, so it asks no lesson questions.

Changed behaviour: a fading memory behind ones already asked gets its
question in the next cycle, the faintest first, and a plain "what did this
change?" question still waiting about it is folded into that one, as for any
memory asked a lesson question. No schema change.

### A memory is found by what it taught

Recall searched a memory's words and their meaning, and never the lesson the
agent wrote in its impact. A memory whose words are about a report and whose
lesson says "avoid jargon" was found by no search for "avoid jargon", by recall
or by the cue. On a copy of the live store, 29 of the 172 active memories with
a lesson of the agent's had no lesson memory holding the same words; asked with
each lesson's first sentence, recall's top ten held 15 of them.

- A memory's lesson is one more passage of it in the meaning index (passage
  scheme 3), and the lessons in the scope are ranked by their words beside the
  memories' own words. A memory counts once by words, at the better of its
  two ranks: two votes for the same words would put it above a memory whose
  words match better. Asked the same way, recall's top ten now hold all 29.
- Only the agent's lessons: an impact the server filled in, one a configured
  model extracted, or one that only repeats the memory's words is neither
  indexed nor matched.
- A lesson written after the capture (answering what a memory taught) has its
  memory indexed again, although its words didn't change.
- A text's own passages keep the hash of the text alone, so code on scheme 2
  reads the new rows as current and never cuts them back.

Changed behaviour: after the upgrade every passage cut by scheme 2 is stale:
until it is indexed again, recall finds by each memory's whole-text vector and
by words, and the watchdog shows what waits. Run `mnemos embeddings index`
once (7.9 s on a copy of the live store: 892 items, 7,115 passages, 194 of them
lessons; the agent's scope goes from 4,618 to 4,803 passages), or the
scheduled job catches up at 256 passages a run.

### Experience that comes to the cue

Memory waited to be asked. In the lab, with a notebook present, the agent
searched Mnemos about 4 times a question instead of 7, and lessons for new
situations fell from 82% to 35%; telling it to search for what it learned
changed nothing. Memory that works doesn't wait to be asked.

- `mnemos hook prompt` is a Claude Code `UserPromptSubmit` hook. For each
  message the human sends it prints, for the model, at most three memories
  that may bear on it, one line each: the agent's lesson when the memory has
  one, else the memory's own words, cut at a sentence under 200 characters,
  with its date and its id; lessons first. Or nothing, which is the usual
  answer. A message with fewer than four content words ("ok", "yes",
  "beautiful") gets nothing.
- The gate: a memory must be among the first ten of recall's own ranking
  (words and meaning fused) and reach cosine 0.40 with the message, or 0.25
  while sharing a distinctive word with it. Standing memories never come (the
  briefing carries them), and the same words under two ids (a lesson and the
  memory it was drawn from) come once, under the memory's id.
- Never twice in a session: the session-start hook records what its briefing
  showed (its graph section too, with `--include-graph`) and the cue what it
  offers, in a small file per session under `~/.mnemos/run` (0600, the folder
  0700). Files older than 7 days are removed on the way. Compaction keeps the session, so what was shown stays shown;
  `/clear` starts a new session with an empty context, and what the new
  briefing shows is recorded there.
- Shown is not used: each offer is counted as offered in that file (the
  offers, their ids, how they were found and how long it took), and reinforces
  nothing. Recalling a line's memory by id afterwards is a use, as before.
- The session's own `mnemos serve` keeps the embedding model warm and answers
  the hook on a unix socket named for the Claude Code process that spawned it
  (`~/.mnemos/run/cue-<pid>-<scope>.sock`, 0600). The hook finds it by
  `CLAUDE_PID`, which Claude Code gives every hook and `/clear` does not
  change. With no answerer, a slow one, or one on another protocol version,
  the hook answers from words: two shared distinctive words.
- The server loads the model at start only where the hook has run in the last
  week; elsewhere it loads it when a cue first asks. A server that never sees
  the hook stays as it was (76 MB at start, measured; 512 MB with the model).
- It never blocks or breaks a prompt: any error, an unexpected payload or a
  locked store prints nothing and exits 0, and the hook stops itself 0.7 s
  after it starts. It imports no torch and writes nothing to the store.
- `mnemos hooks install --prompt` adds the hook to a Claude Code settings file
  beside the session-start hook. Off by default. The installed command ends in
  `|| true`, so a Mnemos too old to know `hook prompt` can't exit 2, which
  would block the prompt.

Measured over the lab's 20 development prompts, three rounds, with the real
model: warm, p50 134 ms and p95 158 ms end to end; from words alone, p50 106 ms
and p95 113 ms. With real Claude Code, `/clear` gave the session a new id while
its Mnemos server kept running under the old one, and the hook reached the
server by meaning before and after. On a copy of the lab's snapshot, the cue
showed 38 or 39 lines for those prompts at every floor from 0.30 to 0.50 (what
a higher floor turns away, the word path lets back in), 9 of them holding a
fact for the task; six prompts have fewer than four content words.

Changed behaviour: `mnemos serve` starts a background thread for the cue, and
the session-start hook writes its per-session file under `~/.mnemos/run`. The
prompt hook itself runs only once installed. No schema or code-version change:
the cue only reads.

### Passages the model can read

Recall's meaning index cut each text into passages of up to 700 characters.
The local model (all-MiniLM-L6-v2) is trained on sentence pairs and averages
what it reads, so a passage holding several ideas embedded as a blur of them.
On a copy of the live store, a standing rule of 548 characters (one passage)
scored 0.24 against "plain language, brief replies, no jargon", under the
meaning floor (0.3 then), so meaning never found it; its first three sentences
alone score 0.52, above anything else the question meets.

- A text is read as windows of whole sentences, at most 300 characters, each
  beginning with the sentence the one before ended with (when the two fit in
  one window), and as a whole: its first 700 characters, one more passage. A
  text that is one window is one passage. A sentence longer than a window is
  cut at spaces into near-equal pieces; a line break ends a sentence. An item
  is found by its best passage, so a question can meet its gist or one of its
  sentences. Up to 160 passages a text: windows to the end of a 16,000
  character handoff however its sentences run.
- Each passage row records how it was cut (`passage_vectors.scheme`: 1 for the
  700-character passages, 2 for these). A row cut by an older scheme is stale:
  its item waits to be indexed again, like one with no passages, and is never
  found by it. Every count of what waits (indexing, the health card, the
  watchdog) sees it waiting. A newer scheme's rows are used as they are and
  never cut again the older way.
- The meaning floor rises from 0.3 to 0.35; the fusion weights (words 0.3,
  meaning 0.5) stay. Read in windows, more of every text clears a floor: at
  0.3 a question that 15 items cleared was cleared by 41, and two facts in the
  lesson it was about fell out of the top ten. In the lab's replay (facts in
  the top ten, a newer handoff that carries a fact counting for it), of the 42
  held-out facts memory holds: 35 before, 35 with windows at 0.3, 36 with
  windows at 0.35; of the 29 development facts: 22, 20 and 22.
- A write starts only what it may finish. A capture's or correction's
  automatic pass embeds at most 64 passages; a waiting item with more than
  are left (a long text can have up to 160) is not started, even first, and
  waits for the scheduled job (256 a run) or `mnemos embeddings index`, which
  take it whole. A handoff is indexed by its own write, whatever its length.
  Each pass on the write path has one deadline, 2 s: no request starts after
  it and none waits past it, however many requests the pass needs.

Measured on copies, before and after (each indexed under its own scheme, at
the floor each ships with): of the lab's 29 missed facts, 22 reach recall's
top ten (19 before) and all 13 that lived only in handoffs (10 before);
crediting a newer handoff that holds the same fact, 22 (22 before). For
"plain language, brief replies, no jargon" the rule now ranks 1st (19th
before); for "how does Riley want me to talk to him" it is still not ranked.
Across the review's twelve cues, the index's own best match is returned for
12 (11 before). Recall's median time rose from about 44 to 53 ms. The live
store's index grows from 1,763 to 4,604 passages in the agent's scope (6.1 an
item, at most 23).

Changed behaviour: after the upgrade, everything indexed the old way waits to
be indexed again. Until it is, recall finds a memory by its whole-text vector
and its words, and a handoff or lesson by its words only, and the watchdog
flags what waits. Run `mnemos embeddings index` once (6.6 s on a copy of the
live store); otherwise the scheduled job catches up at 256 passages a run.
`passages_stored`, `memories_searchable` and `handoffs_searchable` count only
passages cut this way.

No schema version change: the index adds the `scheme` column to an existing
table the first time a writable index opens it, marking every row there 1 in
one transaction. No code-version bump: code older than this writes rows marked
1, which this code indexes again, and reads this code's rows as current, so
the two never cut the same text back and forth.

### A watchdog for silent failure

Every serious failure in this memory looked like success, and nothing watched
the queues: a maintenance report the briefing could not find, questions nobody
answered, lesson questions starved behind stale ones, old servers writing by
old rules. On a copy of the live store the watchdog found 133 questions shown
three times and never answered (5 of 179 ever answered), six Claude Code
sessions still writing with code older than the store, and 711 memories and
notes waiting more than a day for recall's meaning index.

- `mnemos_health` and `mnemos doctor` watch what should be moving: questions
  shown three times and never answered, and the answer rate; the newest
  maintenance report the briefing can find, against the maintenance since;
  cycles in the last 7 days and how many changed anything, and captures no
  cycle followed; lesson questions waiting more than 14 days to be shown;
  faded memories out of ordinary recall; sessions writing with code older than
  the store, each named with when it last wrote; the share of memories the
  agent did not write; what waits for recall's meaning index, and since when;
  and notes hidden because their memory went quiet or faded.
- Each check states what it expected and what it saw, in `mnemos_health`'s
  structured result under `watchdog`. Whatever has stalled for more than a day
  gets one ATTENTION line: a plain sentence and the command that fixes or
  inspects it. When all is well, nothing more is printed.
- A run of cycles that changed nothing is flagged only with evidence of work
  left undone: failing passes, memories the cycles never read, or fading
  memories never asked what they taught. A stable store whose cycles find
  nothing to change stays quiet. A change the briefing never reported stays
  flagged however long ago it was. A question's command carries the verdict
  it needs, so following it settles the question.
- It reads only. Every statement it runs is a read, it works on a store opened
  read-only, and on a copy of the live store the database and its write-ahead
  log were byte-identical after `mnemos doctor` and `mnemos_health`. A check
  that cannot run says so in its data and prints nothing.
- An older session is named by its session id as "below version N", the
  store's minimum: the exact version a session runs is not recorded anywhere a
  read can reach.
- "Nothing has been captured" is said only when nothing was. A scope whose
  notes are all hidden by their memories' fate, or were all forgotten, says
  that instead.
- The `Recall index: not updated` line folds into the watchdog's line about the
  meaning index when that one is printed, so it is said once.
- The continuity warnings follow the same rule, and no longer fire on the
  ordinary state between sessions, which taught the reader to ignore ATTENTION.
  A handoff waiting for the next session is flagged only after it has waited
  more than a day while sessions started without it. The same goes for
  continuity never handed to a starting session (not a new store's first day),
  a week without a delivery (only if memory was written since), and sessions
  without a capture (only once the last capture is more than a day old).

Changed behaviour: the health card and `mnemos doctor` end with ATTENTION
lines when something has stalled. `mnemos_health`'s structured result gains
`watchdog` and `counts.continuity_notes_hidden`, and `continuity` gains
`notes_hidden`. "A session handoff is waiting but has not been delivered yet"
is gone, and the four continuity warnings above now read as one sentence and
a command.

No migration and no code-version bump: nothing here writes.

### Recall that finds by meaning

Recall used meaning in name only. On copies of the live store:

- The meaning search took its top 20 over all 3,746 stored vectors before it
  checked scope, so across twelve cues 14 of 240 meaning hits survived and 1
  of 60 results arrived by meaning.
- Every reached memory re-fired on every hop, with no limit on its links, so
  memories with 20 to 32 links outscored the ones a question was about.
- Results were cut to the requested count before a filter dropped some, and a
  match by meaning alone was dropped unless it scored 1.35.
- 176 live memories (all of them lessons) and all 259 handoffs had no vector.
- Query recall never returned a handoff: in the lab's baseline, 0 of 28 facts
  that lived only in handoffs, and a superseded handoff led to a confident
  "no record".
- Loading the cached embedding model could hang on a network call.

What changed:

- The meaning search scores only what recall may return (the memories live in
  the caller's scope, and the handoffs) and only then takes its top.
- Words and meaning are fused by reciprocal rank, as Polyphonic fuses them:
  words 0.3, meaning 0.5, k = 60. A match by meaning alone is returned when its
  rank earns it.
- Resonance passes on from newly reached memories only, each contribution
  divided by the sender's links, for at most two hops. Dormant and archived
  memories neither relay nor receive, as before.
- Filter first, then cut: asked for five, recall returns five while matches
  remain.
- One list of common words (`mnemos/store/fts.py`), used by the search, the
  links and lessons made from words, the filters and identity's comparison.
- Handoffs join recall: the ones in use and the older ones (replaced by a newer
  handoff from their session, or retired), by their words and their meaning,
  under "Handoffs:", each with who left it and when. An older one says so. A
  forgotten one stays gone. A handoff never relays activation and never
  becomes a memory. Recall by id still reaches any handoff.
- Each row carries up to 300 characters of the item's own words (a memory's
  words, not its impact), so a list is usually enough to use.
- A capture's note and memory are one object, so a capture comes back once, as
  its memory. The "Continuity notes:" section is gone from recall; notes with no
  memory of their own (reports, notes written through other tools) come back
  under "Notes:".
- Recall's meaning index: each memory and handoff is cut into passages the
  model reads whole (it reads about 1,000 characters), with a vector for each,
  in a new table `passage_vectors`. It fills without depending on sessions:
  a handoff as it is written, up to 64 passages with each capture or
  correction, up to 256 each run of the scheduled job (`mnemos consolidate`,
  seven runs a day), and everything waiting with `mnemos embeddings index`,
  which indexes and does nothing else (no cycle, no decay, no links; a second
  run indexes nothing). Until an item has passages, recall uses its whole-text
  vector and its words. Code older than the store indexes nothing, so this is
  how what it writes gets indexed.
- Without the model, the scheduled job skips indexing and still consolidates,
  and the health card says so in one line (`Recall index: not updated ...`).
- A write never waits long on indexing. A capture, a correction or a handoff
  spends at most about 2 s embedding, and a network backend waits at most 2 s
  a call there, with no retry and no second try one passage at a time. What
  doesn't fit, or fails, waits for the scheduled job or the command. (With a
  slow provider, a handoff used to wait 120 s for the batch, then 30 s a
  passage.) The local model's one-time load is not counted.
- A note rewritten in place (a handoff corrected by its id, say) drops its
  passages with its old words, in the same transaction, and a correction
  re-indexes it within the write's budget. Recall also ignores any passage cut
  from words a note no longer holds, so it is never found by its old meaning.
- The local embedding model loads only from files on this machine
  (`local_files_only`). Downloading is one explicit step:
  `mnemos embeddings download`. A hanging network no longer blocks recall,
  health or doctor.
- `MAINTENANCE_CODE_VERSION` is 8: the word list changes how maintenance links
  and matches lessons, and indexing is new. Code older than the store records
  the agent's words and indexes nothing.

Measured on copies (the numbers are in the commit that makes the change):
across the review's twelve cues, 51 of 59 results arrived by meaning (1 of 51
before); of the lab's 29 missed facts, 19 now reach recall's top ten (6
before), 10 of the 13 that lived only in handoffs (0 before); recall's median
time fell from 151 to 42 ms.

Changed behaviour:

- Recall's output: "Durable memories:", then "Handoffs:", then "Notes:",
  each in rank order; `max_results` counts every row. Rows show a memory's own
  words where they showed its impact.
- The model no longer downloads the first time it is needed. On a machine
  without it, semantic recall is off until `mnemos embeddings download` has
  run; doctor and the health card say so.
- Maintenance and `mnemos consolidate` report a line, `Recall index: ...`,
  when they indexed something or could not.

Migration (schema 15). The first open by this code adds the table
`passage_vectors`, empty, after the usual verified pre-migration backup. On a
copy of the live store (schema 14), opening took 0.92 s, the backup (163 MB)
included; integrity ok. Then run `mnemos embeddings index` once: on that copy
it indexed 891 memories and handoffs (2,534 passages, five scopes) in 4.3 s
(7.3 s for the whole command), with no network; run again, it indexed nothing.
If the model has never been downloaded on the machine, run
`mnemos embeddings download` first.

### Standing preferences, marked by the agent

A standing rule is obeyed, not recalled, and nothing marked one. The
`preference` tag and the `foundational` domain are word matches, and on a
copy of a real store the plain-words rule (captured 2026-08-26) had never
been reinforced, corrected or versioned, never reached the briefing, and was
fading for disuse.

- `mnemos_capture(standing=true)` marks a memory as how the human wants the
  agent to work in every session, not just now. The mark is a typed choice,
  signed with the model, session and time, and never read from the words.
- `mnemos_correct` takes `action="mark_standing"` or `"unmark_standing"`
  with a memory's id (or its note's). Only the mark and its signature
  change: no words, no version.
- "Who you're with" opens with the standing memories: the newest mark first,
  up to five, one line each in the memory's own words with its id, then
  `And N more: mnemos_recall(query="", standing=true)`.
- `mnemos_recall(standing=true)` lists every standing memory. The query only
  orders them, and may be empty.
- A standing memory is exempt from decay while it is marked, and a
  correction keeps it standing.
- `MAINTENANCE_CODE_VERSION` is 7. Code older than the store records the
  words and ignores the mark.

Changed behaviour: once a memory is marked, "Who you're with" starts with the
line `Standing, how the human wants you to work in every session:` and the
foundational notes follow `Other notes:`. Without one, it reads as before.

Migration (schema 14). The first open by this code adds `standing`,
`standing_by`, `standing_session` and `standing_at` to `engrams`, with every
existing memory unmarked, after the usual verified pre-migration backup. On a
copy of a real store it took 1.05 s, backup included. The migration marks
nothing: the agent marks its standing rules itself.

### Every rule reaches the model; beliefs carry their ids

Claude Code shows a model only the first 2,048 characters of an MCP server's
instructions. Mnemos's ran to 3,021 characters (3,420 in advanced mode), and
every rule sat past the cut: "never narrate the machinery" began at character
2,210, then came the signing rules and "storage is local". So no model in
Claude Code was shown them (found in the lab, 2026-09-27: a session's copy
ended at character 2,047, mid-sentence).

- The instructions fit: 1,816 characters in simple mode and 1,972 in
  advanced, each held to 2,048 by a test that reads what each mode serves
  over the MCP protocol.
- The rules come first: never narrate the machinery, the six steps of the
  loop, sign every write, storage is local. The tool descriptions, which
  models see in full, carry the details.
- Each belief line in the briefing carries its id,
  `- <belief> (40%, belief_...)`, so a correction can name it: a belief
  changes only by its id.

Changed behaviour: anything that reads the briefing's belief lines now finds
the id after the confidence.

### One capture, one object; corrections that land once

A capture writes two things, a continuity note (what the briefing is built
from) and a memory (what the graph holds), and each correction path updated
one and not the other. Correcting by the note's id left the memory saying the
old thing; correcting by the memory's id left the note saying it in the
briefing; two corrections of one note left two live replacements; correcting
and then forgetting left the corrected memory live. No correction recorded
what it replaced. The capture itself committed the memory, the note and the
link between them separately, so a failure between them left half a pair. On
a copy of a real store (2026-09-27), `claude-code/user/global` held one pair
whose note and memory said different things (a note corrected by its id), and
three live notes over memories a correction by memory id had replaced, each
replacement without a note.

- A capture saves its memory and its note in one transaction, the note
  pointing at the memory; the memory's vector is written once that
  transaction commits (inside it, the vector's own connection would wait on
  the lock and fail, and encoding swallows that failure). Either id reaches
  both.
- Every correction path (the note's id, the memory's id, a query) retires the
  note and its memory together and writes the replacement pair, in one
  transaction; a forget retires both and writes nothing. The old pair is kept,
  archived, never deleted. An id a correction already replaced reaches its
  current version, so correcting or forgetting twice never leaves two live.
- A correction records what it replaced: a `supersedes` link from the new
  memory to the old, `lineage.supersedes` / `lineage.superseded_by` on both,
  the old note's `superseded_by`, and a version on the new memory keeping the
  old words (`change_reason` 'correction'), written only when the words
  change. The replacement pair and its version are signed with the
  corrector's model and session; a retired note's revision records who
  retired it (`revised_by`, `revised_by_session`).
- An impact given with a correction becomes a lesson about the mistake,
  drawn from the replacement (only the agent's own words make one).
- A correction never moves a belief by the words it shares with one: the
  word-overlap heuristic is gone. `mnemos_correct(target_id="belief_...")`
  retires a belief the agent stated (`action=forget`), or replaces it with the
  agent's words, formed at 40% as a stated belief is, the old one retired and
  pointing at it.
- Only one capture writing them together makes a note and a memory a pair
  (`graduated_to_engram_id`). A note that only references a memory
  (`related_engram_id`, as the advanced tools' summaries do) is corrected and
  forgotten on its own, never shares that memory's fate, and is never
  promoted into it. A corrected summary still references what it summarises.
- A note shares its memory's fate. When decay takes the memory dormant or
  into the archive, the note stops showing (briefing, recall, counts); when
  the memory wakes or `resharpen` restores it, the note is back. Nothing is
  copied between them. This is only what is shown: a correction or a forget
  by query still finds such a pair, and retires it, so waking it later
  cannot bring the old words back. Recalling the note by its id brings its
  memory back as recalling the memory's id would. The id of a note or memory
  a correction replaced says so and names the version now in use, never the
  old words.
- `MAINTENANCE_CODE_VERSION` is 6. Code older than the store still records a
  correction in the agent's words and retires what it names, and writes no
  link, lineage, version, lesson or belief change.

Migration (schema 13). The first open by this code adds `author_model` and
`author_session` to `versions` (empty for every existing row) and two indexes
on the note-to-memory columns, after the usual verified pre-migration backup.
Once per store (recorded in `meta.capture_pairs_linked`), it pairs a capture
note that named its memory only as a reference, when the note's words are
the memory's words as a capture writes them and the two were written within
10 seconds of each other (one capture call); no other row changes. On a fresh
copy of the real store it opened in under a second and paired none: its 200
capture notes were already paired, and its 9 notes with only a reference are
summaries whose words differ (all in `claude-field`).

Changed behaviour, and what to do:

- A correction by note id now answers with the new note's and memory's ids
  ("Continuity note ID", "Memory ID"); the note id changes, as the memory id
  always did. An impact given that way is saved.
- Correcting a belief needs its id; words alone no longer retire or lower one.
- Forgetting a note that only references a memory no longer archives that
  memory.
- Notes over dormant or archived memories leave the briefing. On the copy,
  its live notes went from 200 to 181: 16 over dormant memories and 3 over
  memories replaced by a correction.
- Pairs split before this change stay as they are; repairing them is a
  separate, approved step.

### Every memory says who wrote it

The memory could not tell the agent's words from a tool's. No memory recorded
its author. On a copy of a real store (2026-09-26), 103 of the 469 memories in
`claude-code/user/global` were the transcript indexer's model's words: memories
it extracted and lessons copied from them. A lesson copies the impact it is
drawn from, so a model's words landed in the most durable tier, and identity,
belief questions and lessons were all measured from them. And the signature
came from one declared model per scope: a Grok session that introduced itself
became the store's declared model for everyone.

- Every memory records `author_kind` (`agent`, `tool`, `system`, `import` or
  `unknown`), `author_model` and `author_session` (the harness session,
  `CLAUDE_CODE_SESSION_ID`), when it is written. A later save never changes
  them. Captures, corrections, reflections, handoffs and lessons are the
  agent's, and so is what it keeps through the advanced tools
  (`mnemos_remember`, `mnemos_ingest`, which take `signed_as` too). The
  transcript indexer's and the substrate's memories are a tool's; the deep
  reflection pass's thoughts are a tool's (with a model) or Mnemos's
  (without). A path that doesn't say is `unknown`, never guessed. Continuity notes already
  recorded their kind of writer (`authored_by`) and model; captures now also
  record the session.
- The signature is resolved on every write, because the model can change
  mid-session: `signed_as` (a new parameter on `mnemos_capture`,
  `mnemos_correct`, `mnemos_reflect` and `mnemos_handoff`, which the server
  instructions ask the agent to fill with its own model id), then
  `MNEMOS_AGENT_MODEL`, then the model *this* session last introduced itself
  as (kept per harness session, so another process of the session signs the
  same way, and never another session's), then the session's transcript.
  The SessionStart hook finds its reader the same way when the harness names
  no model. The health card and `mnemos doctor` show whom this session
  introduced itself as (model and name), or "none this session"; they no
  longer show the scope's last introduction, which named a Grok session.
- Only the agent's own words make it who it is: identity (the identity pass,
  `mnemos identity diff`, the identity graph), belief questions and theme
  mining read only `author_kind = 'agent'`, and a lesson is drawn only from an
  impact the agent wrote (`impact_source` 'agent') on a memory the agent wrote.
  The agent's evidence never strengthens a tool's "lesson", and the agent is
  not asked what a tool's memory taught. The packet signs a lesson a tool
  wrote "from a tool, not yours".
- `memory_trace`: one row per tool call (context, capture, recall, correct,
  reflect, handoff, introduce, maintain; health stays read-only), with the
  session, the signing model, the ids the call showed or returned and the ids
  it wrote (a memory recall restores from the archive counts as written). Ids
  only, never text. Rows older than 90 days are dropped.
- `mnemos repair quarantine-tool-written` moves the tool-written memories in
  a scope into the legacy quarantine (no person or project; their words,
  links and history stay), dry run unless `--write`, after a verified
  backup. `--undo --write` brings back exactly what it moved; `mnemos
  adopt-legacy --include indexer` brings them back with all the other
  tool-written memories the quarantine holds. It only runs by hand. On the
  copy it listed 103 (96 active, 7 dormant), moved them, and `--undo` restored
  the scope to the same 469 ids. The health card and `adopt-legacy` now call
  that class "written by a tool".

Migration (schema 12). The first open by this code adds the three columns,
after the usual verified pre-migration backup, and labels what the store held
once, from what each row carries: `tool` when tagged `session-indexed`;
`agent` for a capture or correction made through the agent's own tools (a
`session` memory tagged `continuity`) and for a lesson whose words are exactly
an agent-written impact of a memory it was drawn from; everything else
`unknown`. The counts are kept in `meta.engram_authors_labeled`. On the copy:
355 agent, 103 tool, 11 unknown in `claude-code/user/global` (356, 6,989 and
135 in the whole file), in under two seconds.

Changed behaviour, and what to do:

- `MAINTENANCE_CODE_VERSION` is 5. Sessions still running older code stop
  maintaining the store once this code opens it (restart them); what they
  capture meanwhile is recorded as `unknown` and so stays out of identity,
  belief questions and lessons.
- `mnemos daemon install` no longer schedules `substrate-tick`, whose handlers
  write memories in a model's words; installing or uninstalling removes one an
  earlier install scheduled. Neither do the OpenClaw generators
  (`mnemos setup-openclaw`, whose install replaces an earlier `mnemos-*`
  substrate job, and the bootstrap's cron commands); the
  `openclaw/crons/substrate-tick.md` template is gone. `mnemos
  substrate-tick` and `mnemos index` still run by hand, and say that they
  write a model's words.
- `health()["identity"]` is now `{session, model, name}` for this session's
  own introduction, in place of `declared_model` and `declared_name`.
- The legacy quarantine counts lessons distilled from indexer output as the
  indexer's (they copy its words), so a default `mnemos adopt-legacy` leaves
  them hidden; name `--include indexer` to bring them back.
- To move the indexer's memories out of recall and the packet: `mnemos repair
  quarantine-tool-written` (dry run), then `--write`.

### No one-way doors for memories that fade

A memory could leave the active set and never come back, with every check
green. Decay read active memories only, so a dormant one was never touched
again: it could neither finish fading nor come back. Recall seeded from
active memories only, so a dormant memory stayed out however exactly a cue
named it: on a copy of a real store, a recall of each dormant memory's own
distinctive words brought back none of its 24. A dormant or archived memory
reached through a link still passed activation on to its neighbours.
`archive.resharpen` had no caller, an archived memory's id returned nothing,
and the dream report said dormant memories were "ready to wake if needed".

- Recall seeds dormant memories that match the cue, at half the activation
  an active match would start with (at most 10, beside the active seeds), so
  an equal active match comes first. A dormant memory that is returned wakes:
  it is active again, with the accessibility any return gives it. Waking is
  part of the return, so it happens once per session, and a dormant memory
  recalled by its id wakes too. On that copy, the same recalls now bring back
  all 24, 19 of them first.
- Dormant and archived memories take no part in resonance: they pass no
  activation on, and none reaches them through a link. A dormant memory comes
  back for its own match, or not at all. Results show "(it had gone quiet)"
  beside one.
- Decay keeps running over dormant memories until they wake or reach the
  archive: every one of them, read a page at a time apart from the active
  ones, so none waits behind the limit on how many active memories one pass
  reads (10,000). The floors that hold an active memory up (recent use,
  `foundational`, `active_project`) never lift a dormant one. The decay stats
  count dormant memories apart, and `engrams_dormant` still counts only the
  ones that went dormant in that pass. On another copy, one maintenance cycle
  lowered all 24 and archived none.
- A memory that faded into the archive (archived by decay) comes back by its
  exact id, or through `mnemos_recall` with `include_archived=true` when the
  query names it (half its meaningful words, and two when it has two or more:
  the bar a correction's query clears). Every faded memory in the scope is
  weighed, however many there are. Either way it is restored with
  `resharpen` and counts as returned. A memory the agent forgot, or replaced
  with a correction, stays where it was put, by id and by flag.
- `resharpen` restores only a memory that is archived, in one transaction,
  and at full resolution when it brings back the original words, keeping the
  worn wording as a version. An archive row whose memory is active or dormant
  again is left alone; a copy of that store held 1,392 such rows.
- `mnemos_health` and `mnemos doctor` count dormant memories, and the faded
  ones an ordinary recall cannot reach, with the call that reaches them:
  `mnemos_recall("<its words>", include_archived=true)`. Doctor still opens
  the store read-only.
- The dream report says "N memories went quiet. A strong match brings them
  back." A cycle that archives some memories and quiets others reports both.
- `MAINTENANCE_CODE_VERSION` is 4. Code older than the store still reads
  dormant and faded memories, but wakes, fades and restores none of them. The
  decay pass checks the store's minimum itself, so callers without the
  runtime's gate (the bridge, the advanced server) leave dormant memories
  alone too.

Changed behaviour, and what to do:

- Recall and `mnemos_context` can return a dormant memory, marked "(it had
  gone quiet)", and returning it wakes it.
- `mnemos_recall` takes `include_archived` (default false). With it, what
  faded into the archive appears after the durable memories under "From the
  archive:", and comes back.
- `mnemos_health` returns `counts.memories_dormant` and `unreachable`
  (`count` and `command`), and the card's memories line counts dormant ones.
- Dormant memories no longer stay dormant indefinitely: unless recalled, they
  keep fading and reach the archive, where their id or `include_archived`
  finds them.

### One briefing, written for the one reading it

The session-start packet is where this memory does its work, and two builders
made it: the SessionStart hook's and `mnemos_context`'s. It showed each belief
three times (as a core belief, as a living question and in the list), printed
sections that are always empty in simple mode (scope, functional memory,
review queue, "How To Use"), ranked notes against a fixed sentence so recency
decided, and had lost its maintenance report: the report was looked for among
the 50 top-scoring notes, where it no longer ranks, so each cycle wrote a new
one instead of replacing the last. On a copy of a real store (2026-09-26) the
hook's packet ran to its 10,364-character ceiling and was cut off in the
middle of its question, and 117 reports were active at once.

- One builder, `build_context_packet`, makes the packet for the hook and for
  `mnemos_context`. Given the same session, model and folder they return the
  same text (checked on that copy: 5,975 characters from each).
- Six sections, in this order, each left out when it has nothing: **Where you
  left off** (the reader's own handoff whole, then up to two notes from the
  last three days), **Who you're with** (three foundational notes), **What
  you're carrying** (three notes or lessons), **Beliefs** (each once, with its
  confidence), **One question** (at most one, with the verdict call it takes)
  and **While you were away** (the latest maintenance report, only when that
  cycle changed something). A memory with nothing to carry gives no packet.
- A handoff another session of the same model left is framed as the reader's
  own ("Yours (Opus 5.5), from another session"). Only a different model's
  note is a colleague's and carries "don't claim its work as yours" (Riley's
  decision). A note whose author or reader can't be placed says so.
- What you're carrying is ranked by the distinctive words it shares with the
  names of the session's folder and repository (a worktree counts as its
  repository), then by recency. The hook reads the folder from its payload
  (`cwd`); `mnemos_context` uses its server's working folder, which Claude
  Code sets to the session's. The folder only ranks; it never chooses the
  scope. One of the three is always a concrete, dated episode (a note that
  names someone or something and something specific) when there is one.
- The packet stays under 6,000 characters (`--token-budget` now defaults to
  1500 tokens), and so does anything appended to it: `--include-graph` recall
  and `mnemos_context`'s results for a query get only the room left, and an
  entry that doesn't fit is left out whole. The reader's handoff is never cut.
  Notes are cut at a sentence boundary and end with their id, and
  `mnemos_recall("<id>")` returns any note the packet cut, a handoff, a
  continuity note or a lesson, whole. A forgotten note does not come back by
  its id.
- Asking for a memory by its id is a use: `mnemos_recall("<engram id>")`
  reinforces an active memory as a query that returns it would, once a
  session and never on code older than the store. A note read by its id is
  not reinforced (notes have no reinforcement), and the packet showing a
  memory is not a use: the briefing reinforces nothing. Graph recall
  reinforces only the entries it shows.
- The maintenance report is found by its tag, so each new report replaces the
  last again. Reports that piled up stay as they are.
- Code older than the store shows no question and spends no showing on the
  hook's path too, as `mnemos_context` already did.

Changed behaviour, and what to do:

- `mnemos_context` runs no maintenance. Upkeep still rides on captures and
  corrections, and `mnemos_maintain` runs it on demand. The tool is no longer
  annotated destructive. With a query, it appends what else matches after the
  packet (`### For "<query>"`), as recall finds it, leaving out everything the
  packet rendered (notes, handoffs and lessons); what the budget left out of
  the packet can come back here.
- The packet no longer shows the identity summary, functional memory, the
  review queue, the scope or identity-divergence notes (`mnemos recall` finds
  those). `build_context_packet` no longer returns `identity`, `signers`,
  `functional_memory`, `review_queue`, `session` or `stats`; it still accepts
  `session_id`, `max_functional` and `max_hypomnema` and ignores them, and
  `query` is used only for `include_engrams` graph recall.
- `MAINTENANCE_CODE_VERSION` stays 3: this changes what the packet shows, not
  how memory is written or maintained.

### Returns that mean something, and versions only when words change

Recall strengthens a memory because it came back to the one reading it. But
reconsolidation ran inside retrieval, before the runtime's own filters, so
memories the reader was never shown were strengthened, and linked to the ones
it was shown. Nothing limited how often a memory was reinforced: on a copy of
a real store, the most-returned memory had been reinforced 31,517 times.
Maintenance counted its own reinforcing of a lesson as an access. And every
return appended a full copy of the unchanged memory as a new version, while
every save wrote the whole history again: 124,493 of that copy's 125,431
version rows were such copies, and one maintenance cycle rewrote 29,379 of
them.

- Only what a result shows is reinforced. `mnemos_recall` and
  `mnemos_context` reconsolidate exactly the memories they return, after every
  filter, and link as co-activated only memories returned together. Finding a
  memory in order to forget it (`mnemos_correct` with a forget action)
  reinforces nothing.
- A memory is reinforced at most once per session: the Claude Code session
  (`CLAUDE_CODE_SESSION_ID`) when there is one, recorded in the store so every
  process of that session agrees; otherwise the server process. A second
  return in the same session changes nothing: no access count, timestamp,
  strength or link. This holds on every surface that reconsolidates through
  `ReactiveRetriever`.
- Maintenance never records an access. Reinforcing a lesson while softening
  no longer counts as reading it.
- A return writes no version. It updates the memory's access record and trace
  in place. A save writes a version only when it changes the memory's
  content, impact or resolution.
- Saving appends versions and never writes one again. A new version is
  numbered after the last one stored, not by its place in a list that may be
  partial: an engram found by text search carries no versions, and its
  snapshot used to overwrite version 1. On a copy of a real store, one
  maintenance cycle now writes no version rows (29,379 before) and took 3.12 s
  instead of 3.33 s (median of three runs each).
- `mnemos repair-versions` removes the copies returns left behind. A row goes
  only when a return wrote it and it repeats the row just before it in that
  memory's history; the first row of every run stays, and so does every row
  written for another reason (softening, its repair). It is a dry run unless
  `--write`, and reads the store read-only until then. With `--write`, a
  verified backup comes first (`backups/<db>.pre-repair-versions-<stamp>.db`),
  then the copies go in one transaction and nothing else changes. A second
  run finds nothing. On a copy of a real store: 124,321 of 125,431 rows go
  and 1,110 stay. The file keeps its size, since SQLite reuses the space; a
  `VACUUM` took that copy from 162.8 MB to 101.3 MB.
- A new table, `session_reinforcements`, records which session has reinforced
  which memory. The schema script creates it when a store opens. Nothing is
  migrated, so the schema version stays 11, and an older Mnemos ignores it.
- `MAINTENANCE_CODE_VERSION` is 3. Code older than the store reinforces
  nothing on any path, and records no session's reinforcement, so current
  code still makes the one that session is due.
- Every writable open of a store now records the code version, after its
  migrations and only ever raising it. Only a simple-mode server recorded it,
  when it started. The session-start hook, `mnemos search`, the prompt
  builder, the bridge, the advanced server and the shared pool open their
  own stores and reinforce by current rules, so a store they wrote could stay
  marked for older code, and a server running that code never stood down. If
  another process holds the write lock, the store still opens and the next
  opener records it. A read-only open (`mnemos doctor`) records nothing.

### Beliefs change only for real reasons

A belief is something the agent said yes to. Mnemos guessed instead: any
answer to a belief question formed a belief, a declined one included; the
answer's first letters decided the rest, so "Now more than ever" retired a
belief and "No, they don't contradict" recorded a contradiction; a "no" to a
contradiction question deleted every link from one memory to the other; and
without a model, a capture sharing one word with a belief and containing
"not" (which also matches "note") lowered it by 0.05 and linked the capture as
contradicting it. Nothing could raise a belief: a reaffirmation question could
never be asked, because the answered question that formed the belief held its
place in the queue.

- `mnemos_reflect` takes a `verdict`, and the verdict alone decides what
  happens. The words are kept as written and never read for a yes or a no.
  - "Is that a belief you hold?": `hold` forms it from the agent's words at
    0.4; `decline` forms nothing; `not_now` leaves the question open.
  - "Still true?": `hold` raises it by 0.05 (never past 0.99); `retire` sets
    it to 0 and stops it shaping context, keeping the belief; each is a
    revision entry carrying the agent's words. `decline` leaves it as it is;
    `not_now` leaves the question open. Nothing is deleted.
  - A contradiction: `contradicts` leaves exactly one CONTRADICTS link between
    the two memories and changes nothing else. It no longer lowers the
    earlier memory's strength: the verdict says the two conflict, not which
    one is wrong. `compatible` removes only a contradiction link from this
    memory to the other, and every other link stays; `unsure` changes
    nothing.
  - A lesson or what a memory changed: `answer`, or `skip` to close the
    question and leave the memory as it is.
- Without a verdict, a belief or contradiction answer is kept on its
  question, which stays open, and nothing is formed, retired or linked. The
  result says which verdicts the question takes, and both packets (the
  session's and the session-start hook's) show the call for such a question
  with `verdict="…"` and a line naming its verdicts. A lesson or impact answer
  without one is still its answer. Hosts calling `reflect` through the host
  mutation protocol pass `verdict` in its arguments to act on belief and
  contradiction questions.
- Without a model, a capture never lowers a belief and never writes a
  CONTRADICTS link. The model-configured path is unchanged.
- `mnemos repair keyword-contradictions` undoes what that check wrote, for
  one agent across its scopes. It is a dry run unless `--write`, and reads
  the store read-only until then. Its revisions are found by their reason
  ("Contradicted by new evidence: ", where the model path writes "... (impact
  0.60): ...") and their 0.05 step. Its links (CONTRADICTS, formed at
  encoding, strength 0.7, to the memory a belief rested on) have the model
  path's exact shape, so one counts only when its note shows it was saved
  without a model: a link formed by keyword overlap at encoding, or a
  revision of the check that names it. Links whose note a model weighed, and
  links nothing explains, are listed and left. With `--write`, after a
  verified backup (`backups/<db>.pre-repair-keyword-contradictions-<stamp>.db`),
  the check's links go and each active belief it lowered gets back what those
  revisions took, as a new revision that says so. No history is deleted, other
  revisions stand, retired beliefs keep their confidence, and a second run
  finds nothing. On a copy of a real store: 32 links from 16 notes and 4
  revisions; both beliefs 0.30 -> 0.40; 4 links of the shape left as
  ambiguous.
- A belief the agent has not formed or reaffirmed for 30 days may be asked
  about again ("Still true?"), at most once a month, as its own kind of
  question (`reaffirm`), under the packet's usual two-question cap. A theme
  the agent declined is not asked about again.
- Schema v11. SQLite cannot widen a CHECK in place, so opening a v10 store
  rebuilds its reflection queue with every row kept, after a verified backup
  (`backups/<db>.pre-v11-<stamp>.db`). The queue's unique index keeps its
  name, so an older Mnemos still opens the store.
- `MAINTENANCE_CODE_VERSION` is 2. Code older than the store answers only
  impact and lesson questions, as before. Every other question (belief,
  reaffirmation, contradiction, or a kind it does not know) stays open
  whatever the verdict, and the agent's words and verdict are kept as a
  signed note. It asks no reaffirmation.

### Old sessions stop maintaining a memory newer code has moved on from

A Claude Code session keeps the Mnemos code it imported when it started, and a
session can run for days. Every server started before an upgrade went on
maintaining the same store by the old rules (decay, linking, softening,
lessons, questions, beliefs, identity) after newer code had replaced them, and
nothing in the store could tell it to stop. `mnemos doctor` also wrote to the
store it was checking: it built a context packet, which ran maintenance and
used up the showings of pending questions. On a copy of a real store, one
doctor run logged a maintenance cycle, used two question showings and moved
the session counter.

- Each store records the newest maintenance code version that has opened it
  (`min_code_version` in its meta table). A server raises it when it starts
  and never lowers it.
- Code older than the store records the agent's words and applies no rules
  to them. It takes the agent's own captures, handoffs, reflections and
  corrections, because refusing those would lose memories, but:
  - it runs no maintenance, whether through a session or `mnemos consolidate`;
  - recall and the context packet still return what they find, but a return
    changes nothing: no access count, strength, version row or co-activation
    link;
  - a capture or a correction is saved in its own shape (classification,
    full-text index, vector) with no links to other memories and no weighing
    against beliefs. Maintenance under current code links it later: on a copy
    of a real store, one pass linked five such captures;
  - a correction lands on the memory it names, but never lowers or retires a
    belief, and gets no placeholder where its meaning would go;
  - questions wait for a current session. The packet shows none and spends
    no showings. Only an answer about what a memory changed or taught is
    taken: it lands on that memory, and filing it as a lesson waits for
    current code. Any other answer, to a belief or contradiction question or
    to a kind of question newer code added that this code has never heard
    of, is kept as a signed continuity note that names the question, which
    stays open;
  - a handoff replaces only its own session's note and retires no other
    session's.

  Old code never moves a belief by any path.
- A store's `schema_version`, like its `min_code_version`, only ever rises.
  Every open used to stamp the opener's own version, so older code lowered
  what newer code had recorded. Opening a store that is already up to date
  no longer changes the file at all.
- Every result it returns (capture, recall, context, reflect, correct, handoff,
  introduce) ends with one line: "This session runs older Mnemos code than
  the store expects. Restart the session." The agent inside a stale session
  is the only one who can see it. With current code nothing changes.
- `mnemos_health` and `mnemos doctor` show the running version and the
  store's minimum. When a session is older they say so, and what to do:
  restart the session, and if it still says so, update Mnemos or reset the
  minimum.
- `mnemos repair min-code-version` shows both versions and, with
  `--set N --write`, lowers or raises the minimum. It first makes a verified
  backup of the store exactly as it found it
  (`backups/<db>.pre-repair-min-code-version-<stamp>.db`). It refuses N below
  1, and only a human runs it.
- `mnemos doctor` now opens the store read-only and changes nothing. It no
  longer prints a context packet.

Servers started before this change have no gate: they keep maintaining by
their old rules until they are restarted. The gate protects every later bump.
Each change to how memory is written or maintained raises
`MAINTENANCE_CODE_VERSION` in `mnemos/code_version.py`, and from then on an
older server stops maintaining any store the newer code has opened.

### Parallel sessions keep their own handoffs

There was one handoff slot per scope, so when several sessions worked the same
scope at once, each session's handoff replaced whatever another session had
left, and the next session in either thread was handed the other thread's note
first. On one real store, 61 of 208 handoff replacements came from a different
session, and 18 of those replaced a note no session had read. Agents had
started writing combined handoffs to carry each other's threads.

- A handoff now belongs to the session that wrote it. Claude Code gives every
  MCP server `CLAUDE_CODE_SESSION_ID` and gives the SessionStart hook the same
  id, so nothing is asked of the agent or the human. A new handoff replaces
  only the note its own session left before; other sessions' notes stay.
  Clients that don't identify their session keep one shared note, as before.
- The packet hands a session its own note first (after compaction or a resume
  it gets its own thread back), otherwise the newest note, whole. Up to two
  other sessions' notes from the last three days follow as one short, signed
  line each, with the id to read one whole through `mnemos_recall`.
- A note from another session is framed as a colleague's even when the same
  model wrote it, and "the same model as you… Carry on from it" is said only of
  a note this session left.
- At most eight sessions' notes stay active per scope; beyond that the oldest
  is retired, with its prose kept in history.
- Handoffs no longer take continuity slots: the packet, `mnemos_context` and
  `mnemos_recall` leave them out of the ranked continuity search.
- Fixed: `mnemos_correct` with a `query` could land on the active handoff and
  overwrite its exact text with the correction, or forget it. A correction
  found by searching now never touches a handoff.

Schema v10 adds `hypomnema_entries.author_session` and lets the handoff index
hold one active note per session. The store upgrades itself on open, after a
verified backup (`backups/<db>.pre-v10-<stamp>.db`); on a 162 MB real store
that took two seconds. Existing notes keep an empty session and stay as they
are. An older Mnemos can still open a v10 store: the index keeps its name, and
while an unidentified note is active an older writer replaces that one rather
than a session's. A session opened before the upgrade runs the older code until
it restarts.

### Memories the scope migration hid

Schema v6 (0.2.1) gave every engram a person and a project. A legacy engram
linked to exactly one continuity scope was backfilled into it; every other one
was left unscoped and quarantined from scoped reads, so it could never be shown
to the wrong person. The quarantine is right and stays the default. What was
missing was any sign of it and any way out. Unscoped rows never reach recall,
never seed or carry spreading activation, and are skipped by scoped maintenance,
while every count reported only the scoped rows. On one real store the health
card read "186 active" over a file holding about 7,000 engrams, 105 of them
lessons distilled from experience.

- `mnemos_health` and `mnemos doctor` now say how many older memories never
  reach recall, split into lessons, other memories, and transcript-indexer
  output. Doctor raises ATTENTION only while lessons or other memories remain
  hidden; indexer output left out is the recommended state.
- `mnemos adopt-legacy` brings them back, and only a human runs it. It is a dry
  run unless `--write`, shows what would return, makes a verified backup
  (`backups/<db>.pre-adopt-legacy-<stamp>.db`) before anything moves, and
  adopts into the resolved scope. By default it brings back lessons and other
  memories, never archived rows, and never transcript-indexer output unless
  named with `--include indexer`. On a copy of the real store, adopting
  everything took all five recall slots for three of eight ordinary questions,
  while lessons and other memories changed two of sixty.
- It will not choose between people: when the agent holds memory for anyone
  other than the target person, it refuses until `--person-id` and
  `--project-scope` are given explicitly.

To recover an older store: `mnemos adopt-legacy --agent-id <agent>` to review,
then the same command with `--write`.

### Signed notes

One scope is often shared by several models. The same `claude-code` store is
written by whichever model the human is running that day, and every handoff
used to arrive as "From your previous session, in your own words", so each new
model inherited the previous one's first person and carried on as if it had
done that work. Every note is now signed with the model that wrote it.

- Schema v9 adds `hypomnema_entries.author_model`. It is added in place on open
  with one verified pre-migration backup; existing notes stay unsigned, and
  nothing is backfilled or guessed.
- Signatures come from `MNEMOS_AGENT_MODEL`, then `mnemos_introduce` in the
  current session, then the harness. Claude Code is detected from the session
  transcript (`CLAUDE_CODE_SESSION_ID`), reading only the tail of the file for
  the latest assistant turn's model id. Otherwise the note is unsigned.
- `mnemos_introduce` now signs the introducing session only. It used to be
  stored once per scope, so the last model to introduce itself stood for all.
- The handoff heading names its author: "Left by Fable 5.1 (claude-fable-5-1),
  18 hours ago." When the reader is known (a `model` field in the SessionStart
  payload, or detection in `mnemos_context`), the packet says whether it is the
  same model. An unsigned handoff says so and asks the reader not to assume it
  wrote it.
- Continuity notes show `by <model>`, `unsigned`, `co-formed`, or `Mnemos`.
  When a scope has notes from more than one model, the identity section says
  it is shared.
- Corrections re-sign the corrected note and record the prior signer. A
  reflection keeps the note's signature and names its own author inline.
- `mnemos_capture` and `mnemos_handoff` answer with the signature they wrote,
  or with how to sign when they could not tell.

Host adapters can now execute durable Core mutations through a versioned,
host-neutral exactly-once contract. An idempotency claim, every canonical
SQLite effect, and the serialized result commit atomically; a retry returns the
original result, while reuse of a key for a different request fails closed.

- Adds `MnemosRuntime.execute_host_mutation()` protocol v1 for `capture`,
  `correct`, `maintain`, `reflect`, and `introduce`.
- Adds the schema-v8 `host_mutations` replay ledger without changing the v7
  handoff model or migration behavior.
- Makes store commits transaction-aware so multi-table Core operations roll
  back completely after exceptions or process interruption.
- Treats embeddings as a rebuildable cache outside the canonical transaction;
  host mutation execution suppresses embedding writes until the transaction is
  complete.
- Adds replay, conflict, concurrent-delivery, upgrade, and failure-injection
  coverage, including crashes after each multi-table capture stage.

## 0.3.0 (2026-08-01)

Agent-written session handoffs. The agent can now leave one exact, private note
for its next session with `mnemos_handoff`. The newest handoff is delivered
first at startup, in full and only once in the packet, with its age and a quiet
instruction to continue naturally.

- One active handoff per agent/person/project scope, enforced in SQLite and
  replaced atomically while prior versions remain recoverable.
- Handoffs are never summarized, rewritten, promoted, decayed, or expired.
- Schema v7 records entry kind, authorship, author identity, last delivery, and
  delivery count. Ambiguous legacy writing remains `unknown`.
- Deterministic maintenance now uses neutral system language and is clearly
  separated from the agent's own words.
- `mnemos_health` reports handoff save/delivery/authorship state and warns
  when stored continuity is not reaching sessions.
- Claude Code startup injection remains supported. Codex now has an idempotent
  `mnemos hooks install codex --write` path covering startup, resume, clear,
  and post-compaction reinjection while preserving unrelated hooks.
- The installed-wheel audit now expects nine tools and performs a real
  session-A → handoff → fresh session-B transition.

## 0.2.1 (2026-08-01)

Production-hardening release. This release closes security, privacy, scope,
recovery, and installation gaps found during the 0.2.0 release audit.

## 0.2.0 (2026-07-31)

Two things happen in this release. Continuity starts arriving on its own —
loaded at session start and captured as work happens, with nobody asking for
it. And memory stops being a notebook the agent writes to and becomes something
the agent *maintains*, in its own voice, on an install with no API key.

The first half is plumbing that was missing: scope that matches between the
write and the read, a session-start hook, background maintenance, and an
honest signal for when memory comes back empty. The second half is the one the
project was named for — the five shifts that were supposed to make this a mind
rather than a log, four of which did not actually run until now.

**Start here if you are upgrading:** two breaking changes are listed under
*Changed* — the default database path and the distribution name. Existing
stores migrate in place.

### What Mnemos is
Clarified throughout, because the previous framing caused a real failure. Mnemos
is a continuity and identity layer for the agent itself — it carries what the
agent should know about you and how you work together, across sessions. It is
**not** a general memory or retrieval system, and it runs alongside whatever you
already use for that. Pointing general recall at it buries the continuity layer:
on one live install the transcript indexer had written ~7,058 engrams against 13
deliberate captures, and a session packet spent five of six long-term slots on
paraphrases of a single harvested fact.

### A memory that maintains itself
Mnemos's design came from a session that asked one model what it would want if
the memory were its own to inhabit. Five shifts came out of that, and the
explainer has always claimed them — *"most AI memory is a notebook; this is a
mind."* Measured against a real store, four of the five did not run. Each one
needed a model, and the install the README advertises has none.

They run now, because the direction inverted: **the server never calls a model.
It asks the agent.** Maintenance proposes the work that needs judgement, and the
agent answers in its own turn, in its own words — that answer becomes part of
its memory. Consolidation stopped being something done *to* the agent and became
something it does. This works in every MCP client, needs no key, and made the
whole affinity system that used to police which outside model was allowed to
maintain an agent's memory unnecessary — that question is answered by
construction now (201 lines removed).

- **`mnemos_reflect`** — the eighth simple tool, and the only one whose entire
  job is to let the agent's own voice into its own memory. The context packet
  may quietly raise a question — what a capture changed, what a fading memory
  taught — and the agent answers it here. Nothing is written on its behalf; if
  no true answer comes, the prompt fades on its own. Restraint is enforced, not
  hoped for: at most two requests per packet, each shown at most three times
  then dropped, quiet scopes show nothing.
- **Traces, not records** — a capture can carry an `impact`: not what happened,
  but what it changed. That sentence is what survives when the details fade, and
  only the agent can write it, so the server never fills it with a template. An
  empty impact is left empty and asked about later.
- **Forgetting that teaches** — as a memory fades, the lesson in it is distilled
  and kept while the detail softens. With no provider the words are left intact
  and the fade lives in ranking, never a rewrite the store cannot undo.
- **Surprise as growth** — a capture that does not fit what is already held is
  encoded more deeply. This no longer depends on pre-existing beliefs or a
  model, so it is no longer skipped.
- **Resonance over search** and **identity from the graph** — retrieval spreads
  through typed connections, and identity is measured from what the agent keeps
  returning to rather than narrated. Honest limit worth stating: without a
  configured provider, edges the encoder cannot judge are labelled
  `co_activated` — *these came up together* — rather than guessed into a
  semantic type. The graph is honestly labelled, not richly typed; semantic
  relations still need semantic judgement, which is the one thing a provider now
  buys.

### Proof
- **The continuity assay** — spawns real subprocesses and passes no scope
  arguments, because defaults are what an agent actually gets. Covers a capture
  surviving into a later session, a capture written in one directory being
  readable from another, earlier captures not being displaced, reading never
  creating a store, and a corrupt store never failing a session. Reintroducing
  the cwd-derived scope makes it fail; the fix makes it pass
- **Health that reports absence** — `mnemos_health` and `mnemos doctor` now
  report notes held, empty-packet streak, and sessions since the last capture,
  and say plainly when memory is being read but coming back empty. Every failure
  this system has had looked like success from the outside; this is the signal
  none of them could fake
- **Retrieval mode is legible** — `doctor` states whether recall is semantic or
  keyword-only instead of leaving it to chance

### Background Maintenance Without OpenClaw
- `mnemos daemon {install,status,uninstall}` — schedules maintenance with whatever the host provides: launchd on macOS, systemd user timers on Linux, crontab as a fallback. Background continuity previously existed only as OpenClaw cron templates, so every user without OpenClaw had a memory system that did nothing between sessions. The job logic was never OpenClaw-specific — `mnemos consolidate`, `mnemos substrate-tick` and `mnemos index` are plain CLI commands, and only the scheduling was bound to OpenClaw
- Jobs are namespaced per agent, so several agents keep separate maintenance on one machine. Reinstall replaces rather than stacks, and the crontab backend only ever removes lines it wrote
- The model-mediated `index` job is omitted unless a provider is configured, rather than waking every 30 minutes to do nothing
- Nothing is scheduled without `--write`; `mnemos doctor` reports whether background maintenance is active
- On macOS, warns when Mnemos is installed under `~/Documents`, `~/Desktop` or `~/Downloads` — scheduled jobs do not inherit Full Disk Access, so they fail with a permission error even though the same command works by hand
- OpenClaw is now documented as one optional integration for agent-mediated jobs (observer sync, `MEMORY.md` upkeep, briefs) rather than as the way background work happens

### Continuity Without Manual Triggering
- Server instructions — both MCP surfaces now ship `instructions=` to the client, so an agent is told to load context at session start, capture durable things as they appear, and correct rather than contradict. Previously nothing instructed the agent to use memory at all; continuity only happened when a human asked for it
- `mnemos hooks install [--write]` — registers a Claude Code `SessionStart` hook that injects the continuity packet before the first turn. Preserves unrelated hooks and settings keys, replaces its own entry on reinstall rather than stacking, and refuses to overwrite an unparseable settings file
- `mnemos hook session-start` — the subcommand the hook runs. Injection logic ships with the package instead of going stale inside a generated script. Fails silent by design: any error, or a missing or corrupt store, exits 0 with no output
- Reading memory no longer creates a database as a side effect — a mistyped `--db-path` used to mint an empty store at every session start and then report a healthy, permanently empty packet

### Fixed
- **Scope split-brain.** The simple tools resolved scope through `resolve_scope` while the advanced tools took their literal parameter defaults (`default`/`user`/`global`). `mnemos_capture` wrote continuity into one partition and `mnemos_context_packet` read from another, both reporting success, so an agent silently had no memory. All 13 scoped tools now resolve through one shared resolver
- **`project_scope` no longer derives from the process working directory.** An MCP server's cwd is chosen by whichever client spawned it, so a cwd-derived scope partitioned one agent's memory by launch location. It now defaults to `global`; explicit arguments, `MNEMOS_PROJECT_SCOPE` and config still win
- **The CLI, simple mode, and advanced mode used three different combinations of agent id and database.** `mnemos stats` and `mnemos serve` reported on different stores. All entry points now share one resolver
- `ConsolidationDaemon(config={})` in the `mnemos_consolidate` tool, the CLI `consolidate` command, and `bridge.py` silently dropped the entire `consolidation` block of `config.json` — decay rate, thresholds, and `min_idle_minutes` all fell back to hardcoded defaults
- A function-local `Belief` import left the name undefined for the second seed belief in setup step 5; the resulting `NameError` was swallowed and the belief silently dropped
- Duplicated `foundational, foundational` label in the context packet
- **`pip install` produced a dead server.** The `mcp[cli]` dependency was declared `>=1.0.0` with no ceiling, so a fresh install resolved mcp 2.0 — which removed `mcp.server.fastmcp`, the module every server entrypoint imports — and the server died on import. CI never caught it because it installs from the pinned lockfile. Bounded to `<2`, with a wheel smoke job that installs unlocked from PyPI, plus a unit test guarding the declared ceiling
- **`forget` did not forget.** A successful `mnemos_correct(action="forget")` archived the memory and left `recall` silent — and the text was still read back to the agent, on both delivery paths: the session-start hook replayed it for three sessions from a frozen queue excerpt, and `mnemos_context` quoted it in the verification block with an instruction to say it aloud. Two snapshots taken at write time that no deletion reached. The rule now: no packet block renders a frozen copy of note text; every block re-reads by id and skips a memory that is gone. Older stores are cleaned during maintenance
- **A reflection did not reach the agent.** `mnemos_reflect` wrote the answer only to the engram, and the session packet is built from the continuity layer, which excludes the engram graph by default — so the one sentence the whole inversion exists to obtain was unreachable from the automatic path. It now lands in the continuity note as well; answering twice revises rather than stacks
- **Softening could erase what it could not read.** With no provider, the fade step truncated a memory to "An impression related to X... [faded]" and left the impact empty, with no way back. The default now leaves the words intact and lets the fade live in ranking; `mnemos repair-softening` (and a `mnemos doctor` prompt) restore memories an earlier version truncated, from each memory's own pre-fade snapshot
- **Identity reported its own bookkeeping.** "Persistent concerns" counted every tag, including the classifier and indexer labels Mnemos stamps on nearly every memory, so an agent read back `trace-type:fact, session-indexed, decision` as who it was. Those are excluded now; when nothing meaningful remains, the line is omitted rather than fabricated

### Changed
- **BREAKING:** advanced mode and the CLI now default to `~/.mnemos/<agent>.db` rather than `~/.mnemos/memory.db`, matching what simple mode already did. Pass `--db-path` or set `store.db_path` in `config.json` to keep reading an existing store
- Distribution renamed from `mnemos-memory` to `mnemos-continuity`. `mnemos-memory` is a different author's package on PyPI, and the published install instructions pointed users at it. The import package and CLI command are unchanged
- Engrams now record `impact_source` — who wrote the trace: `agent` (via `mnemos_reflect`/`mnemos_capture`), `model` (extracted by a configured provider), or `template` (server boilerplate). The product's claim is that only the agent can say what a memory changed, and this makes an agent-authored impact distinguishable from a generated one instead of something later reconstructed from a boilerplate denylist. Schema version 3 → 4; existing stores migrate in place and their prior impacts read as unknown, never back-filled with a guess

### Simple Mode (five tools → eight)
- Onboarding ritual — a fresh scope's first context packet walks the agent through a short get-to-know-you script (name, current work, durable facts); stores that predate onboarding are grandfathered and never see it
- mnemos_introduce — the agent declares its own model id and name, so its memory knows whose it is (an explicit MNEMOS_AGENT_MODEL still takes precedence)
- mnemos_reflect — the agent answers, in its own words, a reflection the packet raised; see *A memory that maintains itself* above
- Cross-session memory verification — the first context packet after a real restart quotes the very first capture back to the human, once, as proof that memory survived the goodbye. It re-reads that memory live, so a capture the human later forgot is never resurfaced
- Dream journal — consolidation cycles that did meaningful work leave a short first-person narrative, surfaced in the next context packet ("While you were away")
- mnemos_health — truly read-only, human-relayable health card: store location and size, memory counts, last maintenance cycle and who performed it, onboarding and verification progress, latest dream entry, and whether any memories are recoverable from an earlier version's truncation

## 0.1.0 (2026-04-05)

Initial release.

### Core Memory Engine
- Engram model with dual-trace (strength/stability/accessibility)
- 7 typed connections (supports, contradicts, causes, extends, parallels, synthesizes, grounds)
- Beliefs with confidence tracking, revision history, epistemic bounds [0.05, 0.95]
- 6-dimensional emotional state (curiosity, clarity, warmth, tension, surprise, focus)
- Graph-based identity computation
- SQLite backend with FTS5 full-text search and WAL mode

### MCP Server (9 tools)
- mnemos_setup — 10-step conversational onboarding wizard
- mnemos_remember — encode memories with impact, confidence, connection discovery
- mnemos_recall — spreading activation retrieval with emotional biasing
- mnemos_inspect — full engram details with version history
- mnemos_status — system health and statistics
- mnemos_beliefs — list beliefs with confidence and revision count
- mnemos_shared — query shared memory pool
- mnemos_forget — graceful archiving (soft delete)
- mnemos_consolidate — trigger decay, connection discovery, softening, belief review, reflection

### Cognitive Substrate
- Background tick loop (configurable interval, default 4h)
- 6 handlers: dreaming, wandering, surprise, reflection, insight, initiation
- Cognitive modulators (arousal, resolution, openness, selection_threshold, social_drive)
- Production guardrails: skip_surprise_detection on all handler outputs except surprise, per-handler throttles, confidence change caps

### CLI
- mnemos init, serve, stats, search, inspect, consolidate, export
- mnemos substrate-tick, index, bridge {status|recall|remember}
- mnemos setup-openclaw

### Multi-Agent
- Shared memory pool with visibility controls
- Agent relationship tracking with trust scores
- Per-agent isolation with optional cross-pollination

### Embedding Support
- Google Gemini embeddings (3072 dims)
- Local sentence-transformers fallback (384 dims)
- Graceful degradation to FTS5-only when no embedding backend available
