# The notebook for a host: `mnemos interface`

An app the person uses (a host, such as Polyphonic or Ghost) can show the whole
Mnemos notebook, and let the person do everything the notebook's own page lets
them do, through one process it starts and keeps:

```bash
mnemos interface --db-path <store> --agent-id <agent> --person-id <person> \
  --project-scope <project> [--as-person] [--strict-scope]
```

The host writes one JSON request a line on the process's stdin and reads one
JSON answer a line on its stdout, in the same order:

```json
{"id": 7, "command": "summary"}
{"id": 7, "result": {...}}
{"id": 8, "error": "One plain sentence that says why."}
```

`id` is whatever the host sent (a number or a string), given back as it was.
An answer has either `result` or `error`, never both. An error is one plain
sentence, never a trace and never the name of a Python error. Times are ISO 8601,
in UTC.

- **Only closing stdin ends the process.** A line that isn't JSON, holds bytes
  that aren't UTF-8 text (or an escape like `"\ud800"` that stands for no
  character), or is nested too deep to read gets one sentence back, with its
  `id` when the `id` could be read and `null` when it couldn't, and the next line
  is answered as usual.
- **A blank line gets no answer**, so a host must not wait for one. Only a
  newline (`\n`) ends a request; a carriage return inside a line doesn't.
- A number past 9,223,372,036,854,775,807 (the most SQLite holds) is refused in
  a sentence, and a file at `--db-path` that isn't a memory is answered "The
  file at … isn't a memory Mnemos can read." from every command that reads it.

## Start here: `hello`

Ask it once, when the process starts, to learn what this Mnemos can do.

```json
{"id": 1, "command": "hello"}
```
```json
{"id": 1, "result": {
  "protocol": 1, "mnemos": "0.7.0", "schema": 19,
  "commands": ["memories", "search", "correct", "forget", "journal", "notes", "reply", "note",
               "hello", "notebook", "summary", "read", "hours", "shared"],
  "parts": ["life", "memories", "pulse"],
  "writes_as": "person", "strict_scope": true,
  "scope": {"agent_id": "nova", "person_id": "riley", "project_scope": "demo",
            "db_path": "/Users/you/.mnemos/nova.db", "held": true}}}
```

- `protocol` goes up only when a request or a result a host already reads
  changes. A new command, or a new key in a result, leaves it where it is, so
  read results by key and ignore keys you don't know.
- `commands` is everything this build answers. An older Mnemos answers `hello`
  with an error (`There is no command "hello" here; ...`): that is a Mnemos from
  before this page, which answers only the first eight.
- `schema` is the store schema this build writes.
- `writes_as` is whose a correction or a forget will be: `person` or `agent`
  (see `--as-person`).
- `scope` is the one memory this process reads and writes, and `held` whether
  its store is there yet. Nothing here ever makes a store.

## The notebook: `notebook`

Each part of the notebook, exactly what the notebook's own page (`mnemos log`)
is given, made by the page's own code. Show what the page shows from it.

| `part` | what it is | the page's file |
|---|---|---|
| `life` | who the mind is, its quiet hours and their schedule, its settings, the shared notebook, the journal, the notes, what it made, what its memory asks it, its memory's counts, its beliefs, the notes it left itself | `life.json` |
| `memories` | every memory, whole, with how each is tied to the others and how often it came back | `memories.json` |
| `pulse` | what came to the mind since `since` (with none, the last minute) | `pulse.json` |

```json
{"id": 2, "command": "notebook", "part": "life"}
{"id": 2, "result": {"part": "life", "document": {...}, "pictures": {"week.png": "/Users/you/.mnemos/studio/nova/week.png"}}}

{"id": 3, "command": "notebook", "part": "memories"}
{"id": 3, "result": {"part": "memories", "document": {"version": "b5499bd1028d", "made": "...", "memories": [...], "recalled": [...]}}}

{"id": 4, "command": "notebook", "part": "pulse", "since": "2026-11-20T09:00:00+00:00"}
{"id": 4, "result": {"part": "pulse", "document": {"now": "...", "events": [{"key": "t1", "at": "...", "kind": "kept", "ids": ["engram_..."], "session": ""}]}}}
```

- `memories.version` changes only when the memories do, as on the page: read
  `memories` again only then (`life.memory.version` says it too).
- For `pulse`, ask next with the `now` the last answer gave as `since`. An
  event's `key` stays the same each time it is read, so overlap is harmless. A
  `since` that isn't a time is refused, never read as no `since`.
- **Pictures.** The page shows what the mind made from its studio. A host has
  no web server, so `life` comes with `pictures`: for each studio item the page
  shows as a picture, its `path` and the file to read. Only pictures, only from
  inside this mind's own studio once links are followed, never a hidden file,
  and none over 6 MB. Read the file yourself; it is never put inside a line.
  The `picture` field inside the document is the page's own address for it and
  means nothing to a host. The paths are real ones, links followed: if the studio
  folder (or one above it) is itself a link, they name where it really is, so
  compare real paths (`os.path.realpath`), not the path you expected.
- **Another mind's name.** Where the page says a memory was written "by a
  colleague", the name comes from that memory's own `model` (in `memories`), or
  a shared row's `author` and `model` (in `life.shared`). No other store is read.
  This process reads one mind only; there is no `minds` part.
- **Sizes.** On a made-up store of 3,000 memories: `life` 8.7 KB, `memories`
  5.3 MB (about 1.76 KB a memory), `pulse` 16 KB. Each answers in 0.12 s or less
  once the process is warm, and in about 0.3 s as the first request.

### The memories, a page at a time

A large memory makes a long line. `memories` takes an optional `limit` (1 or
more) and `offset` (0 or more) to send it in pages:

```json
{"id": 5, "command": "notebook", "part": "memories", "limit": 500, "offset": 0}
{"id": 5, "result": {"part": "memories",
  "document": {"version": "b5499bd1028d", "made": "...", "memories": [... 500 ...], "recalled": [...]},
  "page": {"offset": 0, "limit": 500, "total": 3000, "next": 500}}}
```

- With neither `limit` nor `offset`, the answer is the whole document, exactly
  as before, with no `page`.
- A page holds the memories from `offset` on, at most `limit` of them (with no
  `limit`, all the rest), in the whole document's own order. `total` is how many
  memories the whole holds, and `next` is the offset to ask for next, or null
  after the last page.
- `version` is the whole's, on every page. `recalled` (each time a memory came
  back) comes whole on the page at offset 0 and empty on every other page.
- To rebuild the whole: ask from offset 0, follow `next` until it is null, join
  the pages' `memories` in order, and take `recalled` from the first page. If
  any page's `version` differs from the first one's, the memories changed while
  you read: start again from offset 0.
- An `offset` past the last memory, or a `limit` or `offset` that isn't a
  whole number in range, is refused in one sentence.
- Each page is cut from a whole export, so paging keeps a line short; it does
  not make the read cheaper. On 3,000 memories, pages of 500 were at most 1.5 MB
  and took 0.2 to 0.4 s each on a busy machine.

## What each part counts: `summary`

Cheap to ask every few seconds, to know whether to read again.

```json
{"id": 5, "command": "summary"}
{"id": 5, "result": {
  "missing": false,
  "counts": {"memories": 2, "states": {"active": 2, "dormant": 0, "archived": 0},
             "shared": 1, "beliefs": 0, "questions": 2, "answered": 0, "journal": 0,
             "notes": 1, "replies": 0, "hours": 0, "made": 1, "carrying": 0},
  "unread": 0, "waiting": 1, "change_token": "573b8bb7b7ca4602db18"}}
```

- The counts are read from the same documents `notebook` gives, so a host's
  counts and the page's agree: `memories` and `states` (the memory), `shared`
  (rows in the shared notebook), `beliefs`, `questions` (open) and `answered`,
  `journal`, `notes` (the agent's notes for the person) and `replies` (the
  person's), `hours` (quiet hours held on record), `made` (files in the studio),
  `carrying` (the notes it left itself).
- `unread`: the agent's notes the person hasn't read. `waiting`: the agent's
  questions still waiting on the person (in each thread, the newest note, when
  it is the agent's and ends with a question mark), as the page counts them.
- `change_token` is the same while nothing the notebook shows has changed, and
  different once anything has (a memory kept, a note read, a picture made, a
  schedule changed). It is not a count and has no order: compare it for
  equality only. The store's size is shown, so SQLite tidying its file can
  change the token once with nothing else changed.
- On 3,000 memories a summary takes about 0.13 s, warm.
- `missing` is true while there is no store yet.

## Reading the memory, journal and notes

The person's commands from before, unchanged: each answers with what its one-shot
`--json` command prints.

| command | request | one-shot beside it |
|---|---|---|
| `memories` | `state` ("active" or "dormant"), `limit`, `offset` | `mnemos memories --json` |
| `search` | `query`, `max_results` | `mnemos search --json` |
| `journal` | `last` | `mnemos journal --json` |
| `notes` | `unread` (true or false) | `mnemos notes --json` |

## What the person can do

Every act the notebook's page allows, but Jev's setting. Each runs through the
page's own code, with its limits and its sentences.

| command | request | result |
|---|---|---|
| `correct` | `memory_id`, `text` | `{"id": <new>, "replaces": <old>, "corrected": <time>}` |
| `forget` | `memory_id` | `{"id", "state": "archived", "forgotten": <time>}` |
| `reply` | `note_id`, `text` | the stored reply, as a `notes` item |
| `note` | `text` | the stored note, as a `notes` item |
| `read` | `note_ids`: a list of the agent's notes, 1 to 200 | the ids this marked read (one already read keeps its time) |
| `hours` | `hours`: the hours to change, any of `mine`, `ours` and `dream`, each with only what changes: `on` (true or false), `at` (`HH:MM`), `minutes` (5 to 120), `online` (true or false; never for `dream`) | what changed, in words |
| `shared` | `action`: "add" (`text`), "correct" (`memory_id`, `text`) or "forget" (`memory_id`, `confirmed: true`) | what the shared notebook said |

```json
{"id": 6, "command": "read", "note_ids": ["a3de9e13-18a5-4bce-a87d-79ecce639b5a"]}
{"id": 6, "result": ["a3de9e13-18a5-4bce-a87d-79ecce639b5a"]}

{"id": 7, "command": "hours", "hours": {"ours": {"on": true}, "dream": {"on": true, "at": "04:15", "minutes": 10}}}
{"id": 7, "result": "Our hour: on, daily at 19:00, up to 30 minutes, offline. The dream: on, daily at 04:15, up to 10 minutes, never online."}

{"id": 8, "command": "shared", "action": "add", "text": "Every agent: the kettle is new."}
{"id": 8, "result": "Saved to shared memory. Every agent on this machine can read it.\nShared memory ID: shared_engram_..."}
```

- A reply or a note is the person's own words, kept exactly as given, at most
  16,384 characters, and refused during one of the agent's quiet hours.
- `hours` changes each hour it names by itself, as `mnemos hours on|off ...
  --write` does for this scope: turning one on writes and loads a real job in
  the system's scheduler (launchd on a Mac), turning one off removes only its
  job, and the other hours are left exactly as they are. An hour that's off
  takes `on` first: changing its time alone is refused. It keeps that the
  person answered about their hours. `life.quietHours` says each hour as it
  is now (`on`, `at`, `minutes`, `online`), and `cant` why none can be turned
  on here, when none can.
- The older request, `on` (true or false) with `mine`, `ours` and `dream`
  (each `HH:MM`, or empty for its own time), still does what `mnemos daemon
  install --hours --write` (or `uninstall --hours --write`) does: all three
  at once.
- Inside Hermes the hours are Hermes's own scheduled jobs: `hours` is refused,
  and `life.quietHours` is `{"where": "hermes", "hours": ...}`, each hour as
  Hermes has it (`at`, `on`, `online`, `limited`, `made_by`, or null for one
  with no job), or `"hours": null` when its jobs can't be read.
- Letting a shared memory go is asked twice: without `"confirmed": true` it is
  refused. The shared notebook is the machine's, one for every agent, and its
  writes here are always the person's. It is always the one under `HOME`
  (`~/.mnemos/shared-memory.db`, or `MNEMOS_SHARED_MEMORY_DB`), whatever
  `--db-path` says, `--strict-scope` or not.
- **Jev is not here.** Its setting takes a key, and nothing in `mnemos
  interface` takes, says or logs a key. Jev is set on the notebook's own page.
  `life.jev` says whether it is on and whether a key is saved, never the key.

## The two flags

- `--as-person`: every write is the person's (a correction's words unsigned and
  marked as theirs, a forget archived as theirs), whatever the shell it runs in
  says. Without it, a correction or a forget from a process started inside an
  agent's shell (one with `CLAUDECODE` or `AI_AGENT` set) is the agent's. (A
  reply, a note, a note read and the shared notebook are always the person's.) A
  host the person uses should pass it: an app started from a terminal Claude Code
  opened would otherwise correct as the agent.
- `--strict-scope`: the scope comes from the four flags and nowhere else. All
  four of `--db-path`, `--agent-id`, `--person-id` and `--project-scope` must be
  given; the environment (`MNEMOS_DB_PATH`, `MNEMOS_AGENT_ID`, ...) and
  `~/.mnemos/config.json` are never asked. With any missing, the process reads
  nothing, writes one sentence to stderr naming what's missing, and ends at once
  with status 2. Each value is used exactly as given: one Mnemos would read as
  something else (it keeps a scope in lower-case letters, digits, `-` and `_`, so
  `--agent-id "!!!"` would be read as `mnemos-agent`, and `Nova` as `nova`) ends
  it the same way, naming the flag. A host should pass it, so it never reads a
  memory it didn't name. The person's name on the page (`life.identity.person`)
  still comes from `MNEMOS_PERSON_NAME`: it only names them, and never chooses a
  store.

Without the flags, everything is as it was.

## What never changes

- The person's eight commands keep their requests and their results.
- Reading writes nothing. No read, search included, wakes, strengthens, links,
  marks read, schedules or writes anything, and none makes a store. A person
  looking through the memory is not the agent remembering. (A store already in
  use may have its `-wal` and `-shm` files beside it; those are SQLite's.)
- Nothing is ever deleted: a forget archives.
- One process, one memory. It never lists or reads another mind's store.

## What a host must do itself

- **Choose the store, and say whose it is.** Pass all four scope flags with
  `--strict-scope`, and show the person which mind they are looking at
  (`hello`'s `scope`, `life.identity`).
- **Ask before it acts.** Every write here is the person's: a host sends one
  only when the person asked for it, in its own interface. Turning the quiet
  hours on installs a job on their machine; letting a memory go is asked twice.
- **Read pictures from the paths given**, and only those.
- **Keep the process for as long as it shows the notebook**, and close stdin to
  end it. The meaning model loads once, in the background, as it starts; a
  search waits for it, nothing else does.
