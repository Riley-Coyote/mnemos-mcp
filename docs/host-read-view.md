# Host Read View

An app that hosts an agent (Polyphonic is the first) can show that agent's
memory in a tab of its own. Opening or refreshing that tab must never change
the memory: nothing woken or strengthened, no note marked read, no trace
written, no file left beside the store. It must also never show anyone else's
memory. `mnemos view` is that view, and nothing more. It reads one section of
one resident's memory, prints one JSON document, and exits.

It is read only. A host that changes memory does it through the
[host mutation protocol](host-mutation-protocol.md), never through the view.

Every statement below is checked by `tests/test_host_read_view.py` or by the
example, `examples/host_read_view/run.py`.

## The command

```bash
mnemos view --protocol 1 --section memories \
  --db-path /profile/mnemos/mnemos.db \
  --agent-id wren --person-id pat-example --project-scope lighthouse \
  [--limit 50] [--cursor CURSOR]
```

It prints one JSON document on stdout. The exit status is 0 with a reply and
2 with a refusal. A refusal is JSON too, with one exception: a flag the
command doesn't know at all is refused by the command line itself, with a
plain usage message on stderr and nothing on stdout.

A host written in Python can call the same engine without a process:

```python
from mnemos.host_view import read_view, ViewRefused

reply = read_view(
    protocol=1, section="summary",
    db_path="/profile/mnemos/mnemos.db",
    agent_id="wren", person_id="pat-example", project_scope="lighthouse",
)
```

`read_view` returns the reply as a dict and raises `ViewRefused` (with a
`code` and a `message`) where the command would print a refusal.
`mnemos.host_view.render(reply)` gives the exact text the command prints.

## The scope is yours to name, in full

All four are required: `--db-path`, `--agent-id`, `--person-id` and
`--project-scope`. The view answers for those and for nothing else.

- The environment (`MNEMOS_AGENT_ID`, `MNEMOS_DB_PATH` and the rest) and
  `~/.mnemos/config.json` are never read for this command. Pointing them at a
  different agent changes nothing, and leaving a flag out is a refusal
  (`scope_required`, naming the missing flags). It is never filled in from
  them.
- An id must be given as Mnemos stores it (lower case, letters, digits, `-`
  and `_`). `--agent-id Wren` is refused (`scope_not_canonical`), not quietly
  read as `wren`.
- The store must already exist. The view never creates a file, never
  migrates a store, and never stamps it. A missing path is `no_store`, and
  the folder is left as it was. An empty file is `not_a_store`, and a file
  that isn't a database is `unreadable_store`. A store an older Mnemos wrote is
  read as it is, and its `schema_version` is reported unchanged.

## The version rule

`VIEW_PROTOCOL_VERSION = 1`. It is exported from `mnemos` next to
`HOST_MUTATION_PROTOCOL_VERSION`. The caller must pass `--protocol 1`.
Anything else is refused before the store is opened, and before any other
part of the request is looked at:

```json
{"protocol_version": 1, "supported_protocols": [1],
 "error": {"code": "unsupported_protocol", "message": "This Mnemos speaks view protocol 1, not 2."}}
```

With no `--protocol`, or one that isn't a number, the code is
`protocol_required`.

## Every reply

```json
{
  "protocol_version": 1,
  "mnemos_version": "0.6.7",
  "schema_version": 19,
  "scope": {"agent_id": "wren", "person_id": "pat-example", "project_scope": "lighthouse"},
  "section": "memories",
  "limit": 50,
  "items": [ ... ],
  "truncated": false,
  "next_cursor": null
}
```

`mnemos_version` is the running Mnemos. `schema_version` is the store's own,
as it says it. The store's path appears nowhere in a reply.

## The sections

`--section` is one of these:

| Section | What it lists | Order |
| --- | --- | --- |
| `summary` | how much each section holds, and a `change_token` | (no items) |
| `memories` | the active and dormant memories | oldest first |
| `standing` | the memories marked standing | oldest first |
| `journal` | the agent's journal | newest first |
| `notes` | notes both ways: the agent's to the person, and the person's own and replies | newest first |
| `handoffs` | the agent's current handoffs, at most 40 | newest first |
| `beliefs` | the beliefs this scope supports | oldest first |

**summary**

```json
"counts": {
  "memories": {"active": 3, "dormant": 0, "archived": 0},
  "standing": 1, "journal": 1, "notes": {"all": 2, "unread": 1},
  "handoffs": 1, "beliefs": 1
},
"change_token": "…32 hex characters…"
```

`unread` counts the agent's notes the person hasn't read. Each count is
counted by the database, through the same scope the section reads, so it is
how many items paging that section to its end gives.

The `change_token` stays the same until something a section would show
changes, and changes when it does. Another resident's writes don't move it,
nor do this agent's writes about another person or in another project. A
host can compare tokens and skip a refresh when they match. The token is made
from the stored values the sections show, not from the items as shown, so it
can also move when a value changes but looks the same on screen (a memory's
`alive` is shown to three places). A token is only comparable with tokens
from the same Mnemos version, which every reply names: after an update, the
first token can differ even though nothing changed.

**memories** and **standing** items have the shape `mnemos memories --json`
gives, plus `standing`:
`{"id", "words", "kept", "state", "alive", "conversation", "corrected", "impact", "author", "standing"}`.

**journal** items have the shape `mnemos journal --json` gives:
`{"id", "text", "mood", "written", "model", "created_at"}`.

**notes** items have the shape `mnemos notes --json` gives:
`{"id", "kind", "text", "author", "model", "in_reply_to", "created_at", "read_at"}`,
and a person's note adds `delivered_at`. `read_at` is shown as it is. The view
never sets it.

**handoffs** items: `{"text", "created_at", "model"}`.

**beliefs** items:
`{"id", "text", "confidence", "domain", "created_at", "revised_at", "revisions", "supports", "supports_total"}`.
Mnemos keeps a belief by agent alone (the table has no person or project).
So a belief belongs to this scope only through the memories it rests on. It
is listed when every memory supporting it is this agent's, about this
person, in this project. `supports` names those memories (at most 50), and
`supports_total` counts them. A belief that rests, even in part, on another
person's or project's memories is not listed, because its words may carry
what was said there. Nor is one that rests on no memory at all.

## Only this resident

Every table the view reads is kept to the agent, person and project you
named, beliefs included. One store file can hold several residents. The
others' words, ids, names and counts appear in no reply, not even in the
summary's counts. The example builds such a file through Mnemos's normal
write path, with two residents and a second person of the first one's. It
checks every reply for every text, id and name of theirs.

The view reads no other store and nothing else on the machine. That means no
neighbouring stores, no shared-memory notebook, no quiet hours and their
schedule, no studio files and no keys.

## Limits

- A list section gives `--limit` items, 50 when not asked. The limit runs
  from 1 to 200, and anything else is refused (`bad_limit`). The summary takes
  no `--limit` or `--cursor`.
- A text longer than 16,384 characters (a memory's words or impact, an
  entry's text) is cut there, and its item says `"clipped": true`.
- A reply is at most 256 KiB (262,144 bytes) of UTF-8, exactly as printed.
  When the next item would pass that, the reply stops before it. In the test,
  the largest reply measured was 204,361 bytes, a page of memories full of
  four-byte characters.
- When there is more, either past the limit or past the ceiling, the reply
  says `"truncated": true` and gives `next_cursor`. Pass it back as
  `--cursor` to go on. Paging to the end gives every item once, in order. A
  cursor only works for the section that gave it, and any other cursor is
  refused (`bad_cursor`).

## How fast

`summary` counts each section with the database and makes its token from the
stored values those sections show, read in one fixed order. It reads every
memory of the scope to do that, so its time still grows with the memory, but
it builds no item and writes no JSON for it. The list sections read one page.
`standing` puts the scope's memories in order once, reading only each one's
time, id and mark, and then reads its page's memories by id.

Measured with `uv run python examples/host_read_view/measure.py`, on an
Apple M4 Max running macOS 27.0.1, with Python 3.12.11 and SQLite 3.50.4. The
script builds one store holding two residents of the same size, with made-up
words. The first is the one read, and it holds its memories, one standing
memory in fifty, a journal entry and a note for every twenty memories, a
reply for every forty, three handoffs, and a belief for every hundred. The
second is as large, so reading "only this resident" is paid for in full.

Each cell is in milliseconds: the median, then the worst in brackets, of 7
calls after one warm-up. The first number calls `read_view` in the host's own
Python process. The second runs `mnemos view` as a process of its own, which
pays for Python's start-up (79 ms median on its own, for a request refused
before any store is opened). A list section asks for its first page of 50.

| Section | 1,000 memories | 10,000 memories | 50,000 memories |
| --- | --- | --- | --- |
| summary | 4.7 (5.6) · 96.4 (128.2) | 38.4 (44.9) · 113.5 (118.0) | 198.9 (222.6) · 274.5 (278.5) |
| memories | 2.9 (3.0) · 89.2 (106.4) | 8.2 (8.9) · 84.4 (88.4) | 35.0 (35.7) · 111.7 (112.5) |
| standing | 2.3 (2.6) · 81.1 (95.8) | 12.5 (12.8) · 89.8 (96.0) | 51.5 (52.6) · 129.7 (130.7) |
| journal | 1.3 (1.6) · 82.2 (86.2) | 2.2 (2.8) · 78.3 (80.7) | 7.7 (8.0) · 85.8 (86.8) |
| notes | 1.2 (1.3) · 80.6 (85.0) | 3.1 (7.3) · 79.6 (81.6) | 12.1 (12.1) · 88.1 (90.8) |
| handoffs | 0.9 (1.3) · 79.9 (83.9) | 1.0 (1.0) · 77.6 (79.4) | 0.8 (0.9) · 75.4 (79.6) |
| beliefs | 1.0 (1.1) · 76.1 (81.0) | 2.1 (2.3) · 77.4 (81.1) | 5.5 (5.9) · 84.1 (84.9) |
| store file | 10.6 MB | 69.3 MB | 332.1 MB |

Before, when `summary` built every item and `standing` sorted the scope
again for every 500 memories it looked through, the same script on the same
machine and day measured `summary` at 12.5, 128.3 and 774.1 ms in-process
(at 1,000, 10,000 and 50,000 memories) and `standing` at 7.9, 58.8 and
221.7 ms.

With another process holding the 50,000-memory store open for writing, its
newest commit still only in the write-ahead log, `summary` took 199.5 ms
(202.0) in-process and 281.7 ms (349.7) through `mnemos view`, about the
same as with nobody writing.

A reply's size doesn't grow with the memory. `summary` was 367 to 377 bytes.
A first page was at most about 31 KB (the journal's).

The 1,000-memory store was written through Mnemos's normal write path. The
larger ones were built faster, by copying the rows that path wrote for the
first memory, entry, note and belief, with new ids, words and times. At
1,000 memories, a store built that way gave the same `summary` counts and the
same number of items in every section as the one written through the normal
path, and its in-process timings were within 1 ms of it. The copies leave
out the links Mnemos draws between similar memories, which the view never
reads. So those files are smaller than a real store of that size would be.

**How often to ask.** Up to 10,000 memories, asking for `summary` when the
tab opens and then every few seconds while it is in view costs little: under
50 ms in-process. At 50,000, one `summary` takes about a fifth of a second
in-process and about a quarter to a third of a second through `mnemos view`,
so ask for it when the tab opens or comes back into view, and no more than
about every 10 seconds while it stays open.

## Reads, never writes, never wakes

| Section | Reads | Never writes | Never wakes |
| --- | --- | --- | --- |
| summary | every section below, to count them and make the token | ✓ | ✓ |
| memories | `engrams`, kept to the scope | ✓ | ✓ |
| standing | `engrams`, kept to the scope | ✓ | ✓ |
| journal | `journal_entries`, kept to the scope | ✓ | ✓ |
| notes | `notes`, kept to the scope (`read_at` is never set) | ✓ | ✓ |
| handoffs | `hypomnema_entries` (current handoffs), kept to the scope | ✓ | ✓ |
| beliefs | `beliefs` for the agent, then `engrams` of the scope they rest on | ✓ | ✓ |

The tests check these things:

- **One way in.** Every section opens the store the one way the exporter
  does (`open_read_only` in `mnemos/companion/export.py`). That is one
  read-only SQLite connection a call. With SQLite's own authorizer on that
  connection, no write is even attempted. The view makes no runtime, no
  writable store and no interface. It is not one of the person interface's
  commands, which include writes.
- **An idle store.** If nobody has the store open, there's no `-wal` beside
  it. After a view of every section, the store's bytes are identical, and so
  is its folder's listing: no `-wal`, `-shm` or journal appears.
  One case is outside this promise: a `-wal` left behind by a writer that
  was killed, with no `-shm` beside it. Reading such a store makes SQLite
  create a `-shm` again; the main file and the `-wal` keep their bytes. (An
  independent check saw this by killing a writer and deleting its `-shm`; no
  test in the suite covers it.)
- **A live writer.** Suppose another process holds the store open in WAL
  mode, and its last commit is still only in the `-wal`. The view reads that
  newest commit. The main file's bytes are unchanged, the `-wal`'s bytes are
  unchanged, and nothing fails. **What SQLite does to `-shm`:** a reader
  records the newest frame it read in one of the WAL index's read-mark slots
  (bytes 100 to 119 of `-shm`). In the test, when the writer's last act was a
  commit, one slot moved from frame 28 to frame 30, at byte 104. Nothing else
  in `-shm` changed, and its size didn't change. `-shm` is SQLite's shared
  index for coordinating readers and writers, not the memory. When the writer
  had already read after its last commit, a matching mark was there and
  `-shm` didn't change at all.
- **Nothing remembered.** Across a view of every section, these stay
  unchanged: every memory's access count, last access, strength, stability,
  accessibility and state; every note's `read_at`; and the rows of
  `memory_trace`, `session_reinforcements` and `connections`. Nothing new
  appears anywhere under the home (no `~/.mnemos/run/shown-*` files, no
  config).

## What it leaves out, and why

- **Search.** The existing search path (`mnemos search`) is write-free at
  the SQL level, but it opens the store through a reader of its own, not the
  exporter's. Beside a store nobody has open, it leaves a `-wal` and a `-shm`
  file. That fails the folder-listing proof above, and it would be a second
  way of opening the store. So `search` is not a section. A test pins that
  behaviour down. If it starts failing, the search path no longer leaves
  those files, and search can be weighed again.
- **Questions, ties, recall history, quiet hours, the studio, the schedule,
  the cue's judge and the shared notebook.** The memory page reads these, and
  some of them live outside the store. A tab of one resident's memory doesn't
  need them, and each one would be more to keep to the scope.
- **The store's path and size.** Nothing here is about where the store is.

## How edits happen instead

The view has no way to change anything. A host that corrects, forgets,
captures or answers does it through the host mutation protocol
(`MnemosRuntime.execute_host_mutation`, `docs/host-mutation-protocol.md`),
which is versioned the same way and replay-safe. After an edit there, the
next `summary` gives a new `change_token`.
