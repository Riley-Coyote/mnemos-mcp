"""What a person's own app reads and does in their agent's memory.

The person's commands, each with ``--json`` in the shapes an app reads (Ghost's
home is the first): ``mnemos memories``, ``mnemos search``, ``mnemos correct``
and ``mnemos forget``, beside ``mnemos journal``, ``mnemos notes``, ``mnemos
notes reply`` and ``mnemos notes write``. And ``mnemos interface``: one long-lived process that answers the
same commands in the same shapes, one JSON request a line on stdin and one JSON
line an answer on stdout, so the meaning model loads once rather than once a
command (4.4 s on the maintainer's Mac, then about 14 ms a query). Beside
them, the whole notebook for a host: ``hello``, each part of the notebook's
page as the page is given it (``notebook``), what each part counts
(``summary``), and the rest of what the person can do on that page (``read``,
``hours``, ``shared``), each through the page's own code (docs/host-interface.md).

Reading writes nothing and never makes a store. A person looking through the
memory is not the agent remembering: nothing a search finds is woken,
strengthened or linked. A correction or a forget the person makes (outside an
agent's shell) is the person's: the new words unsigned and ``author_kind``
'person', a forget archived as ``forgotten_by_person``, and the agent wakes to
each once. A reply or a note of the person's own is the person's too, and the
agent wakes to each once. Nothing is deleted.

Times are ISO 8601 in UTC (``utc_iso``).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import threading
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from ..authorship import run_by_agent
from ..companion.export import Exporter, _Reading, open_read_only, person_name, pulse, studio_picture, when
from ..simple_runtime import (
    MnemosRuntime,
    NothingChanged,
    SEARCH_RESULTS,
    closeness,
    found_by,
    journal_view,
    note_view,
    notes_view,
    utc_iso,
)
from ..simple_scope import MnemosScope, resolve_scope
from ..store.embedding_index import EmbeddingIndex
from ..store.sqlite_store import ReadOnlyEngramStore
from .context_packet import lineage_supersedes

#: The states ``mnemos memories`` lists, and ``--state`` chooses from.
STATES = ("active", "dormant")
#: Who wrote a memory's words (its ``author_kind``), as the person's app is
#: told: the agent, the person, or a tool, which includes Mnemos's own
#: templates ("system") and what was brought in from elsewhere ("import").
#: Anything else (none, or a kind a newer Mnemos adds) is "unknown".
AUTHORS = {"agent": "agent", "person": "person", "tool": "tool", "system": "tool", "import": "tool"}
#: The version of what ``mnemos interface`` says, as ``hello`` tells a host. It goes up only when a request or a
#: result a host already reads changes; a new command, or a new key in a result, leaves it where it is.
PROTOCOL = 1
#: What ``mnemos interface`` answers: the person's commands, then what a host asks of the whole notebook (``hello``,
#: ``notebook``, ``summary``) and the rest of what the person can do on the notebook's own page (``read``, ``hours``,
#: ``shared``). Jev's setting is left to the page: it takes a key, and nothing here takes, says or keeps one.
COMMANDS = ("memories", "search", "correct", "forget", "journal", "notes", "reply", "note",
            "hello", "notebook", "summary", "read", "hours", "shared")
#: The parts of the notebook ``notebook`` gives: the page's own documents (``life.json``, ``memories.json``,
#: ``pulse.json``), for the one mind this process was started for.
PARTS = ("life", "memories", "pulse")
#: The four scope flags ``--strict-scope`` asks for, all of them.
SCOPE_FLAGS = {"db_path": "--db-path", "agent_id": "--agent-id",
               "person_id": "--person-id", "project_scope": "--project-scope"}
_JOURNAL_LAST = 5


class Refused(ValueError):
    """A request the person's commands can't answer, with the one plain
    sentence that says why."""


# ── Reading the memories ──


def first_kept(reading: _Reading, memories: Mapping[str, tuple[Any, Any]]) -> dict[str, Any]:
    """When each memory was first kept: for ``memories`` (each id with its own
    ``(created_at, lineage)``), the earliest ``created_at`` along its line of
    corrections, followed back through ``lineage.supersedes``. A memory no
    correction made was kept when it was written. So a memory first kept on
    Oct 4 and corrected on Oct 14 reads "Kept Oct 4. Corrected Oct 14." What
    it replaced is read from this scope, archived or not."""
    known: dict[str, tuple[Any, list[str]]] = {
        memory_id: (created, lineage_supersedes(lineage))
        for memory_id, (created, lineage) in memories.items()
    }
    wanted = {old for _, older in known.values() for old in older if old not in known}
    while wanted:
        found = reading.kept_rows(wanted)
        for row in found:
            known[row["id"]] = (row["created_at"], lineage_supersedes(row["lineage"]))
        for gone in wanted - {row["id"] for row in found}:
            known[gone] = (None, [])  # not in this scope: nothing more to follow
        wanted = {old for row in found for old in known[row["id"]][1] if old not in known}

    def first(memory_id: str) -> Any:
        earliest: tuple[datetime, Any] | None = None
        stack, seen = [memory_id], set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            created, older = known.get(current, (None, []))
            moment = when(created)
            if moment is not None and (earliest is None or moment < earliest[0]):
                earliest = (moment, created)
            stack.extend(older)
        return earliest[1] if earliest else known[memory_id][0]

    return {memory_id: first(memory_id) for memory_id in memories}


def memory_view(row: Mapping[str, Any], kept: Any) -> dict[str, Any]:
    """One memory as ``mnemos memories --json`` gives it.

    ``alive`` is its accessibility: the value decay lowers and a return
    raises, and the one its states follow (under .05 it goes dormant, under
    .01 it is archived). ``kept`` is when its first version was kept
    (``first_kept``); ``corrected`` is when this version was written, when it
    replaced another through a correction, else None. ``conversation`` is the
    session it was kept in (Mnemos records its id, never a title). ``impact``
    is what it changed, empty when it says nothing its words don't, as the log
    shows it. ``author`` is "agent", "person", "tool" or "unknown"
    (``AUTHORS``)."""
    words = (row["content"] or "").strip()
    impact = (row["impact"] or "").strip()
    session = (row["author_session"] or "").strip()
    return {
        "id": row["id"],
        "words": words,
        "kept": utc_iso(kept or row["created_at"]),
        "state": row["state"],
        "alive": round(min(1.0, max(0.0, float(row["accessibility"] or 0.0))), 3),
        "conversation": {"id": session, "title": None} if session else None,
        "corrected": utc_iso(row["created_at"]) if lineage_supersedes(row["lineage"]) else None,
        "impact": impact if impact != words else "",
        "author": AUTHORS.get(row["author_kind"] or "", "unknown"),
    }


def memories_view(
    scope: MnemosScope, *, state: str | None = None, limit: int | None = None, offset: int = 0,
) -> dict[str, Any]:
    """``mnemos memories --json``: ``{"memories": [...], "counts": {"active",
    "dormant", "archived"}}``. The active and dormant memories of the scope
    (or those in ``state``), oldest first and in a stable order, from
    ``offset`` on, at most ``limit`` (None: all); ``counts`` is always the
    whole scope's. Read through the log's own reading of them, from a
    connection that can't write and leaves nothing beside the store; a store
    that isn't there is no memories, and is never made."""
    if state is not None and state not in STATES:
        raise Refused(f"--state is one of: {', '.join(STATES)}.")
    if limit is not None and limit < 0:
        raise Refused("--limit takes a number of memories, 0 or more.")
    if offset < 0:
        raise Refused("--offset takes a number of memories, 0 or more.")
    names = (*STATES, "archived")
    db = Path(scope.db_path).expanduser()
    if not db.is_file():
        return {"memories": [], "counts": {name: 0 for name in names}}
    conn = open_read_only(db)
    try:
        reading = _Reading(conn, scope)
        if not reading.has("engrams"):
            return {"memories": [], "counts": {name: 0 for name in names}}
        rows = reading.memory_rows(state=state, limit=limit, offset=offset)
        counts = reading.state_counts()
        kept = first_kept(reading, {row["id"]: (row["created_at"], row["lineage"]) for row in rows})
    finally:
        conn.close()
    return {
        "memories": [memory_view(row, kept[row["id"]]) for row in rows],
        "counts": {name: int(counts.get(name, 0)) for name in names},
    }


# ── Searching ──


def search_view(
    runtime: MnemosRuntime, query: str, max_results: int = SEARCH_RESULTS,
) -> dict[str, Any]:
    """``mnemos search --json``: ``{"query", "results": [{"id", "words", "kept",
    "closeness", "found"}]}``, closest first. The mind's own recall over the
    memories alone (``MnemosRuntime.search_memories``), which writes nothing.
    ``found`` and ``closeness`` are decided where recall's rows decide how
    each was found (``found_by``, ``closeness``): closeness is relative within
    this one search, the first result 1.0, and nothing found is no results."""
    if max_results < 1:
        raise Refused("-n takes a number of results, 1 or more.")
    results = runtime.search_memories(query, max_results=max_results)
    near = closeness(results)
    kept: dict[str, Any] = {}
    if results and runtime._store is not None:
        kept = first_kept(_Reading(runtime._store._get_conn(), runtime.scope), {
            result.engram.id: (result.engram.created_at, {"supersedes": result.engram.lineage.supersedes})
            for result in results
        })
    return {
        "query": query,
        "results": [
            {
                "id": result.engram.id,
                "words": (result.engram.content or "").strip(),
                "kept": utc_iso(kept.get(result.engram.id) or result.engram.created_at),
                "closeness": near[index],
                "found": found_by(result),
            }
            for index, result in enumerate(results)
        ],
    }


# ── The interface: one process, the same commands ──


def _whole(request: Mapping[str, Any], key: str, default: int | None, *, least: int) -> int | None:
    """The whole number a request gives for ``key``, or ``default``."""
    value = request.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < least:
        raise Refused(f'"{key}" takes a whole number, {least} or more.')
    return value


def _words(request: Mapping[str, Any], key: str) -> str:
    """The text a request gives for ``key``, or ``""``."""
    value = request.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Refused(f'"{key}" takes text.')
    return value


def _one_sentence(exc: BaseException) -> str:
    """Something that went wrong, as one plain line."""
    detail = " ".join(str(exc).split())[:240]
    return f"Mnemos couldn't do that ({type(exc).__name__}{': ' + detail if detail else ''})."


def missing_scope(flags: Mapping[str, str | None]) -> list[str]:
    """The scope flags ``--strict-scope`` asks for that ``flags`` doesn't give
    (None or blank), as the command line names them, in their order."""
    return [flag for key, flag in SCOPE_FLAGS.items() if not (flags.get(key) or "").strip()]


def strict_scope_sentence(missing: list[str]) -> str:
    """Why ``--strict-scope`` won't start, in one sentence."""
    return (f"--strict-scope takes the memory's scope from all four of {', '.join(SCOPE_FLAGS.values())}, "
            f"and never from the environment or the config; this is missing {', '.join(missing)}.")


# ── What a host asks of the whole notebook ──


def waiting(notes: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The agent's questions still waiting on the person, as the page counts
    them (``waiting`` in ``page/shared/words.js``): in each thread of notes
    (a note and the replies that answer it), the newest note, when it is the
    agent's and ends with a question mark."""
    by_id = {note["id"]: note for note in notes}

    def root(note: Mapping[str, Any]) -> str:
        current = note
        for _ in range(50):
            above = current.get("replyTo")
            if not above or above not in by_id:
                break
            current = by_id[above]
        return current["id"]

    last: dict[str, Mapping[str, Any]] = {}
    for note in notes:
        thread, newest = root(note), last.get(root(note))
        moment, then = when(note.get("at")), when(newest.get("at")) if newest else None
        if newest is None or (moment is not None and then is not None and moment >= then):
            last[thread] = note
    return [note for note in last.values()
            if note.get("author") == "agent" and (note.get("text") or "").strip().endswith("?")]


def change_token(life: Mapping[str, Any], memories: Mapping[str, Any]) -> str:
    """A stamp of everything the notebook shows (its two documents, less the
    moment each was made): the same while nothing a host would show has
    changed, and different once anything has."""
    shown = {"life": {k: v for k, v in life.items() if k != "made"},
             "memories": {k: v for k, v in memories.items() if k != "made"}}
    digest = hashlib.sha256(json.dumps(shown, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()[:20]


def summary_of(life: Mapping[str, Any], memories: Mapping[str, Any]) -> dict[str, Any]:
    """``summary``: what each part of the notebook counts, read from the very
    documents its page is given, so a host's counts and the page's agree.
    ``unread`` is the agent's notes the person hasn't read; ``waiting`` its
    questions still waiting on them (``waiting``)."""
    notes = life.get("notes") or []
    theirs = [note for note in notes if note.get("author") == "agent"]
    questions = life.get("questions") or {}
    memory = life.get("memory") or {}
    states = memory.get("states") or {}
    return {
        "missing": bool(life.get("missing")),
        "counts": {
            "memories": int(memory.get("count", 0)),
            "states": {name: int(states.get(name, 0)) for name in ("active", "dormant", "archived")},
            "shared": len((life.get("shared") or {}).get("rows") or []),
            "beliefs": len(life.get("beliefs") or []),
            "questions": int(questions.get("open", 0)),
            "answered": len(questions.get("answered") or []),
            "journal": len(life.get("journal") or []),
            "notes": len(theirs),
            "replies": len(notes) - len(theirs),
            "hours": len(life.get("hours") or []),
            "made": len(life.get("studio") or []),
            "carrying": len(life.get("handoffs") or []),
        },
        "unread": sum(1 for note in theirs if not note.get("read")),
        "waiting": len(waiting(notes)),
        "change_token": change_token(life, memories),
    }


def _acted(answer: Mapping[str, Any]) -> Any:
    """What one of the page's acts answered (``{"result": ...}`` or
    ``{"error": one sentence}``), as the interface answers: the result, or
    the same sentence refused."""
    if "result" in answer:
        return answer["result"]
    raise Refused(str(answer.get("error") or "That couldn't be done just now."))


class Interface:
    """``mnemos interface``: the person's commands for an app, answered by one
    process for as long as the app keeps it.

    Nothing a read does can change the memory: the memories are read as
    ``mnemos memories`` reads them, the journal and the notes from a store
    opened read-only, and a search through one read-only runtime, opened once
    the store exists. A correction, a forget or a reply opens a writing
    runtime of its own and closes it when done.

    The meaning model loads once, in the background as the process starts
    (its libraries' import included, the larger part of the wait), and every
    runtime here embeds with it (``EmbeddingIndex.share_embedder``). What
    needs it (a search, a correction) waits for the load; what doesn't (the
    memories, the journal, the notes, a forget) answers at once.
    """

    def __init__(self, *, db_path: str | None = None, agent_id: str | None = None,
                 person_id: str | None = None, project_scope: str | None = None,
                 person: bool | None = None, strict_scope: bool = False) -> None:
        # Whose a correction or a forget is: the person's own app says so (``person=True``: the page someone clicked,
        # even when an agent's server is serving it); with None, as the command line decides, by the shell it runs in.
        self._person = person
        self._flags = {
            "db_path": db_path, "agent_id": agent_id,
            "person_id": person_id, "project_scope": project_scope,
        }
        missing = missing_scope(self._flags) if strict_scope else []
        if missing:
            raise Refused(strict_scope_sentence(missing))
        self._strict = strict_scope
        self.scope = resolve_scope(**self._flags)
        self._exporter: Exporter | None = None
        self._reader: MnemosRuntime | None = None
        # The meaning model, once loaded: an index of no store, only a backend.
        self._model: EmbeddingIndex | None = None
        self._loading: threading.Thread | None = None

    def _as_person(self) -> bool:
        return self._person if self._person is not None else not run_by_agent()

    def warm(self) -> None:
        """Start loading the meaning model in the background, once."""
        if self._loading is None:
            self._loading = threading.Thread(target=self._load, name="mnemos-meaning", daemon=True)
            self._loading.start()

    def _load(self) -> None:
        index = EmbeddingIndex(read_only=True)
        if index.available:
            index.embed_query("mnemos")  # loads the model; a failure says why, once
        self._model = index

    def _loaded(self) -> None:
        """Wait until the meaning model has loaded (starting it if need be)."""
        self.warm()
        assert self._loading is not None
        self._loading.join()

    def _runtime(self, *, read_only: bool) -> MnemosRuntime:
        runtime = MnemosRuntime(
            **self._flags, use_dedicated_model=False, read_only=read_only, marks_lived=False,
        )
        runtime._ensure_init()
        if runtime._embedding_index is not None and self._model is not None:
            runtime._embedding_index.share_embedder(self._model)
        return runtime

    def _reading(self) -> MnemosRuntime | None:
        """The read-only runtime a search runs in, once the model has loaded
        and the store exists; None while there is no store."""
        if self._reader is None and self._held():
            self._loaded()
            self._reader = self._runtime(read_only=True)
        return self._reader

    def _store(self) -> ReadOnlyEngramStore | None:
        """The store, opened read-only for one request, or None while it
        isn't there."""
        return ReadOnlyEngramStore(self.scope.db_path) if self._held() else None

    def _scope_args(self) -> dict[str, str]:
        return {
            "agent_id": self.scope.agent_id,
            "person_id": self.scope.person_id,
            "project_scope": self.scope.project_scope,
        }

    def _held(self) -> bool:
        """Whether the store is there (nothing here ever makes it)."""
        return Path(self.scope.db_path).expanduser().is_file()

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    # Each command answers with exactly what its one-shot --json prints.

    def memories(self, request: Mapping[str, Any]) -> Any:
        state = request.get("state")
        if state is not None and state not in STATES:
            raise Refused('"state" is "active" or "dormant".')
        return memories_view(
            self.scope, state=state,
            limit=_whole(request, "limit", None, least=0),
            offset=_whole(request, "offset", 0, least=0) or 0,
        )

    def search(self, request: Mapping[str, Any]) -> Any:
        query = _words(request, "query")
        max_results = _whole(request, "max_results", SEARCH_RESULTS, least=1) or SEARCH_RESULTS
        reader = self._reading()
        if reader is None:
            return {"query": query, "results": []}
        return search_view(reader, query, max_results)

    def correct(self, request: Mapping[str, Any]) -> Any:
        memory_id, text = _words(request, "memory_id"), _words(request, "text")
        if not text.strip():
            raise NothingChanged("A correction needs the memory's new words.")
        if not self._held():
            raise NothingChanged(f"No memory {memory_id.strip()} is held here.")
        self._loaded()  # the new words are embedded as they are kept
        writer = self._runtime(read_only=False)
        try:
            return writer.correct_memory(memory_id, text, person=self._as_person())
        finally:
            writer.close()

    def forget(self, request: Mapping[str, Any]) -> Any:
        memory_id = _words(request, "memory_id")
        if not self._held():
            raise NothingChanged(f"No memory {memory_id.strip()} is held here.")
        writer = self._runtime(read_only=False)
        try:
            return writer.forget_memory(memory_id, person=self._as_person())
        finally:
            writer.close()

    def journal(self, request: Mapping[str, Any]) -> Any:
        last = _whole(request, "last", _JOURNAL_LAST, least=1) or _JOURNAL_LAST
        store = self._store()
        if store is None:
            return []
        try:
            return journal_view(store, last=last, **self._scope_args())
        finally:
            store.close()

    def notes(self, request: Mapping[str, Any]) -> Any:
        unread = request.get("unread", False)
        if not isinstance(unread, bool):
            raise Refused('"unread" is true or false.')
        store = self._store()
        if store is None:
            return []
        try:
            # Only reading, so nothing is marked read, as `notes --json` reads.
            return notes_view(store, unread=unread, **self._scope_args())
        finally:
            store.close()

    def reply(self, request: Mapping[str, Any]) -> Any:
        note_id, text = _words(request, "note_id"), _words(request, "text")
        if not self._held():
            raise Refused("Nothing saved: there are no notes here yet.")
        writer = self._runtime(read_only=False)
        try:
            try:
                reply_id = writer.reply_to_note(note_id, text)
            except ValueError as exc:
                raise Refused(f"Nothing saved: {exc}") from exc
            # Answering a note is reading it, as `notes reply` counts it.
            try:
                writer.mark_notes_read([note_id])
            except sqlite3.Error:
                pass
            assert writer._store is not None
            return note_view(writer._store.get_note(reply_id, **writer._scope_args()))
        finally:
            writer.close()

    def note(self, request: Mapping[str, Any]) -> Any:
        """A note of the person's own to the agent, answering nothing: kept
        exactly as given, as theirs, and the stored note answered in the
        ``notes`` item shape. It writes nothing else, and never makes a store."""
        text = _words(request, "text")
        if not self._held():
            raise Refused("Nothing saved: there is no memory here yet.")
        writer = self._runtime(read_only=False)
        try:
            try:
                note_id = writer.person_note(text)
            except ValueError as exc:
                raise Refused(f"Nothing saved: {exc}") from exc
            assert writer._store is not None
            return note_view(writer._store.get_note(note_id, **writer._scope_args()))
        finally:
            writer.close()

    # What a host asks of the whole notebook, and the rest of what the person can do on its page.

    def hello(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """What this Mnemos answers, asked once by a host: the protocol's
        version, Mnemos's, the store schema this build writes, every command,
        whose a write is, and the one memory this process reads."""
        from ..package_version import mnemos_version
        from ..store.sqlite_store import SCHEMA_VERSION

        return {
            "protocol": PROTOCOL,
            "mnemos": mnemos_version(),
            "schema": SCHEMA_VERSION,
            "commands": list(COMMANDS),
            "parts": list(PARTS),
            "writes_as": "person" if self._as_person() else "agent",
            "strict_scope": self._strict,
            "scope": {**self._scope_args(), "db_path": str(Path(self.scope.db_path).expanduser()),
                      "held": self._held()},
        }

    def _notebook(self) -> Exporter:
        """The notebook's exporter for this process's one mind, kept as the
        page's server keeps one, so a finished hour's record is read once."""
        if self._exporter is None:
            self._exporter = Exporter(self.scope, person_name())
        return self._exporter

    def notebook(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """One part of the notebook, exactly as its page is given it, made by
        the page's own code: ``life`` and ``memories`` by ``Exporter.export``,
        ``pulse`` by ``export.pulse``. ``life`` comes with ``pictures``: for
        each picture the page would show, the file itself, inside this mind's
        studio, where a host with no web server can read it."""
        part = request.get("part")
        if part not in PARTS:
            raise Refused('"part" is "life", "memories" or "pulse".')
        exporter = self._notebook()
        if part == "pulse":
            since = request.get("since")
            if since is not None and not isinstance(since, str):
                raise Refused('"since" takes a time, in ISO 8601.')
            return {"part": part, "document": pulse(exporter, since)}
        life, memories = exporter.export()
        if part == "memories":
            return {"part": part, "document": memories}
        root = exporter.studio_dir
        pictures: dict[str, str] = {}
        for item in life.get("studio") or []:
            found = studio_picture(root, item["path"]) if root is not None and item.get("picture") else None
            if found is not None:
                pictures[item["path"]] = found
        return {"part": part, "document": life, "pictures": pictures}

    def summary(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """What each part of the notebook counts, what waits on the person,
        and a ``change_token`` that changes only when something shown does
        (``summary_of``), from the page's own documents."""
        return summary_of(*self._notebook().export())

    def read(self, request: Mapping[str, Any]) -> Any:
        """Mark the agent's notes read, as the page does when the person reads
        them there: through the page's own act (``companion.server.read_notes``),
        its limits and its sentences. Answers the ids this marked."""
        from ..companion.server import read_notes

        return _acted(read_notes(self.scope, request.get("note_ids")))

    def hours(self, request: Mapping[str, Any]) -> Any:
        """Turn the agent's quiet hours on, at the times given, or off, as the
        page's Settings does (``companion.server.quiet_hours``): what `mnemos
        daemon install --hours --write` or `uninstall --hours --write` does
        for this scope. Answers what it said."""
        from ..companion.server import quiet_hours

        return _acted(quiet_hours(self.scope, request))

    def shared(self, request: Mapping[str, Any]) -> Any:
        """Add to the shared notebook, correct one of the person's own there,
        or let one go (asked twice, ``"confirmed": true``), as the page does
        (``shared_memory.notebook_act``), always as the person."""
        from ..shared_memory import notebook_act

        return _acted(notebook_act(request))

    def answer(self, line: str) -> dict[str, Any]:
        """The answer to one request line: ``{"id": <the request's>, "result":
        <what the command's one-shot --json prints>}``, or ``{"id": ...,
        "error": "<one plain sentence>"}``."""
        try:
            request = json.loads(line)
        except ValueError:
            request = None
        if not isinstance(request, dict):
            return {"id": None, "error": "A request is one JSON object on one line."}
        request_id = request.get("id")
        command = request.get("command")
        if command not in COMMANDS:
            return {
                "id": request_id,
                "error": f"There is no command {json.dumps(command)} here; "
                         f"the commands are {', '.join(COMMANDS)}.",
            }
        try:
            return {"id": request_id, "result": getattr(self, command)(request)}
        except (Refused, NothingChanged) as exc:
            return {"id": request_id, "error": str(exc)}
        except Exception as exc:  # any other failure is the one plain line, never a trace
            return {"id": request_id, "error": _one_sentence(exc)}


def serve(
    stdin: IO[str] | None = None, stdout: IO[str] | None = None, *,
    as_person: bool = False, strict_scope: bool = False, stderr: IO[str] | None = None,
    **flags: str | None,
) -> int:
    """Run ``mnemos interface`` until stdin closes: read one JSON request a
    line and answer each with one JSON line, flushed at once. The meaning
    model starts loading as it starts.

    ``as_person``: every write is the person's, whatever the shell it runs in
    says. ``strict_scope``: the scope comes from the four flags alone; with
    any of them missing it reads nothing, says why in one sentence on stderr
    and ends at once, with status 2."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    missing = missing_scope(flags) if strict_scope else []
    if missing:
        print(strict_scope_sentence(missing), file=stderr, flush=True)
        return 2
    for stream in (stdin, stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    interface = Interface(**flags, person=True if as_person else None, strict_scope=strict_scope)
    interface.warm()
    try:
        for line in stdin:
            if not line.strip():
                continue
            stdout.write(json.dumps(interface.answer(line), ensure_ascii=False) + "\n")
            stdout.flush()
    finally:
        interface.close()
    return 0
