"""A read-only view of one resident's memory, for an app that hosts it.

A host app (Polyphonic is the first) shows one agent's memory in a tab of its
own. Opening or refreshing that tab must never wake, recall, mark read or
write anything, and must never show anyone else's memory. This module is the
whole of that view: one engine function, ``read_view``, which a host can
import, and ``mnemos view``, the command that prints its reply as one JSON
document and exits.

What it promises, each checked by ``tests/test_host_read_view.py``:

- **Read only.** Every section is read through the exporter's one read-only
  opening (``companion.export.open_read_only``): a connection that cannot
  write, which leaves no -wal or -shm beside a store nobody has open. The
  store must already exist; the view never creates a file, never migrates
  and never stamps. Nothing here marks a note read, wakes, strengthens or
  links a memory, or writes a trace row.
- **The whole scope, pinned.** The store path, the agent, the person and the
  project are all required, and only the caller's own words count: the
  environment and ``~/.mnemos/config.json`` are never read for them. Every
  table read is kept to that one agent, person and project, beliefs
  included; no other mind's rows, ids, names or counts appear in a reply.
- **A checked version.** The caller names the protocol it speaks
  (``VIEW_PROTOCOL_VERSION``); any other version is refused before the store
  is opened. Every reply says its protocol, the Mnemos version, the store's
  schema version and the scope it answered for.
- **Bounded.** A list section gives at most ``MOST_ITEMS`` items a reply
  (``DEFAULT_ITEMS`` unless asked), each long text cut at ``MOST_TEXT_CHARS``,
  and a reply is never more than ``MOST_REPLY_BYTES`` as printed. When there
  is more, it says ``truncated: true`` and gives a ``next_cursor``.

Edits never happen here. A host that changes memory does it through the host
mutation protocol (``docs/host-mutation-protocol.md``).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import marshal
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .companion.export import _Reading, open_read_only
from .simple_scope import MnemosScope, _slugify

#: The version of the view's request and reply. A caller names the version
#: it speaks; any other is refused before the store is opened.
VIEW_PROTOCOL_VERSION = 1
SUPPORTED_VIEW_PROTOCOLS = (VIEW_PROTOCOL_VERSION,)

#: What ``--section`` chooses from: ``summary``, then the list sections.
SECTIONS = ("summary", "memories", "standing", "journal", "notes", "handoffs", "beliefs")
LIST_SECTIONS = SECTIONS[1:]

#: Items a list reply gives when not asked, and the most it ever gives.
DEFAULT_ITEMS = 50
MOST_ITEMS = 200
#: The most a reply is, in bytes of UTF-8, exactly as ``render`` prints it.
MOST_REPLY_BYTES = 256 * 1024
#: A text longer than this (a memory's words or impact, an entry's text) is
#: cut here, and its item says ``clipped: true``. At this length even the
#: longest item fits a reply on its own.
MOST_TEXT_CHARS = 16_384
#: A belief names at most this many of its supporting memories.
MOST_SUPPORTS = 50
#: The states the memories and standing sections show: the ones
#: ``_Reading.memory_rows`` reads unless it is asked for another.
_SHOWN_STATES = ("active", "dormant")

_SCOPE_FLAGS = (
    ("db_path", "--db-path"),
    ("agent_id", "--agent-id"),
    ("person_id", "--person-id"),
    ("project_scope", "--project-scope"),
)


class ViewRefused(ValueError):
    """A request the view won't answer: a ``code`` a host can act on and one
    plain sentence. ``details`` are added to the error reply as they are."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# ── The request ──


def _protocol(value: Any) -> int:
    if isinstance(value, bool):
        value = None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if value is None or not isinstance(value, int):
        raise ViewRefused(
            "protocol_required",
            f"Say which protocol you speak: --protocol {VIEW_PROTOCOL_VERSION}.",
        )
    if value not in SUPPORTED_VIEW_PROTOCOLS:
        raise ViewRefused(
            "unsupported_protocol",
            f"This Mnemos speaks view protocol {', '.join(map(str, SUPPORTED_VIEW_PROTOCOLS))}, "
            f"not {value}.",
        )
    return value


def _pinned_scope(given: Mapping[str, Any]) -> MnemosScope:
    """The scope exactly as the caller named it, or a refusal. Nothing is
    filled in: not from the environment, not from the config file, not from
    Mnemos's defaults. An id must be given as Mnemos stores it (the form
    ``resolve_scope`` writes), so the view can't quietly read a different
    scope than the one asked for."""
    missing = [flag for key, flag in _SCOPE_FLAGS if not str(given.get(key) or "").strip()]
    if missing:
        raise ViewRefused(
            "scope_required",
            "The view reads only the scope you name in full: give "
            + ", ".join(missing) + ".",
            missing=missing,
        )
    ids: dict[str, str] = {}
    for key, flag in _SCOPE_FLAGS[1:]:
        value = str(given[key])
        stored = _slugify(value, "")
        if value != stored:
            raise ViewRefused(
                "scope_not_canonical",
                f"{flag} must be the id as Mnemos stores it"
                + (f" ({stored!r})." if stored else "."),
                flag=flag,
            )
        ids[key] = value
    return MnemosScope(db_path=str(given["db_path"]), **ids)


def _limit(value: Any, section: str) -> int:
    if value is None:
        return DEFAULT_ITEMS
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MOST_ITEMS:
        raise ViewRefused(
            "bad_limit", f"--limit is a whole number from 1 to {MOST_ITEMS}.", most=MOST_ITEMS,
        )
    return value


def _encode_cursor(section: str, after: Any) -> str:
    raw = json.dumps({"s": section, "a": after}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: Any, section: str) -> Any:
    """Where the last reply stopped, from the cursor it gave. A cursor is
    only good for the section that gave it."""
    if cursor is None:
        return None
    bad = ViewRefused("bad_cursor", "That cursor isn't one this section gave.")
    if not isinstance(cursor, str) or not cursor or len(cursor) > 1024:
        raise bad
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, binascii.Error):
        raise bad from None
    if not isinstance(data, dict) or data.get("s") != section:
        raise bad
    after = data.get("a")
    if section in ("journal", "notes"):
        if not (isinstance(after, list) and len(after) == 2 and all(isinstance(x, str) for x in after)):
            raise bad
    elif isinstance(after, bool) or not isinstance(after, int) or after < 0:
        raise bad
    return after


# ── The items ──


def _clip(item: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        text = item.get(key)
        if isinstance(text, str) and len(text) > MOST_TEXT_CHARS:
            item[key] = text[:MOST_TEXT_CHARS]
            item["clipped"] = True
    return item


def _memory_items(reading: _Reading, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Memories in the shape ``mnemos memories --json`` gives them
    (``interface.person.memory_view``), with whether each is standing."""
    from .interface.person import first_kept, memory_view

    kept = first_kept(reading, {row["id"]: (row["created_at"], row["lineage"]) for row in rows})
    return [
        _clip({**memory_view(row, kept[row["id"]]), "standing": bool(row["standing"])}, "words", "impact")
        for row in rows
    ]


def _journal_item(entry: Mapping[str, Any]) -> dict[str, Any]:
    """A journal entry in the shape ``mnemos journal --json`` gives it."""
    from .simple_runtime import journal_entry_view

    return _clip(journal_entry_view({
        "id": entry["id"], "text": entry["text"], "mood": entry["mood"], "written": entry["written"],
        "model_id": entry["model"], "created_at": entry["at"],
    }), "text")


def _note_item(note: Mapping[str, Any]) -> dict[str, Any]:
    """A note in the shape ``mnemos notes --json`` gives it. ``read_at`` is
    as it is: the view never marks a note read."""
    from .simple_runtime import note_view

    return _clip(note_view({
        "id": note["id"], "kind": note["kind"], "text": note["text"], "author": note["author"],
        "model_id": note["model"], "in_reply_to": note["replyTo"], "created_at": note["at"],
        "read_at": note["read"], "delivered_at": note["delivered"],
    }), "text")


def _handoff_item(handoff: Mapping[str, Any]) -> dict[str, Any]:
    return _clip({"text": handoff["text"], "created_at": handoff["at"], "model": handoff["model"] or None}, "text")


#: What a belief row is read with: everything the beliefs section shows of it.
_BELIEF_COLUMNS = ("id", "content", "confidence", "domain", "created_at", "last_revised",
                   "revision_history", "supporting_engram_ids")


def _scoped_belief_rows(reading: _Reading) -> list[tuple[sqlite3.Row, list[str]]]:
    """This scope's beliefs, oldest first, each with the memories it rests
    on. A belief is kept by agent alone (the table has no person or project),
    so a belief belongs to this scope only through what it rests on: it is
    shown when every memory supporting it is this agent's, about this person,
    in this project. One that also rests on a memory from elsewhere is not
    shown, because its words may carry what was said there; nor is one that
    rests on no memory at all. The one reading of them, for the section and
    for the summary's count and token."""
    if not reading.has("beliefs"):
        return []
    rows = reading.c.execute(
        f"SELECT {', '.join(_BELIEF_COLUMNS)} FROM beliefs WHERE agent_id=? AND superseded_by IS NULL "
        "ORDER BY created_at, id", (reading.scope.agent_id,)).fetchall()
    supports: dict[str, list[str]] = {}
    for row in rows:
        try:
            named = json.loads(row["supporting_engram_ids"] or "[]")
        except ValueError:
            named = []
        supports[row["id"]] = [s for s in named if isinstance(s, str)] if isinstance(named, list) else []
    here = _here(reading, {s for named in supports.values() for s in named})
    out = []
    for row in rows:
        own = [s for s in supports[row["id"]] if s in here]
        if own and len(own) == len(supports[row["id"]]):
            out.append((row, own))
    return out


def _here(reading: _Reading, ids: set[str]) -> set[str]:
    """Which of ``ids`` are memories of this scope, in any state. Each is
    looked up by its id, and kept only if the scope's clause holds for it.
    (Asked with the clause and an id list together, SQLite reads the whole
    scope through its index instead, once for every 400 ids.)"""
    clause, scope = reading.scoped("engrams", owner="owner_agent_id")
    wanted, found = sorted(ids), set()
    for start in range(0, len(wanted), 400):
        chunk = wanted[start:start + 400]
        values = ", ".join("(?)" for _ in chunk)
        found.update(row[0] for row in reading.c.execute(
            f"WITH wanted(wanted_id) AS (VALUES {values}) SELECT engrams.id FROM wanted "
            f"CROSS JOIN engrams ON engrams.id = wanted_id WHERE {clause}", (*chunk, *scope)))
    return found


def _belief_item(row: sqlite3.Row, own: list[str]) -> dict[str, Any]:
    try:
        history = json.loads(row["revision_history"] or "[]")
    except ValueError:
        history = []
    return _clip({
        "id": row["id"], "text": row["content"], "confidence": row["confidence"],
        "domain": row["domain"], "created_at": row["created_at"], "revised_at": row["last_revised"],
        "revisions": len(history) if isinstance(history, list) else 0,
        "supports": own[:MOST_SUPPORTS], "supports_total": len(own),
    }, "text")


def _scoped_beliefs(reading: _Reading) -> list[dict[str, Any]]:
    """The beliefs section's items: ``_scoped_belief_rows``, as shown."""
    return [_belief_item(row, own) for row, own in _scoped_belief_rows(reading)]


# ── What the memories and standing sections read ──


def _shown_memories(reading: _Reading) -> tuple[str, tuple[str, ...]]:
    """The memories the memories and standing sections show: this scope's,
    active or dormant, as ``_Reading.memory_rows`` keeps to them. The one
    clause the standing page, the standing count and the token all read
    through."""
    clause, scope = reading.scoped("engrams", owner="owner_agent_id")
    marks = ", ".join("?" for _ in _SHOWN_STATES)
    return f"{clause} AND state IN ({marks})", (*scope, *_SHOWN_STATES)


def _is_standing(reading: _Reading) -> str:
    """Whether a memory is standing, as SQL. A store from before memories
    could stand has none standing."""
    return "standing != 0" if "standing" in reading.columns("engrams") else "0"


def _memory_columns(reading: _Reading) -> str:
    """A memory's columns, exactly as ``_Reading.memory_rows`` reads them
    (with its stand-ins on an older store), so a standing item is built from
    the same row the memories section builds it from."""
    def col(name: str, default: str = "''") -> str:
        return reading.col("engrams", name, default)

    return ", ".join((
        "id", "content", col("impact"), "kind", "accessibility", "state", "created_at", "last_accessed",
        col("author_kind", "'unknown'"), col("author_model"), col("author_session"), col("lineage", "'{}'"),
        col("standing", "0"), col("strength", "0.5"), col("stability", "0.5"),
    ))


# ── The sections ──


def _newest_first(rows: list[dict[str, Any]], after: list[str] | None) -> list[dict[str, Any]]:
    """Rows newest first in a stable order (time, then id), from just past
    ``after`` (the ``[time, id]`` a cursor holds)."""
    rows = sorted(rows, key=lambda r: (r["at"], r["id"]), reverse=True)
    if after is not None:
        rows = [r for r in rows if (r["at"], r["id"]) < (after[0], after[1])]
    return rows


def _page_newest_first(fetch: Callable[[str, tuple], list[dict]], build: Callable[[dict], dict],
                       after: Any, limit: int) -> tuple[list[dict], list[Any], bool]:
    where, params = "", ()
    if after is not None:
        where, params = "AND created_at <= ?", (after[0],)
    rows = _newest_first(fetch(where, params), after)
    page = rows[:limit]
    return [build(r) for r in page], [[r["at"], r["id"]] for r in page], len(rows) > limit


def _in_order(reading: _Reading, start: int) -> Any:
    """Each memory the memories section shows, as ``(place, id, standing)``
    in that section's order (``created_at``, then ``id``), from just past
    place ``start``. One query of these three columns alone, put in order
    once. Python orders it, because it orders text as SQLite does (by code
    point, which is UTF-8's byte order) and faster than SQLite's own sort of
    a whole scope. A store holding mixed kinds of value in those columns
    can't be ordered that way, so SQLite orders it, by the same rule
    ``_Reading.memory_rows`` reads in."""
    where, params = _shown_memories(reading)
    cursor = reading.c.cursor()
    cursor.row_factory = None
    query = f"SELECT created_at, id, {_is_standing(reading)} FROM engrams WHERE {where}"
    rows = cursor.execute(query, params).fetchall()
    try:
        rows.sort()
    except TypeError:
        rows = cursor.execute(f"{query} ORDER BY created_at, id", params).fetchall()
    return ((place + 1, rows[place][1], rows[place][2]) for place in range(start, len(rows)))


def _page_memories(reading: _Reading, after: Any, limit: int,
                   standing_only: bool) -> tuple[list[dict], list[Any], bool]:
    """Memories oldest first, as ``mnemos memories`` orders them; a cursor
    is the position in that order to go on from."""
    start = after or 0
    if not standing_only:
        rows = reading.memory_rows(limit=limit + 1, offset=start)
        page = rows[:limit]
        return _memory_items(reading, page), [start + i + 1 for i in range(len(page))], len(rows) > limit
    found: list[tuple[int, str]] = []
    for place, memory_id, standing in _in_order(reading, start):
        if standing:
            found.append((place, memory_id))
            if len(found) > limit:
                break
    page = found[:limit]
    rows = {}
    if page:
        marks = ", ".join("?" for _ in page)
        rows = {row["id"]: row for row in reading.c.execute(
            f"SELECT {_memory_columns(reading)} FROM engrams WHERE id IN ({marks})",
            [memory_id for _, memory_id in page])}
    page = [(place, memory_id) for place, memory_id in page if memory_id in rows]
    return (_memory_items(reading, [rows[memory_id] for _, memory_id in page]), [place for place, _ in page],
            len(found) > limit)


def _page_list(items: list[dict], after: Any, limit: int) -> tuple[list[dict], list[Any], bool]:
    start = after or 0
    page = items[start:start + limit]
    return page, [start + i + 1 for i in range(len(page))], len(items) > start + limit


def _page(reading: _Reading, section: str, after: Any, limit: int) -> tuple[list[dict], list[Any], bool]:
    """One page of a list section: its items, where each leaves off (for the
    cursor), and whether there is more."""
    if section in ("memories", "standing"):
        return _page_memories(reading, after, limit, standing_only=section == "standing")
    if section == "journal":
        return _page_newest_first(reading.journal_rows, _journal_item, after, limit)
    if section == "notes":
        return _page_newest_first(reading.note_rows, _note_item, after, limit)
    if section == "handoffs":
        return _page_list([_handoff_item(h) for h in reading.handoffs()], after, limit)
    return _page_list(_scoped_beliefs(reading), after, limit)


#: The stored values the token is made from, table by table: every column a
#: section shows something of. A memory the sections don't show (archived)
#: still counts through what an item's ``kept`` follows back to.
_TOKEN_COLUMNS = {
    "memories": ("id", "content", "impact", "state", "created_at", "accessibility", "author_kind",
                 "author_session", "lineage", "standing"),
    "earlier": ("id", "state", "created_at", "lineage"),
    "journal_entries": ("id", "created_at", "text", "mood", "written", "model_id"),
    "notes": ("id", "created_at", "kind", "text", "author", "model_id", "in_reply_to", "read_at",
              "delivered_at"),
}


def _stored(reading: _Reading, table: str, columns: tuple[str, ...], where: str,
            params: tuple) -> list[tuple]:
    """The raw stored values of ``columns`` for the rows ``where`` names, as
    plain tuples in id order (sorted here: the database would sort the
    whole rows). A column an older store lacks is left out: it shows the
    same stand-in everywhere."""
    have = reading.columns(table)
    cursor = reading.c.cursor()
    cursor.row_factory = None
    rows = cursor.execute(
        f"SELECT {', '.join(name for name in columns if name in have)} FROM {table} WHERE {where}",
        params).fetchall()
    try:
        rows.sort(key=_first)
    except TypeError:  # ids of mixed kinds: still one fixed order
        rows.sort(key=lambda row: (type(row[0]).__name__, repr(row[0])))
    return rows


def _first(row: tuple) -> Any:
    return row[0]


def _count(reading: _Reading, table: str, where: str, params: tuple) -> int:
    return int(reading.c.execute(f"SELECT count(*) FROM {table} WHERE {where}", params).fetchone()[0])


def _summary(reading: _Reading) -> dict[str, Any]:
    """How much each section holds, counted by the database through the same
    scope the sections read, and a token that changes whenever what any
    section would show changes. The token is made from the stored values
    those sections draw on, read in a fixed order; no item is built for it."""
    digest = hashlib.sha256()

    def feed(name: str, values: Any) -> None:
        # marshal's first format: exact, the same bytes for the same values
        digest.update(marshal.dumps((name, values), 0))

    shown, shown_params = _shown_memories(reading)
    scope, scope_params = reading.scoped("engrams", owner="owner_agent_id")
    feed("memories", _stored(reading, "engrams", _TOKEN_COLUMNS["memories"], shown, shown_params))
    marks = ", ".join("?" for _ in _SHOWN_STATES)
    feed("earlier", _stored(reading, "engrams", _TOKEN_COLUMNS["earlier"],
                            f"{scope} AND (state IS NULL OR state NOT IN ({marks}))",
                            (*scope_params, *_SHOWN_STATES)))
    states = reading.state_counts()
    feed("states", sorted(states.items(), key=repr))
    standing = _count(reading, "engrams", f"{shown} AND {_is_standing(reading)}", shown_params)

    journal = notes = unread = 0
    for table in ("journal_entries", "notes"):
        if not reading.has(table):
            continue
        where, params = reading.scoped(table)
        feed(table, _stored(reading, table, _TOKEN_COLUMNS[table], where, params))
        if table == "journal_entries":
            journal = _count(reading, table, where, params)
        else:
            notes, unread = reading.c.execute(
                "SELECT count(*), coalesce(sum(author = 'agent' AND (read_at IS NULL OR read_at = '')), 0) "
                f"FROM notes WHERE {where}", params).fetchone()

    handoffs = reading.handoffs()
    feed("handoffs", [(h["text"], h["at"], h["model"]) for h in handoffs])
    beliefs = _scoped_belief_rows(reading)
    feed("beliefs", [(tuple(row), own) for row, own in beliefs])
    return {
        "counts": {
            "memories": {name: int(states.get(name, 0)) for name in ("active", "dormant", "archived")},
            "standing": standing,
            "journal": journal,
            "notes": {"all": int(notes), "unread": int(unread)},
            "handoffs": len(handoffs),
            "beliefs": len(beliefs),
        },
        "change_token": digest.hexdigest()[:32],
    }


# ── The reply ──


def render(reply: Mapping[str, Any]) -> str:
    """A reply as ``mnemos view`` prints it, and as its size is measured."""
    return json.dumps(reply, ensure_ascii=False, separators=(",", ":"))


def _size(reply: Mapping[str, Any]) -> int:
    return len(render(reply).encode("utf-8"))


def _envelope(scope: MnemosScope, section: str, schema: int | None) -> dict[str, Any]:
    from .package_version import mnemos_version

    return {
        "protocol_version": VIEW_PROTOCOL_VERSION,
        "mnemos_version": mnemos_version(),
        "schema_version": schema,
        "scope": {"agent_id": scope.agent_id, "person_id": scope.person_id,
                  "project_scope": scope.project_scope},
        "section": section,
    }


def _schema_version(reading: _Reading) -> int | None:
    if not reading.has("meta"):
        return None
    row = reading.c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    try:
        return int(row[0]) if row else None
    except (TypeError, ValueError):
        return None


def read_view(
    *,
    protocol: Any,
    db_path: str | None,
    agent_id: str | None,
    person_id: str | None,
    project_scope: str | None,
    section: str | None,
    limit: Any = None,
    cursor: Any = None,
) -> dict[str, Any]:
    """One section of one resident's memory, read and never written.

    Raises ``ViewRefused`` for a request it won't answer: an unsupported
    protocol (checked first, before anything is opened), a scope not given in
    full, an unknown section, a limit or cursor it can't use, or a store that
    isn't there or isn't a Mnemos store."""
    _protocol(protocol)
    scope = _pinned_scope({"db_path": db_path, "agent_id": agent_id, "person_id": person_id,
                           "project_scope": project_scope})
    if section not in SECTIONS:
        raise ViewRefused("unknown_section", f"--section is one of: {', '.join(SECTIONS)}.",
                          sections=list(SECTIONS))
    if section == "summary":
        if limit is not None or cursor is not None:
            raise ViewRefused("bad_limit", "The summary takes no --limit or --cursor.")
        count, after = 0, None
    else:
        count = _limit(limit, section)
        after = _decode_cursor(cursor, section)
    db = Path(scope.db_path).expanduser()
    if not db.is_file():
        raise ViewRefused("no_store", "There is no Mnemos store at that path. The view never makes one.")
    try:
        conn = open_read_only(db)
    except sqlite3.Error:
        raise ViewRefused("unreadable_store", "That store couldn't be opened for reading.") from None
    try:
        reading = _Reading(conn, scope)
        try:
            if not reading.has("engrams"):
                raise ViewRefused("not_a_store", "That file isn't a Mnemos store.")
            reply = _envelope(scope, section, _schema_version(reading))
            if section == "summary":
                reply.update(_summary(reading))
                return reply
            items, ends, more = _page(reading, section, after, count)
        except sqlite3.DatabaseError:
            raise ViewRefused("unreadable_store", "That store couldn't be read.") from None
    finally:
        conn.close()
    reply.update({"limit": count, "items": [], "truncated": False, "next_cursor": None})
    # Room for the end of the reply: the flag and the longest cursor this
    # section can give, so adding them never takes it past the ceiling.
    room = MOST_REPLY_BYTES - _size(reply) - len(',"truncated":true,"next_cursor":""') - 1100
    used, kept = 0, 0
    for item in items:
        cost = len(render(item).encode("utf-8")) + 1
        if used + cost > room:
            break
        used += cost
        kept += 1
    reply["items"] = items[:kept]
    if kept < len(items) or more:
        reply["truncated"] = True
        reply["next_cursor"] = _encode_cursor(section, ends[kept - 1] if kept else after)
    while _size(reply) > MOST_REPLY_BYTES and reply["items"]:  # never reached at these limits; the ceiling holds anyway
        reply["items"].pop()
        reply["truncated"] = True
        kept = len(reply["items"])
        reply["next_cursor"] = _encode_cursor(section, ends[kept - 1] if kept else after)
    return reply


def error_reply(refused: ViewRefused) -> dict[str, Any]:
    """A refusal as ``mnemos view`` prints it."""
    return {
        "protocol_version": VIEW_PROTOCOL_VERSION,
        "supported_protocols": list(SUPPORTED_VIEW_PROTOCOLS),
        "error": {"code": refused.code, "message": refused.message, **refused.details},
    }


def answer(**request: Any) -> tuple[int, str]:
    """``mnemos view``: the exit status and the one JSON document to print.
    0 with the reply; 2 with a refusal."""
    try:
        return 0, render(read_view(**request))
    except ViewRefused as refused:
        return 2, render(error_reply(refused))
