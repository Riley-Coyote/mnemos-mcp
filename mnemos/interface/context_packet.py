"""The session-start packet: one builder for the hook and ``mnemos_context``.

The packet is where this memory does its work. An agent reads it at the start
of every session; recall is called far less often. It holds what matters and
nothing else, in the order the reader needs it, and a section with nothing to
say is left out rather than announced empty.

It is written as the reader waking, not as a briefing about someone. A mind
that reads "Yours (Opus 5.5), if you are Opus 5.5" and a list of ids reads
about the one who wrote its notes; it doesn't remember being them (Luca's own
words on first connecting, 2026-09-30: continuity "arrived as a briefing"). So
the reader speaks as "I", what is its own carries no signature, what a
colleague left carries theirs, and the machinery (ids, confidences, calls) sits
apart at the end, for the tools:

0. The opening: when and where, and who the reader is with; the first wake
   that crosses a restart ends it with the first thing kept here ("I still
   have what I kept before: ..."), once (``first_restart``).
1. What I've come to see: each belief once, the firm ones apart from the ones
   still forming.
2. Where I was: one handoff whole, the reader's own, else the newest one left
   where the reader works (``mnemos.place``), else the newest; then a short
   line for every other note a session left in the last three days, this
   place's first, each with its age and, when it isn't the reader's, its
   model. Then, when the latest journal entry is under three days old, its
   first line ("last time I wrote in my journal (5 hours ago): ...").
3. What's been changing in me: the reader's newest impact lines, up to five.
4. What I keep coming back to: the ideas the noticer found in the agent's own
   words, up to two, until one becomes a belief.
5. The person (or "who i'm with"): what the agent marked standing, how the
   person wants it to work in every session: the newest mark first, up to
   five, one line each in the memory's own words, and a count of the rest.
6. A question: at most one thing the agent's memory is waiting on it for.
7. While I was away: the reader's own quiet hour, when one ended since the
   last packet, what the person wrote into this memory with ``mnemos
   remember`` or ``mnemos correct`` since the last wake that showed it, at
   most three, oldest first, one line saying the person let memories go
   (``mnemos forget``) and on which days, never their words, and the
   person's replies to the agent's notes, and notes of their own, that
   haven't reached a packet yet, at most three, each delivered once.
8. For the memory tools: the ids and calls for what the packet showed, in the
   order it showed them, never to be shown to the person.

Event notes, foundational notes and upkeep's report are not in it; recall
finds them.

The voice follows who is reading. The reader is this memory's resident when
its model line wrote most of the signed notes here (``resident_model``), and
then the store-wide things (beliefs, unsigned notes) are its own; an earlier
version of its line is itself. Another kind of model is a guest: its own notes
are still its own, the rest is labelled with who wrote
it, and the opening says whose memory it is visiting. A reader the harness
didn't name gets every note labelled, and the opening says so once.

The SessionStart hook injects this text and ``mnemos_context`` returns it, so the
two can no longer disagree. Building it never runs maintenance. Besides the
handoff shown whole, it stays under ``PACKET_MAX_CHARS``: that handoff is never
cut and takes no room from the rest, notes are cut at a sentence boundary, and
``mnemos_recall(<id>)`` returns a note whole.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import code_version
from ..authorship import (
    clean_model_id,
    clean_session_id,
    display_name,
    from_same_session,
    model_line,
    same_mind,
)
from ..dream_journal import DREAM_JOURNAL_TAG
from ..retrieval.reactive import ReactiveRetriever, RetrievalResult
from ..place import place_name, place_of, place_words

if TYPE_CHECKING:
    from ..store.sqlite_store import EngramStore


_CHARS_PER_TOKEN = 4

# A briefing longer than this is no longer read closely. The handoff shown
# whole is never cut and is not counted here: a long one used to push out
# everything else (on a real store, Oct 12 2026, a 4,800-character handoff
# left no beliefs, nothing that had been changing and no question). With 6,000
# here, the short lines for the other live threads were the first thing cut,
# and a session woke with one thread of the eight in progress.
PACKET_MAX_CHARS = 8000
DEFAULT_TOKEN_BUDGET = PACKET_MAX_CHARS // _CHARS_PER_TOKEN

# At most this many questions per packet. A packet that asks for work every
# time becomes a chore list appended to every conversation.
PACKET_QUESTIONS = 1

_BELIEFS_SHOWN = 6

# What the agent marked standing: how the human wants it to work in every
# session, not just now. A standing rule is obeyed, not recalled, so no usage
# signal (reinforcement, recency, recall) can be trusted to bring it here; the
# agent's own mark does. The newest marks open the section on who the agent is
# with, this many, one line each; the closing section says how to list the rest.
STANDING_SHOWN = 5
# How long a standing line may run, cut at a sentence boundary. Each is a rule
# to follow in this session, so it is not shortened to make room: when the
# packet must lose something, these are the last lines to go.
STANDING_CHARS = 320
STANDING_LABEL = "Standing, how the human wants you to work in every session:"
STANDING_LIST_CALL = 'mnemos_recall(query="", standing=true)'
# A capture keeps its context after its words, after a blank line. A standing
# line is the words themselves.
_CONTEXT_MARK = "\n\nContext: "

# How long a note may run before it is cut, tried in turn until the packet fits.
# A typical note on a real store is about a thousand characters.
_NOTE_CHARS = (420, 320, 240, 160, 100)
# Other sessions' handoffs are one short line each: enough to tell which thread
# it is and who left it (handoffs open with a headline). Shown whole, they
# would fill the packet (a typical one is about 2,000 characters), and up to
# seven of them are listed.
_OTHER_HANDOFF_CHARS = 200
# A light wake (``wake="light"``) cuts the reader's handoff here: a quick
# session needs where things stand, and the id reads the rest whole.
LIGHT_HANDOFF_CHARS = 700

_HEADER = "## waking up"
# For the tools that list handoffs on request (``simple_runtime``), which speak
# to the agent rather than as it.
COLLEAGUE_LINE = (
    "A colleague's note is theirs: take what's useful and don't claim its work as yours."
)
# The same, in the packet, where the reader speaks.
_COLLEAGUE_OWN_WORDS = (
    "A colleague's note is theirs: I take what's useful and don't claim the work."
)

# Whose note is it, as the reader should take it.
_OWN = "own"
_COLLEAGUE = "colleague"
_UNPLACED = "unplaced"

# Who is reading, relative to this memory: its resident, a guest (another
# model), or a reader the harness didn't name.
SELF = "self"
GUEST = "guest"
UNKNOWN = "unknown"

# A belief below this confidence is shown as still forming.
_FIRM = 0.5

# The latest journal entry is shown, as its first line, only while it is this
# recent; past it, it is the journal's to keep, found by recall. The agent's
# own words are not shown stale as though they were news.
JOURNAL_LIVE = timedelta(days=3)
_JOURNAL_LINE_CHARS = 240
# The person's replies a packet hands over at most, oldest first; the rest wait
# for the next waking. A reply is never left out for room (a reply left out
# would be marked delivered unread), so each is cut at a sentence boundary
# instead, and the whole waits behind its id.
REPLIES_SHOWN = 3
_REPLY_CHARS = 700
_REPLIED_NOTE_CHARS = 100

# What has been changing in the reader: its newest impact lines, this many.
CHANGING_SHOWN = 5
# The ideas the noticer found that the reader keeps coming back to, this many.
RETURNING_SHOWN = 2
# A quiet hour shows once, when it ended after the last delivery; with none
# recorded, while it is this recent.
HOUR_LIVE = timedelta(days=3)
_WAKE_LINE_CHARS = 160
# What the person wrote into this memory (``mnemos remember``), this many at
# most, oldest first: each shows once, those written after the last wake that
# showed one (meta ``person_words_shown_at``); with none shown yet, those of
# the last ``PERSON_WORDS_LIVE``.
PERSON_WORDS_SHOWN = 3
PERSON_WORDS_LIVE = timedelta(days=3)
_PERSON_WORDS_CHARS = 200
# The first capture's words, as the first wake across a restart says them.
_FIRST_RESTART_CHARS = 120


def build_context_packet(
    store: "EngramStore",
    query: str = "",
    *,
    agent_id: str = "default",
    person_id: str = "user",
    project_scope: str = "global",
    session_id: str = "",
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    include_prompt: bool = True,
    include_engrams: bool = True,
    include_reflections: bool = True,
    mark_surfaced: bool = True,
    max_functional: int = 10,
    max_hypomnema: int = 8,
    max_engrams: int = 6,
    reader_model: str = "",
    reader_session: str = "",
    workdir: str = "",
    older_than_store: bool | None = None,
    person_name: str = "",
    now: datetime | None = None,
    wake: str = "full",
    session_counter: int | None = None,
) -> dict[str, Any]:
    """Build the packet an agent reads before its first turn.

    ``reader_model`` and ``reader_session`` are the model and harness session
    about to read it, when the harness says: they decide whether a handoff is
    the reader's own or a colleague's, and whether the reader wakes as this
    memory's resident. ``workdir`` is the folder the session works in. Its
    name and its repository's name say where it wakes; they never choose
    whose memory this is.

    ``person_name`` is the name of the person this memory works with, when the
    operator gave one; without it the packet says "who i'm with". ``now`` is
    the moment of waking (local time), for tests; it defaults to the clock.

    ``session_counter`` is the runtime's session count, when the caller has
    one: with ``reader_session`` it tells whether this wake is a later
    session than the first capture (``first_restart``).

    ``older_than_store`` says whether this code is older than the store (the
    runtime passes its own check). Code older than the store shows no question
    and spends no showing. Left as None, the store's minimum decides.

    ``query`` is used only with ``include_engrams``: long-term graph recall for
    that cue, appended after the briefing. ``session_id``, ``max_functional``
    and ``max_hypomnema`` are accepted for existing callers; the briefing has no
    functional-memory section and fixed section sizes.
    """
    del session_id, max_functional, max_hypomnema  # accepted, not used
    wake = wake.lower() if isinstance(wake, str) else wake
    wake = wake if wake in ("full", "light") else "full"
    scope = {"agent_id": agent_id, "person_id": person_id, "project_scope": project_scope}
    reader_model = clean_model_id(reader_model)
    reader_session = clean_session_id(reader_session)
    if older_than_store is None:
        older_than_store = _older_than(store)

    handoffs = store.live_handoffs(
        **scope, reader_session=reader_session, reader_place=place_of(workdir),
    )
    handoff = handoffs[0] if handoffs else None

    # Every standing memory in scope, the newest mark first, each said once, as
    # its standing line.
    standing = _standing(store, scope)
    standing_ids = {item["id"] for item in standing}
    notes = [
        entry for entry in store.search_hypomnema(
            "", **scope, limit=_MAX_NOTES, exclude_kinds=("handoff", "maintenance_report"),
        )
        if DREAM_JOURNAL_TAG not in (entry.get("tags") or [])
    ]
    standing_notes: dict[str, list[str]] = {}
    for entry in notes:
        if entry.get("graduated_to_engram_id") in standing_ids:
            standing_notes.setdefault(entry["graduated_to_engram_id"], []).append(entry["id"])
    place = place_words(workdir)

    resident = resident_model(store, scope)
    beliefs = [_serialize_belief(b) for b in _beliefs_for(
        store.get_beliefs(agent_id, active_only=True), reader_model, resident,
    )]
    beliefs = beliefs[:_BELIEFS_SHOWN]

    questions: list[dict[str, Any]] = []
    if wake != "light" and include_reflections and not older_than_store:
        try:
            questions = store.pending_reflections(
                **scope, limit=PACKET_QUESTIONS, reader_model=reader_model or resident,
            )
        except Exception:
            # A packet must never fail because of the reflection queue.
            questions = []

    voice = reader_voice(reader_model, resident)
    owner = reader_model or resident
    changing = [] if wake == "light" else _changing(store, scope, owner)
    returning = (
        [] if wake == "light" or voice != SELF
        else _returning(store, scope, agent_id, owner)
    )

    found: list[RetrievalResult] = []
    if wake != "light" and include_engrams and query.strip():
        found = _graph_recall(store, query, scope, max_engrams)

    woke = now or datetime.now().astimezone()
    if woke.tzinfo is None:
        woke = woke.astimezone()
    journal = None if wake == "light" else _latest_journal(store, scope, woke)
    replies = [] if wake == "light" else _waiting_replies(store, scope)
    person_words = [] if wake == "light" else _person_words(store, scope, woke)
    person_letgo = [] if wake == "light" else _person_letgo(store, scope)
    kept_before = (
        None if wake == "light"
        else first_restart(store, scope, reader_session, session_counter)
    )
    # Read before this packet records its delivery: an hour shows once.
    hour = (
        None if wake == "light" or voice != SELF
        else _latest_hour(store, scope, owner, woke)
    )

    packet: dict[str, Any] = {
        "include_engrams": include_engrams,
        "reader_model": reader_model,
        "reader_session": reader_session,
        "resident": resident,
        "voice": voice,
        "person_name": " ".join((person_name or "").split())[:80],
        "woke_at": woke.isoformat(),
        "wake": wake,
        "place": place_name(workdir),
        "workdir": workdir,
        "place_words": sorted(place),
        "older_than_store": older_than_store,
        "scope": dict(scope),
        "query": query,
        "handoff": handoff,
        "other_handoffs": [] if wake == "light" else handoffs[1:],
        "standing": standing,
        "standing_notes": standing_notes,
        # The waking note is the agent's own words. Event notes, foundational
        # notes and upkeep's report are not in it; recall finds them. Their
        # keys stay, empty, for callers that read them.
        "hypomnema": [],
        "beliefs": beliefs,
        "reflections": questions,
        "maintenance_report": None,
        "maintenance_reports": [],
        "journal": journal,
        "replies": replies,
        "person_words": person_words,
        "person_letgo": person_letgo,
        "first_restart": kept_before,
        "changing": changing,
        "returning": returning,
        "hour": hour,
        "mnemos_engrams": [_serialize_retrieval_result(result) for result in found],
    }

    max_chars = _max_chars(token_budget) + handoff_room(packet)
    text, shown = _render(packet, max_chars=max_chars)
    packet["shown"] = shown
    # The opening, and the first restart's line in it, show only with a body.
    said_kept_before = bool(kept_before and text)
    # What the briefing rendered is what it showed: the ids a later section
    # must not repeat, and nothing it selected but cut for room.
    text, kept = _append_graph(packet, text, max_chars)
    packet["mnemos_engrams"] = kept
    if mark_surfaced and wake != "light":
        _record_delivery(
            store, scope, shown, deliver_replies=not older_than_store,
            person_words=person_words, person_letgo=person_letgo,
            first_restart_shown=said_kept_before,
        )
    if kept:
        # Recall for a cue is a use, and only what the reader was shown is
        # reinforced: once per session, never by code older than the store
        # (see ReactiveRetriever.reinforce). The briefing's own sections
        # reinforce nothing.
        shown_ids_kept = {entry["id"] for entry in kept}
        ReactiveRetriever(store).reinforce(
            [result for result in found if result.engram.id in shown_ids_kept],
            query,
            agent_id=agent_id,
            session=reader_session or None,
        )
    if include_prompt:
        packet["prompt"] = text
    return packet


def format_context_packet(
    packet: dict[str, Any], *, token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> str:
    """The briefing text for a packet ``build_context_packet`` returned."""
    max_chars = _max_chars(token_budget) + handoff_room(packet)
    text, shown = _render(packet, max_chars=max_chars)
    return _append_graph({**packet, "shown": shown}, text, max_chars)[0]


def carried_count(packet: dict[str, Any]) -> int:
    """How many handoffs, standing memories, notes, reports, journal lines,
    replies, the person's own words, lines about what the person let go,
    changing lines, returning ideas, beliefs, quiet hours and questions the
    packet showed after its budget: 0 means the session started from nothing.
    A question counts: it asks about a memory of this scope, so a wake that
    shows only one is memory read, not amnesia."""
    shown = packet.get("shown") or {}
    return (
        len(shown.get("questions") or [])
        + len(shown.get("handoffs") or [])
        + len(shown.get("standing") or [])
        + len(shown.get("notes") or [])
        + int(bool(shown.get("report")))
        + int(bool(shown.get("journal")))
        + len(shown.get("replies") or [])
        + len(shown.get("person_words") or [])
        + int(bool(shown.get("person_letgo")))
        + len(shown.get("changing") or [])
        + len(shown.get("returning") or [])
        + len(shown.get("beliefs") or [])
        + int(bool(shown.get("hour")))
    )


def shown_ids(packet: dict[str, Any]) -> set[str]:
    """The ids of everything the packet rendered: handoffs, standing memories
    and the notes paired with them, notes, lessons (an engram's id), the
    report, the journal entry and the replies. Only what survived the budget
    counts; a note selected but cut for room was not shown. A caller appending
    more to the packet leaves these out, so nothing is shown twice."""
    shown = packet.get("shown") or {}
    ids = set(shown.get("handoffs") or []) | set(shown.get("notes") or [])
    ids.update(shown.get("replies") or [])
    if shown.get("journal"):
        ids.add(shown["journal"])
    paired = packet.get("standing_notes") or {}
    for engram_id in shown.get("standing") or []:
        ids.add(engram_id)
        ids.update(paired.get(engram_id) or [])
    if shown.get("report"):
        ids.add(shown["report"])
    return ids


def shown_memories(packet: dict[str, Any]) -> tuple[set[str], list[str]]:
    """What the briefing showed, as the cue must know it to never show it again
    in the session: every id ``shown_ids`` names, with the memory each shown
    note is one object with (a capture's note and memory, R07), the memory
    each question shown asks about, each memory whose impact line shows as
    changing, each memory of an idea shown as returning, each memory of the
    person's words shown, and every memory its graph section showed
    (``--include-graph``); and the whole words of each standing memory, impact
    line, person's words and graph memory shown, since the same words can sit
    under another id."""
    ids = shown_ids(packet)
    shown = packet.get("shown") or {}
    rendered = set(shown.get("notes") or []) | set(shown.get("standing") or [])
    texts: list[str] = []
    for entry in packet.get("standing") or []:
        if entry.get("id") not in rendered:
            continue
        paired = entry.get("graduated_to_engram_id")
        if paired:
            ids.add(paired)
        words = entry.get("content") or entry.get("text") or ""
        if words:
            texts.append(words.split(_CONTEXT_MARK, 1)[0])
    # What the new note shows of memories (Ready C): the memory each question
    # shown asks about, whose words it quotes; the memories whose impact lines
    # show as what has been changing in me; and each idea shown as returning.
    asked = set(shown.get("questions") or [])
    for item in packet.get("reflections") or []:
        if item.get("id") in asked and item.get("target_id"):
            ids.add(item["target_id"])
    changing = set(shown.get("changing") or [])
    ids.update(changing)
    for item in packet.get("changing") or []:
        if item.get("id") in changing and item.get("text"):
            texts.append(item["text"])
    for joined in shown.get("returning") or []:
        ids.update(engram_id for engram_id in joined.split(",") if engram_id)
    # What the person wrote into my memory, as its line showed it.
    told = set(shown.get("person_words") or [])
    ids.update(told)
    for item in packet.get("person_words") or []:
        if item.get("id") in told:
            words = _person_words_line(item)
            if words:
                texts.append(words)
    # What the graph section kept: ``build_context_packet`` leaves only those.
    for entry in packet.get("mnemos_engrams") or []:
        ids.add(entry["id"])
        for words in (entry.get("impact"), entry.get("content")):
            if words:
                texts.append(words.split(_CONTEXT_MARK, 1)[0])
    return ids, texts


def fit_section(
    heading: str, groups: list[tuple[str, list[tuple[Any, str]]]], room: int,
) -> tuple[str, list[Any]]:
    """A section of whole entries that fits in ``room`` characters.

    ``groups`` are ``(label, [(key, entry text), ...])`` in rank order; a label
    is printed only above an entry kept under it ("" prints none). An entry
    that doesn't fit is dropped whole, never cut, and later ones may still
    fit. Returns the text and the keys of the entries kept, or ``("", [])``
    when none fits.
    """
    lines = [heading]
    used = len(heading)
    kept: list[Any] = []
    for label, entries in groups:
        labelled = not label
        for key, text in entries:
            cost = len(text) + 1 + (0 if labelled else len(label) + 1)
            if used + cost > room:
                continue
            if not labelled:
                lines.append(label)
                labelled = True
            lines.append(text)
            used += cost
            kept.append(key)
    return ("\n".join(lines), kept) if kept else ("", [])


def room_after(text: str, max_chars: int) -> int:
    """How long a section appended after ``text`` may be, separator included,
    for the whole to stay under ``max_chars``."""
    return max_chars - 1 - len(text) - (2 if text else 0)


# ── Whose note is it ──


def whose_handoff(
    note: dict[str, Any], reader_model: str = "", reader_session: str = "",
) -> tuple[str, str]:
    """How a handoff is introduced to its reader, and whose it is.

    Returns the label ("Yours (Opus 5.5), from another session, 5 hours ago")
    and one of ``own``, ``colleague`` or ``unplaced``.

    A note the reader's own model line left is the reader's, from this session
    or another one, and from any version of the line: several sessions of one
    model often work in parallel, and each is the same agent (Riley's
    decision, 2026-09-26). A note another kind of model left is a colleague's,
    even in this session, where it means the model was switched. When the reader's model isn't known, or the note isn't
    signed, the label says so and the reader is left to judge.

    This is the wording of the tools that list handoffs on request; the packet
    introduces the same decision in the reader's own voice (``when_left``).
    """
    whose, name, age, session = _whose(note, reader_model, reader_session)
    where = {True: "from this session", False: "from another session"}.get(session)
    if whose == _COLLEAGUE:
        during = ", earlier in this session" if session is True else ""
        return f"From {name}, a colleague{during}, {age}", _COLLEAGUE
    if whose == _OWN:
        if name:
            return _joined(f"Yours ({name})", where, age), _OWN
        return f"Yours, from this session, {age} (unsigned)", _OWN
    elsewhere = " in another session" if session is False else ""
    if name:
        return f"From {name}{elsewhere}, {age} (yours if you are {name})", _UNPLACED
    return f"Unsigned{elsewhere}, {age} (maybe yours, maybe a colleague's)", _UNPLACED


def when_left(
    note: dict[str, Any], reader_model: str = "", reader_session: str = "",
) -> tuple[str, str]:
    """How the packet introduces a handoff, and whose it is.

    The reader's own note says only when and where it was left ("2 hours ago,
    this session"): a note of one's own isn't signed to oneself. A colleague's
    says who ("Fable 5, a colleague, 26 hours ago"). A note the reader can't
    place says whose signature it carries, with no "if you are" in it: the
    opening line of the packet says once what a reader who isn't this
    memory's resident should make of it.
    """
    whose, name, age, session = _whose(note, reader_model, reader_session)
    if whose == _OWN:
        where = {True: "this session", False: "in another session"}.get(session)
        return _joined(age, where), _OWN
    if whose == _COLLEAGUE:
        during = "earlier in this session" if session is True else None
        return _joined(f"{name}, a colleague", during, age), _COLLEAGUE
    elsewhere = "in another session" if session is False else None
    return _joined(name or "unsigned", age, elsewhere), _UNPLACED


def _whose(
    note: dict[str, Any], reader_model: str, reader_session: str,
) -> tuple[str, str, str, bool | None]:
    """Whose a handoff is (``own``, ``colleague`` or ``unplaced``), with its
    author's name, its age, and whether the reader's session left it."""
    author = clean_model_id(note.get("author_model") or "")
    reader = clean_model_id(reader_model)
    session = from_same_session(reader_session, note.get("author_session"))
    age = _age_text(note.get("created_at"))
    name = display_name(author)
    if author and reader and not same_mind(author, reader):
        return _COLLEAGUE, name, age, session
    if (author and (reader or session is True)) or (not author and session is True):
        return _OWN, name, age, session
    return _UNPLACED, name, age, session


def _joined(*parts: str | None) -> str:
    return ", ".join(part for part in parts if part)


# ── Who is reading ──


def _beliefs_for(beliefs, reader_model, resident) -> list:
    """The beliefs a reader wakes with as its own: those its line signed (any
    version) and the unsigned ones. A guest (another kind of model than the
    resident) wakes with only the ones its own line signed. Without a reader,
    the resident's line's and the unsigned ones."""
    if clean_model_id(reader_model) and resident and not same_mind(reader_model, resident):
        return [belief for belief in beliefs if same_mind(belief.author_model, reader_model)]
    owner = reader_model or resident
    return [belief for belief in beliefs
            if not clean_model_id(belief.author_model)
            or same_mind(belief.author_model, owner)]


def resident_model(store: "EngramStore", scope: dict[str, str]) -> str:
    """The model line whose memory this mostly is: the one that signed the
    most of its live notes and handoffs, or ``""`` when none did or two tie;
    returned as the id that line signed with most recently, so the opening
    names its newest version.

    One store is often shared by several models, and each signs what it
    writes. The one that has written most of it is who it belongs to, and
    reading it as that line, any version of it, is waking as oneself. Another
    kind of model reading it is a guest. A store with nothing signed has no resident, and whoever reads it
    reads it as their own, as before signatures existed.
    """
    try:
        rows = store._get_conn().execute(
            """
            SELECT author_model, COUNT(*), MAX(created_at) FROM hypomnema_entries
            WHERE agent_id = ? AND person_id = ? AND project_scope = ?
              AND active = 1 AND COALESCE(author_model, '') != ''
            GROUP BY author_model
            """,
            (scope["agent_id"], scope["person_id"], scope["project_scope"]),
        ).fetchall()
    except Exception:
        return ""
    counts: dict[str, int] = {}
    newest: dict[str, tuple[str, str]] = {}
    for model, count, latest in rows:
        model = clean_model_id(model)
        line = model_line(model)
        if not line:
            continue
        counts[line] = counts.get(line, 0) + int(count)
        if line not in newest or (latest or "") > newest[line][0]:
            newest[line] = (latest or "", model)
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return ""
    return newest[ranked[0][0]][1]


def reader_voice(reader_model: str, resident: str) -> str:
    """``self`` when the reader is this memory's resident (or it has none),
    ``guest`` when it is another kind of model, ``unknown`` when the harness didn't
    say which model is reading."""
    if not clean_model_id(reader_model):
        return UNKNOWN
    if not resident or same_mind(reader_model, resident):
        return SELF
    return GUEST


# ── Where the session works: ranking only (see ``mnemos.place``) ──


# ── What is marked standing ──

# Every note in scope is read for the standing memories' notes; a few hundred
# is typical.
_MAX_NOTES = 5000


def _standing(store: "EngramStore", scope: dict[str, str]) -> list[dict[str, Any]]:
    """The standing memories in scope, the newest mark first. A packet never
    fails because of them: a store that cannot say has none here."""
    try:
        return store.standing_engrams(**scope)
    except Exception:
        return []


# ── Rendering within the budget ──


def _max_chars(token_budget: int) -> int:
    return max(800, int(token_budget) * _CHARS_PER_TOKEN)


def handoff_room(packet: dict[str, Any]) -> int:
    """The room the handoff shown whole takes, which the budget leaves out:
    it is never cut, and a long one must not push out the rest."""
    handoff = packet.get("handoff")
    if not handoff:
        return 0
    text = handoff.get("content") or ""
    if packet.get("wake") == "light":
        return len(cut_at_sentence(text, LIGHT_HANDOFF_CHARS)[0])
    return len(text)


def _render(packet: dict[str, Any], *, max_chars: int) -> tuple[str, dict[str, Any]]:
    """The briefing text, and what it shows.

    Notes are cut shorter until the packet fits; then, if it still doesn't,
    whole items are left out, least needed first. The reader's handoff is
    never cut. What comes back as shown is what was rendered.
    """
    dropped: set[tuple[str, str]] = set()
    for chars in _NOTE_CHARS:
        text, shown = _compose(packet, chars, dropped)
        if len(text) < max_chars:
            return text, shown
    for victim in _drop_order(packet):
        dropped.add(victim)
        text, shown = _compose(packet, _NOTE_CHARS[-1], dropped)
        if len(text) < max_chars:
            break
    return text, shown


def _drop_order(packet: dict[str, Any]) -> list[tuple[str, str]]:
    """What leaves the packet first when it does not fit: the quiet hour's
    line, then what has been changing (the oldest first), then what I keep
    coming back to (the last first), then other sessions' notes (the last
    listed first: the farthest from here, the oldest), then what the person
    wrote into my memory (the newest first), then the journal line; the
    question, beliefs and standing lines go last. The oldest standing mark
    leaves first: standing says how to work in this session. The person's
    replies never go: one left out would be marked delivered unread.

    The other threads stay longer than they did: several sessions are often
    live at once, and a session that doesn't know the others exist repeats or
    undoes their work. Their lines are cut short before anything leaves."""
    standing = (packet.get("standing") or [])[:STANDING_SHOWN]
    return [
        ("report", ""),
        *(("changing", item["id"]) for item in reversed(packet.get("changing") or [])),
        *(("returning", ",".join(entry["ids"])) for entry in reversed(packet.get("returning") or [])),
        *(("other", entry["id"]) for entry in reversed(packet.get("other_handoffs") or [])),
        *(("person_words", item["id"]) for item in reversed(packet.get("person_words") or [])),
        ("journal", ""),
        ("question", ""),
        *(("belief", belief["id"]) for belief in reversed(packet.get("beliefs") or [])),
        *(("standing", item["id"]) for item in reversed(standing)),
    ]


def _compose(
    packet: dict[str, Any], chars: int, dropped: set[tuple[str, str]],
) -> tuple[str, dict[str, Any]]:
    shown: dict[str, Any] = {
        "handoffs": [], "standing": [], "notes": [], "questions": [], "report": None,
        "journal": None, "replies": [], "hour": None, "person_words": [],
        "person_letgo": [], "changing": [], "returning": [], "beliefs": [],
    }
    # What the closing section lists for the tools, in the order shown.
    tools: dict[str, Any] = {
        "standing": [], "more": 0, "cut": [], "beliefs": [], "calls": [], "replies": [],
        "person_notes": [],
    }
    # Being comes before news. Someone waking doesn't first recall last
    # night's events; they are simply themselves, with the people they know,
    # and what happened comes after. Fresh readers said the same (2026-09-30):
    # how they see things "settles in easily", events and task lists "read
    # more like a briefing". So the full wake is the agent's own words, in
    # the order a mind wakes: how I see, where I was, what has been changing
    # in me, what I keep coming back to, who I'm with, one question, and
    # while I was away. What leaves first under the budget is ``_drop_order``.
    if packet.get("wake") == "light":
        sections = [
            _format_beliefs(packet, dropped, shown, tools),
            _format_who(packet, chars, dropped, shown, tools),
            _format_left_off(packet, chars, dropped, shown, tools),
        ]
    else:
        sections = [
            _format_beliefs(packet, dropped, shown, tools),
            _format_where_left(packet, chars, dropped, shown, tools),
            _format_changing(packet, dropped, shown, tools),
            _format_returning(packet, dropped, shown),
            _format_who(packet, chars, dropped, shown, tools),
            _format_question(packet, dropped, shown, tools),
            _format_away(packet, dropped, shown, tools),
        ]
    body = "\n\n".join(section for section in sections if section)
    if not body:
        return "", shown
    parts = (f"{_HEADER}\n{_opening(packet)}", body, _format_tools(packet, tools))
    return "\n\n".join(part for part in parts if part), shown


def _opening(packet: dict[str, Any]) -> str:
    """When and where the reader wakes, and who it is with; for a reader that
    isn't this memory's resident, whose memory this is; and, the first wake
    across a restart, what was kept before (``first_restart``)."""
    line = _opening_line(packet)
    kept_before = packet.get("first_restart")
    if kept_before:
        return f'{line} I still have what I kept before: "{kept_before}".'
    return line


def _opening_line(packet: dict[str, Any]) -> str:
    when = _when_text(packet.get("woke_at"))
    place = packet.get("place") or ""
    person = packet.get("person_name") or ""
    context = [part for part in (place and f"in {place}", person and f"with {person}") if part]
    voice = packet.get("voice")
    # The time ends in "a.m." or "p.m.", which already closes a sentence.
    if voice == SELF:
        return f"{when} I'm {', '.join(context)}." if context else when
    line = f"{when}, {', '.join(context)}." if context else when
    resident = display_name(packet.get("resident") or "")
    if not resident:
        return line
    if voice == GUEST:
        reader = display_name(packet.get("reader_model") or "")
        return f"{line} This memory is mostly {resident}'s; I'm {reader}, visiting."
    return f"{line} This memory is mostly {resident}'s; if I'm not {resident}, I'm visiting."


def _when_text(woke_at: str | None) -> str:
    """``Wednesday, September 30, 4:12 a.m.``, in the waking moment's own zone."""
    try:
        moment = datetime.fromisoformat(woke_at or "")
    except (TypeError, ValueError):
        moment = datetime.now().astimezone()
    hour = moment.hour % 12 or 12
    half = "a.m." if moment.hour < 12 else "p.m."
    return f"{moment:%A}, {moment:%B} {moment.day}, {hour}:{moment:%M} {half}"


def _append_graph(
    packet: dict[str, Any], text: str, max_chars: int,
) -> tuple[str, list[dict[str, Any]]]:
    """The briefing with opted-in graph recall appended in the room left under
    the budget, leaving out what the briefing already showed: the text, and
    the graph entries kept."""
    if not packet.get("include_engrams"):
        return text, []
    shown = shown_ids(packet)
    entries = [entry for entry in packet.get("mnemos_engrams") or [] if entry["id"] not in shown]
    prefix = text or _HEADER
    section, kept = fit_section(
        "### Mnemos Graph",
        [("", [(entry, _graph_line(entry)) for entry in entries])],
        room_after(prefix, max_chars),
    )
    if not section:
        return text, []
    return f"{prefix}\n\n{section}", kept


def _format_left_off(
    packet: dict[str, Any],
    chars: int,
    dropped: set[tuple[str, str]],
    shown: dict[str, Any],
    tools: dict[str, Any],
) -> str:
    handoff = packet.get("handoff")
    if not handoff:
        return ""
    reader_model = packet.get("reader_model") or ""
    reader_session = packet.get("reader_session") or ""
    label, whose = when_left(handoff, reader_model, reader_session)
    relations = {whose}
    heading = "### where i was" if whose == _OWN else "### where things were left"
    text = handoff["content"]
    if packet.get("wake") == "light":
        text, cut = cut_at_sentence(handoff["content"], LIGHT_HANDOFF_CHARS)
        if cut:
            tools["cut"].append(handoff["id"])
    lines = [heading, f"{label}:", text]
    shown["handoffs"].append(handoff["id"])
    others = [
        entry for entry in packet.get("other_handoffs") or []
        if ("other", entry["id"]) not in dropped
    ]
    if others:
        lines.extend(["", "also from the last three days:"])
        for entry in others:
            label, whose = when_left(entry, reader_model, reader_session)
            relations.add(whose)
            who = f"me, {label}" if whose == _OWN else label
            lines.append(f"- {who}: {_cut(entry, min(chars, _OTHER_HANDOFF_CHARS), tools)}")
            shown["handoffs"].append(entry["id"])
    if relations & {_COLLEAGUE, _UNPLACED}:
        lines.append(_COLLEAGUE_OWN_WORDS)
    return "\n".join(lines)


def _format_where_left(
    packet: dict[str, Any],
    chars: int,
    dropped: set[tuple[str, str]],
    shown: dict[str, Any],
    tools: dict[str, Any],
) -> str:
    """Where I left off: the handoffs, then the journal's latest line when it
    is recent. With no handoff the journal line makes the section on its own."""
    left_off = _format_left_off(packet, chars, dropped, shown, tools)
    journal = _format_journal(packet, dropped, shown, tools)
    if left_off and journal:
        return f"{left_off}\n\n{journal}"
    if journal:
        heading = "### where i was" if packet.get("voice") == SELF else "### where things were left"
        return f"{heading}\n{journal}"
    return left_off


def _format_journal(
    packet: dict[str, Any],
    dropped: set[tuple[str, str]],
    shown: dict[str, Any],
    tools: dict[str, Any],
) -> str:
    """The first line of the journal's latest entry, when it is under three
    days old: "last time I wrote in my journal (5 hours ago): ...".

    It says "I" only when the entry is the reader's own, by the rule a handoff
    follows (``_whose``): an entry another kind of model signed is a colleague's, and
    one no one can place says who signed it. No id and no tool name here; when
    more of the entry exists than this line, its id waits in the closing
    section, where ``mnemos_recall`` reads it whole.
    """
    entry = packet.get("journal")
    if not entry or ("journal", "") in dropped:
        return ""
    # The quiet hour's line says this entry already, under while i was away.
    hour = packet.get("hour") or {}
    if _hour_shows(packet, dropped) and hour.get("journal_id") == entry.get("id"):
        return ""
    whose, name, age, _session = _whose(
        {
            "author_model": entry.get("model_id"),
            "author_session": entry.get("session_id"),
            "created_at": entry.get("created_at"),
        },
        packet.get("reader_model") or "",
        packet.get("reader_session") or "",
    )
    text = entry.get("text") or ""
    words, cut = cut_at_sentence(_first_line(text), _JOURNAL_LINE_CHARS)
    if whose == _OWN:
        line = f"last time I wrote in my journal ({age}): {words}"
    elif name:
        line = f"the last journal entry here, by {name} ({age}): {words}"
    else:
        line = f"the last journal entry here, unsigned ({age}): {words}"
    shown["journal"] = entry["id"]
    if cut or sum(1 for row in text.splitlines() if row.strip()) > 1:
        tools["cut"].append(entry["id"])
    return line


def _person_words_line(item: dict[str, Any]) -> str:
    """The person's own words as their line under "while i was away" shows
    them: without the context a capture keeps after them, on one line, cut
    at a sentence boundary."""
    own = (item.get("content") or "").split(_CONTEXT_MARK, 1)[0]
    return cut_at_sentence(own, _PERSON_WORDS_CHARS)[0]


def _letgo_line(name: str, times: list[str], woke_at: str | None) -> str:
    """The one line saying the person let memories of mine go, and on which
    days, in the waking moment's own zone: never the words, never an id.
    "- Riley let a memory of mine go on Oct 18; its words went with it.", or
    for several, "- Riley let 3 memories of mine go, on Oct 18 and Oct 19;
    their words went with them." """
    woke = _moment(woke_at)
    days: list[str] = []
    for time in times:
        moment = _moment(time)
        if moment is None:
            continue
        local = moment.astimezone(woke.tzinfo) if woke else moment.astimezone()
        day = f"{local:%b} {local.day}"
        if day not in days:
            days.append(day)
    on = " and ".join(filter(None, [", ".join(days[:-1]), days[-1]])) if days else ""
    if len(times) == 1:
        return f"- {name} let a memory of mine go{f' on {on}' if on else ''}; its words went with it."
    return (
        f"- {name} let {len(times)} memories of mine go{f', on {on}' if on else ''}; "
        "their words went with them."
    )


def _reply_lines(
    packet: dict[str, Any], shown: dict[str, Any], tools: dict[str, Any],
) -> list[str]:
    """The person's replies to the agent's notes, and notes of their own, that
    have not reached a packet yet, oldest first: a reply as "<person> replied
    to my note "<its first line>": <reply>", and a note of their own, which
    answers nothing, as "<person> left me a note (<when>): <note>".

    Never left out for room (``_drop_order``): a reply or note the reader was
    not shown must not be marked delivered. A long one is cut at a sentence
    boundary, and its whole waits behind its id in the closing section. The
    note a reply answers is "my" note only when the agent who wrote it is the
    reader; another model's is named, and one no one can place is just "a
    note". Ids and tool names stay in the closing section.
    """
    person = packet.get("person_name") or "the person I'm with"
    reader = packet.get("reader_model") or ""
    lines = []
    for item in packet.get("replies") or []:
        words, cut = cut_at_sentence(item.get("text") or "", _REPLY_CHARS)
        if item.get("in_reply_to"):
            title, _ = cut_at_sentence(
                _first_line(item.get("reply_to_text") or ""), _REPLIED_NOTE_CHARS,
            )
            about = f' "{title}"' if title else ""
            owner = _whose_note(item.get("reply_to_model"), reader)
            lines.append(f"- {person} replied to {owner} note{about}: {words}")
            tools["replies"].append(item["id"])
        else:
            lines.append(f"- {person} left me a note ({_age_text(item.get('created_at'))}): {words}")
            tools["person_notes"].append(item["id"])
        shown["replies"].append(item["id"])
        if cut:
            tools["cut"].append(item["id"])
    return lines


def _whose_note(note_model: object, reader_model: str) -> str:
    """"my", "Fable 5's" or "a": whose note a reply answers, to this reader."""
    author, reader = clean_model_id(note_model), clean_model_id(reader_model)
    if author and reader:
        return "my" if same_mind(author, reader) else f"{display_name(author)}'s"
    return "a"


def _first_line(text: str) -> str:
    """The first line of ``text`` that says something, on one line."""
    for row in (text or "").splitlines():
        if row.strip():
            return " ".join(row.split())
    return ""


def _format_who(
    packet: dict[str, Any],
    chars: int,
    dropped: set[tuple[str, str]],
    shown: dict[str, Any],
    tools: dict[str, Any],
) -> str:
    """Who I'm with: what the agent marked standing, under the person's name
    when the operator gave it.

    The standing lines come first, the newest mark first, at most
    ``STANDING_SHOWN``, each the memory's own words on one line, cut at a
    sentence boundary. Their ids, which unmark one or read it whole, and the
    call that lists the rest wait in the closing section for the tools.
    Without a standing memory there is no section.
    """
    person = packet.get("person_name") or ""
    standing = packet.get("standing") or []
    lines: list[str] = []
    if standing:
        kept = [
            item for item in standing[:STANDING_SHOWN]
            if ("standing", item["id"]) not in dropped
        ]
        # Relational, not an order from outside: a fresh reader heard "what
        # Riley asks of me" as describing it from outside (2026-09-30).
        lines.append("how we work, every session:")
        for item in kept:
            lines.append(f"- {standing_words(item['content'])}")
            shown["standing"].append(item["id"])
            tools["standing"].append(item["id"])
        more = len(standing) - len(kept)
        tools["more"] = more
        if more and kept:
            lines.append(f"and {more} more like these.")
        elif more:
            lines.append(f"{more} left out for room.")
    heading = f"### {person}" if person else "### who i'm with"
    return "\n".join([heading, *lines]) if lines else ""


def standing_words(content: str) -> str:
    """A standing memory as one line: its own words, without the context a
    capture keeps after them, cut at a sentence boundary."""
    words = (content or "").split(_CONTEXT_MARK, 1)[0]
    return cut_at_sentence(words, STANDING_CHARS)[0]


def _cut(
    item: dict[str, Any], limit: int, tools: dict[str, Any], *, key: str = "content",
) -> str:
    """A note on one line, cut at a sentence boundary; a cut note's id waits
    in the closing section, where ``mnemos_recall`` reads it whole."""
    text, cut = cut_at_sentence(item.get(key) or "", limit)
    if cut:
        tools["cut"].append(item["id"])
    return text


def _format_beliefs(
    packet: dict[str, Any],
    dropped: set[tuple[str, str]],
    shown: dict[str, Any],
    tools: dict[str, Any],
) -> str:
    """Each belief once, in its own words: the firm ones, then those still
    forming.

    A belief changes only when a correction names it by id, so the ids, with
    each belief's confidence, wait in the closing section, in this order.
    """
    beliefs = [
        belief for belief in packet.get("beliefs") or []
        if ("belief", belief["id"]) not in dropped
    ]
    if not beliefs:
        return ""
    firm = [belief for belief in beliefs if float(belief["confidence"]) >= _FIRM]
    forming = [belief for belief in beliefs if float(belief["confidence"]) < _FIRM]
    voice = packet.get("voice")
    resident = display_name(packet.get("resident") or "")
    if voice in (SELF, GUEST):
        headings = ("what i've come to see", "what i'm starting to see")
    elif resident:
        headings = (f"what {resident} has come to see", f"what {resident} is starting to see")
    else:
        headings = ("what this memory holds", "what this memory is starting to hold")
    lines = [f"### {headings[0] if firm else headings[1]}"]
    lines.extend(f"- {belief['content']}" for belief in firm)
    if firm and forming:
        lines.append("still forming:")
    lines.extend(f"- {belief['content']}" for belief in forming)
    shown["beliefs"].extend(belief["id"] for belief in [*firm, *forming])
    tools["beliefs"] = [
        (belief["id"], int(round(float(belief["confidence"]) * 100)))
        for belief in [*firm, *forming]
    ]
    return "\n".join(lines)


def _format_question(
    packet: dict[str, Any],
    dropped: set[tuple[str, str]],
    shown: dict[str, Any],
    tools: dict[str, Any],
) -> str:
    """What the memory is waiting on the reader for, in words; the call that
    answers it waits in the closing section."""
    items = packet.get("reflections") or []
    if not items or ("question", "") in dropped:
        return ""
    shown["questions"].extend(item["id"] for item in items)
    # The verdicts live with the runtime that applies them. Imported here, not
    # at the top: the runtime imports this module.
    from ..simple_runtime import verdict_call_lines

    if packet.get("voice") == SELF:
        heading = "a question waiting for me" if len(items) == 1 else "questions waiting for me"
    else:
        heading = "one question" if len(items) == 1 else "questions"
    lines = [f"### {heading}"]
    for item in items:
        excerpt = item.get("excerpt") or ""
        if len(excerpt) >= _EXCERPT_CHARS:
            excerpt = excerpt.rsplit(" ", 1)[0] + " […]"
        if "[evidence:" not in item["prompt"]:
            lines.append(f'about "{excerpt}":')
        lines.append(question_words(item["prompt"]))
        call = verdict_call_lines(item)
        tools["calls"].extend(
            call if call is not None
            else [f'mnemos_reflect(target_id="{item["target_id"]}", text="…")']
        )
    lines.append(
        "If something true comes, I'll answer it in my own words; if not, I'll leave it, "
        "and it fades on its own."
    )
    return "\n".join(lines)


def format_questions(items: list[dict[str, Any]]) -> str:
    """The question section: what the memory asks, and the call that answers it.

    A question that takes a verdict shows the call with its verdicts, so an
    agent copying it gives the verdict that decides the question: answered
    without one, a belief question forms nothing.
    """
    if not items:
        return ""
    # The verdicts live with the runtime that applies them. Imported here, not
    # at the top: the runtime imports this module.
    from ..simple_runtime import verdict_call_lines

    heading = "One question" if len(items) == 1 else "Questions"
    lines = [f"### {heading}"]
    for item in items:
        excerpt = item.get("excerpt") or ""
        if len(excerpt) >= _EXCERPT_CHARS:
            excerpt = excerpt.rsplit(" ", 1)[0] + " […]"
        lines.append(f'About: "{excerpt}"')
        lines.append(_MARKER.sub("", item["prompt"]).strip())
        call = verdict_call_lines(item)
        if call is None:
            lines.append(f'mnemos_reflect(target_id="{item["target_id"]}", text="…")')
        else:
            lines.extend(call)
    lines.append(
        "Answer in your own words if one comes. If nothing true does, leave it; "
        "it fades on its own."
    )
    return "\n".join(lines)


# The store gives a question the first 160 characters of its memory, cut
# wherever they end.
_EXCERPT_CHARS = 160

# The queue's own markers ("[theme:room]", "[belief:<id>]", "[ref:<id>]") say
# which theme or memory a question is about. They are for Mnemos, not the reader.
_MARKER = re.compile(r"\s*\[(?:theme|belief|ref|evidence):[^\]]*\]")
_SENTENCES = re.compile(r"(?<=[.?!])\s+")
_VERDICT_WORD = re.compile(r"\bverdict\b", re.IGNORECASE)


def question_words(prompt: str) -> str:
    """A question as the reader holds it: its words up to the first sentence
    that says how to give a verdict ("If it is, state it in one line with
    verdict hold…", "Verdict hold if it is, retire if…"). How to
    answer waits with the call, among the ids for the memory tools; a fresh
    reader found the question "reads like a form I'm being asked to fill in"
    with it (2026-09-30). A sentence inside a quotation is the memory's own
    words, and is kept."""
    text = _MARKER.sub("", prompt or "").strip()
    sentences = _SENTENCES.split(text)
    for index, sentence in enumerate(sentences[1:], start=1):
        if _VERDICT_WORD.search(sentence) and '"' not in sentence:
            return " ".join(sentences[:index])
    return text


def _format_changing(
    packet: dict[str, Any],
    dropped: set[tuple[str, str]],
    shown: dict[str, Any],
    tools: dict[str, Any],
) -> str:
    """What has been changing in me: my newest impact lines, newest first, each
    with its age. Traces, not records: how something changed me, in my words."""
    del tools  # nothing here is shown by id
    items = [
        item for item in packet.get("changing") or []
        if ("changing", item["id"]) not in dropped
    ]
    if not items:
        return ""
    heading = (
        "### what's been changing in me" if packet.get("voice") == SELF
        else "### what has been changing in this mind"
    )
    lines = [heading]
    for item in items:
        words = cut_at_sentence(item["text"], _WAKE_LINE_CHARS)[0]
        lines.append(f"- {words} ({_age_text(item['created_at'])})")
        shown["changing"].append(item["id"])
    return "\n".join(lines)


def _format_returning(
    packet: dict[str, Any], dropped: set[tuple[str, str]], shown: dict[str, Any],
) -> str:
    """What I keep coming back to: the ideas the noticer found in my own words,
    on how many days, until one becomes a belief."""
    entries = [
        entry for entry in packet.get("returning") or []
        if ("returning", ",".join(entry["ids"])) not in dropped
    ]
    if not entries:
        return ""
    lines = ["### what i keep coming back to"]
    lines.extend(f'- "{entry["quote"]}" ({entry["days"]} days)' for entry in entries)
    shown["returning"].extend(",".join(entry["ids"]) for entry in entries)
    return "\n".join(lines)


def _format_away(
    packet: dict[str, Any],
    dropped: set[tuple[str, str]],
    shown: dict[str, Any],
    tools: dict[str, Any],
) -> str:
    """While I was away: my own quiet hour, when one ended since the last
    packet, then what the person wrote into my memory (a correction of
    theirs said as one), then the memories the person let go, by day, then
    the person's replies to my notes. Upkeep's report isn't here: its words
    aren't mine."""
    lines = []
    which = _hour_shows(packet, dropped)
    if which:
        hour = packet["hour"]
        line = f"{which} ({_age_text(hour.get('ended_at'))})"
        first = hour.get("first_line") or ""
        if first:
            line += f": {cut_at_sentence(first, _WAKE_LINE_CHARS)[0]}"
        lines.append(line)
        shown["hour"] = hour.get("ended_at")
    name = packet.get("person_name") or "The person"
    for item in packet.get("person_words") or []:
        if ("person_words", item["id"]) in dropped:
            continue
        words = _person_words_line(item)
        if item.get("corrected"):
            lines.append(f'- {name} corrected a memory of mine; it now says: "{words}"')
        else:
            lines.append(f'- {name} wrote this into my memory: "{words}"')
        shown["person_words"].append(item["id"])
    letgo = packet.get("person_letgo") or []
    if letgo:
        lines.append(_letgo_line(name, letgo, packet.get("woke_at")))
        shown["person_letgo"] = list(letgo)
    lines.extend(_reply_lines(packet, shown, tools))
    if not lines:
        return ""
    heading = "### while i was away" if packet.get("voice") == SELF else "### lately, in this memory"
    return "\n".join([heading, *lines])


def _hour_shows(packet: dict[str, Any], dropped: set[tuple[str, str]]) -> str:
    """How the quiet hour's line begins when this wake shows it, else ``""``."""
    hour = packet.get("hour")
    if not hour or ("report", "") in dropped:
        return ""
    return {"mine": "- my quiet hour", "ours": "- our hour"}.get(hour.get("kind"), "")


def _format_tools(packet: dict[str, Any], tools: dict[str, Any]) -> str:
    """The machinery the packet kept out of the reader's voice: the ids and
    calls for what it showed, in the order it showed them. ``""`` when it
    showed nothing that needs one."""
    lines: list[str] = []
    if tools["standing"]:
        line = f"- what's marked standing, in order: {', '.join(tools['standing'])}"
        if tools["more"]:
            line += f"; all of it: {STANDING_LIST_CALL}"
        lines.append(line)
    elif tools["more"]:
        lines.append(f"- what's marked standing: {STANDING_LIST_CALL}")
    if tools.get("replies"):
        lines.append(
            f"- replies to my notes, in order: {', '.join(tools['replies'])}; to answer one: "
            'mnemos_note(text="…", kind="…", in_reply_to="<its id>")'
        )
    if tools.get("person_notes"):
        whose = f"{packet['person_name']}'s notes" if packet.get("person_name") else "notes"
        lines.append(
            f"- {whose} to me, in order: {', '.join(tools['person_notes'])}; to answer one: "
            'mnemos_note(text="…", kind="…", in_reply_to="<its id>")'
        )
    if tools["cut"]:
        calls = ", ".join(f'mnemos_recall("{entry_id}")' for entry_id in tools["cut"])
        lines.append(f"- what was cut short, whole, in order: {calls}")
    if tools["beliefs"]:
        beliefs = ", ".join(f"{belief_id} ({percent}%)" for belief_id, percent in tools["beliefs"])
        lines.append(f"- beliefs, in order: {beliefs}")
    if tools["calls"]:
        lines.append(f"- to answer the question: {'; '.join(tools['calls'])}")
    if not lines:
        return ""
    person = packet.get("person_name") or "the person I'm with"
    return "\n".join([
        "### for the memory tools",
        f"Ids and calls for my memory tools. Never shown to {person}.",
        *lines,
    ])


def _graph_line(item: dict[str, Any]) -> str:
    confidence = int(float(item["confidence"]) * 100)
    return (
        f"- {item['display']} "
        f"[{item['kind']}, score {float(item['score']):.2f}, confidence {confidence}%]"
    )


# ── Cutting a note ──

_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]*(?=\s)")
_CUT_MARK = " […]"


def cut_at_sentence(text: str, limit: int) -> tuple[str, bool]:
    """``text`` on one line, cut to ``limit`` at a sentence boundary: the text,
    and whether it was cut.

    When the last sentence that fits would leave less than half the room (a
    short first sentence before a long one), the cut falls on a word boundary
    instead. A note never ends mid-word. The mark a cut text ends with is
    within ``limit``: a cut text is never longer than it.
    """
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed, False
    room = max(1, limit - len(_CUT_MARK))
    ends = [
        match.end() for match in _SENTENCE_END.finditer(collapsed[: room + 1])
        if match.end() <= room
    ]
    if ends and ends[-1] >= (limit - len(_CUT_MARK)) // 2:
        head = collapsed[: ends[-1]]
    else:
        head = collapsed[:room].rsplit(" ", 1)[0]
    return f"{head.rstrip()}{_CUT_MARK}", True


# ── Small helpers ──


def _older_than(store: "EngramStore") -> bool:
    """Whether this code is older than the store, read from the store itself."""
    try:
        minimum = store.min_code_version()
    except Exception:
        return False
    return minimum is not None and minimum > code_version.MAINTENANCE_CODE_VERSION


def _record_delivery(
    store: "EngramStore",
    scope: dict[str, str],
    shown: dict[str, Any],
    *,
    deliver_replies: bool = True,
    person_words: list[dict[str, Any]] | None = None,
    person_letgo: list[str] | None = None,
    first_restart_shown: bool = False,
) -> None:
    """Count what was actually shown: a handoff as delivered, a question as
    one showing spent, a reply of the person's as delivered, once, a quiet
    hour as shown (meta ``last_hour_shown``), so it shows once, what the
    person wrote as shown up to the newest shown (meta
    ``person_words_shown_at``), what the person let go as said up to the
    newest said (meta ``person_letgo_shown_at``), and the first restart as
    said (meta ``verified_at``), so each shows once.

    A reply is marked only when it was shown, and never by code older than the
    store (``deliver_replies`` False): what delivered means is a rule newer
    code may have replaced. Older code still shows it, and it is delivered, and
    marked, by the code that comes after.
    """
    for handoff_id in shown["handoffs"]:
        store.mark_handoff_surfaced(handoff_id, **scope)
    if deliver_replies and shown.get("replies"):
        try:
            store.mark_replies_delivered(shown["replies"], **scope)
        except Exception:
            pass  # shown again next time rather than lost
    if shown["questions"]:
        try:
            store.mark_reflections_surfaced(shown["questions"])
        except Exception:
            pass
    prefix = f"simple:{scope['agent_id']}:{scope['person_id']}:{scope['project_scope']}"
    if shown["handoffs"] or shown["notes"] or shown.get("standing"):
        store.set_meta(f"{prefix}:last_context_delivery_at", datetime.now(timezone.utc).isoformat())
    if shown.get("hour"):
        store.set_meta(f"{prefix}:last_hour_shown", shown["hour"])
    said = set(shown.get("person_words") or [])
    moments = [item["created_at"] for item in person_words or [] if item["id"] in said]
    if moments:
        store.set_meta(f"{prefix}:person_words_shown_at", max(moments))
    told = set(shown.get("person_letgo") or [])
    let_go = [moment for moment in person_letgo or [] if moment in told]
    if let_go:
        store.set_meta(f"{prefix}:person_letgo_shown_at", max(let_go))
    if first_restart_shown:
        store.set_meta(f"{prefix}:verified_at", datetime.now(timezone.utc).isoformat())


def _moment(timestamp: str | None) -> datetime | None:
    """A stored ISO timestamp as an aware datetime, or None when unreadable."""
    try:
        moment = datetime.fromisoformat(timestamp or "")
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _latest_journal(
    store: "EngramStore", scope: dict[str, str], woke: datetime,
) -> dict[str, Any] | None:
    """The newest journal entry of the scope, when it is under three days old
    at the moment of waking (``JOURNAL_LIVE``), else None. A packet must never
    fail because of the journal."""
    try:
        rows = store.journal_entries(**scope, limit=1)
    except Exception:
        return None
    if not rows:
        return None
    moment = _moment(rows[0].get("created_at"))
    if moment is None or woke - moment >= JOURNAL_LIVE:
        return None
    return rows[0]


def _waiting_replies(store: "EngramStore", scope: dict[str, str]) -> list[dict[str, Any]]:
    """The person's replies that have not reached a packet yet, oldest first,
    at most ``REPLIES_SHOWN``. Reads: delivering them is ``_record_delivery``'s."""
    try:
        return store.undelivered_replies(**scope, limit=REPLIES_SHOWN)
    except Exception:
        return []


def _person_words(
    store: "EngramStore", scope: dict[str, str], woke: datetime,
) -> list[dict[str, Any]]:
    """What the person wrote into this memory (``author_kind`` 'person') and
    no wake has shown yet: the active memories in scope written after meta
    ``person_words_shown_at``, or, with none, in the last
    ``PERSON_WORDS_LIVE``. Oldest first, at most ``PERSON_WORDS_SHOWN``. One
    that replaced a memory (``mnemos correct``, the person's) is marked
    ``corrected``. A packet never fails because of them."""
    try:
        prefix = f"simple:{scope['agent_id']}:{scope['person_id']}:{scope['project_scope']}"
        since = store.get_meta(f"{prefix}:person_words_shown_at", None)
        if since is None:
            since = (woke - PERSON_WORDS_LIVE).astimezone(timezone.utc).isoformat()
        rows = store._get_conn().execute(
            """
            SELECT id, content, created_at, lineage FROM engrams
            WHERE owner_agent_id = ? AND person_id = ? AND project_scope = ?
              AND state = 'active' AND author_kind = 'person' AND created_at > ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (scope["agent_id"], scope["person_id"], scope["project_scope"], since,
             PERSON_WORDS_SHOWN),
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "id": row["id"], "content": row["content"], "created_at": row["created_at"],
            "corrected": bool(lineage_supersedes(row["lineage"])),
        }
        for row in rows
    ]


def lineage_supersedes(lineage: Any) -> list[str]:
    """The memories a memory's stored lineage says it replaced through a
    correction (``lineage.supersedes``): none when it says nothing readable."""
    try:
        value = json.loads(lineage) if isinstance(lineage, str) else lineage
    except ValueError:
        return []
    found = value.get("supersedes") if isinstance(value, dict) else None
    return [item for item in found if isinstance(item, str)] if isinstance(found, list) else []


def _person_letgo(store: "EngramStore", scope: dict[str, str]) -> list[str]:
    """When the person let memories of this scope go (``mnemos forget``,
    archive reason ``FORGOTTEN_BY_PERSON``) that no wake has said yet: those
    archived after meta ``person_letgo_shown_at``, or every one when none has
    been said, since none existed before the person could. Only the times,
    oldest first: their words went with them. An agent's forget never counts.
    A packet never fails because of them."""
    from ..store.sqlite_store import FORGOTTEN_BY_PERSON

    try:
        prefix = f"simple:{scope['agent_id']}:{scope['person_id']}:{scope['project_scope']}"
        since = store.get_meta(f"{prefix}:person_letgo_shown_at", None) or ""
        rows = store._get_conn().execute(
            """
            SELECT a.archived_at FROM archive a JOIN engrams e ON e.id = a.id
            WHERE e.owner_agent_id = ? AND e.person_id = ? AND e.project_scope = ?
              AND e.state = 'archived' AND a.archive_reason = ? AND a.archived_at > ?
            ORDER BY a.archived_at ASC
            """,
            (scope["agent_id"], scope["person_id"], scope["project_scope"],
             FORGOTTEN_BY_PERSON, since),
        ).fetchall()
    except Exception:
        return []
    return [row[0] for row in rows]


def first_restart(
    store: "EngramStore",
    scope: dict[str, str],
    reader_session: str,
    session_counter: int | None,
) -> str | None:
    """The first capture's words, when this wake is the first to cross a
    restart since it: its note's content, the first ``_FIRST_RESTART_CHARS``
    characters on one line, cut at a sentence boundary. None when meta
    ``verified_at`` is set, when meta ``first_capture`` is missing or doesn't
    parse, when its note isn't active in scope, or when this wake isn't a
    later session than the capture: by the harness session when the capture
    recorded one and the reader has one, else by the runtime's session count.
    Read anew from the live note, never from a copy, so a forgotten first
    note is never said. Never fails a packet."""
    try:
        prefix = f"simple:{scope['agent_id']}:{scope['person_id']}:{scope['project_scope']}"
        if store.get_meta(f"{prefix}:verified_at", None) is not None:
            return None
        raw = store.get_meta(f"{prefix}:first_capture", None)
        if raw is None:
            return None
        payload = json.loads(raw)
        note_id = payload["note_id"]
        first_session = int(payload["session"])
        captured_in = clean_session_id(payload.get("harness_session"))
        reader = clean_session_id(reader_session)
        if captured_in and reader:
            later = captured_in != reader
        else:
            later = session_counter is not None and session_counter > first_session
        if not later:
            return None
        note = store.get_hypomnema_entry(note_id, **scope, active_only=True)
        if note is None:
            return None
        words = cut_at_sentence(note.get("content") or "", _FIRST_RESTART_CHARS)[0]
    except Exception:
        return None
    return words or None


def _changing(
    store: "EngramStore", scope: dict[str, str], owner: str,
) -> list[dict[str, Any]]:
    """What has been changing in the reader: the newest ``CHANGING_SHOWN`` impact
    lines its own line wrote (``owner`` is the reader, else the resident), newest
    first, each said once (a lesson and the memory it came from say the same
    words). Unsigned lines never count. A packet never fails because of them."""
    items: list[dict[str, Any]] = []
    try:
        rows = store._get_conn().execute(
            """
            SELECT id, impact, author_model, created_at FROM engrams
            WHERE owner_agent_id = ? AND person_id = ? AND project_scope = ?
              AND state = 'active' AND author_kind = 'agent' AND impact_source = 'agent'
              AND trim(impact) != '' AND standing = 0
            ORDER BY created_at DESC
            """,
            (scope["agent_id"], scope["person_id"], scope["project_scope"]),
        )
        newest = []
        for row in rows:
            if same_mind(row["author_model"], owner):
                newest.append(row)
                if len(newest) == CHANGING_SHOWN:
                    break
    except Exception:
        return []
    said: set[str] = set()
    for row in newest:
        impact = row["impact"].strip()
        if impact in said:
            continue
        said.add(impact)
        items.append({"id": row["id"], "text": row["impact"], "created_at": row["created_at"]})
    return items


def _returning(
    store: "EngramStore", scope: dict[str, str], agent_id: str, owner: str,
) -> list[dict[str, Any]]:
    """What the reader keeps coming back to: the ideas the noticer found (meta
    ``ideas_returning``), until one is held. An idea is held once half or more
    of its memories support an active belief the reader's line signed. One an
    open question asks about is left out while it is open: the question shows
    it already. At most ``RETURNING_SHOWN``; none when the meta is missing or
    unreadable."""
    try:
        entries = json.loads(store.get_meta(
            f"simple:{scope['agent_id']}:{scope['person_id']}:{scope['project_scope']}"
            ":ideas_returning",
            "",
        ) or "")
        held: set[str] = set()
        for belief in store.get_beliefs(agent_id, active_only=True):
            if same_mind(belief.author_model, owner):
                held.update(belief.supporting_engram_ids or [])
        asking = _open_evidence(store, scope)
        kept = []
        for entry in entries:
            ids = [str(engram_id) for engram_id in entry["ids"]]
            if 2 * sum(engram_id in held for engram_id in ids) >= len(ids):
                continue
            if any(2 * len(asked.intersection(ids)) > len(ids) for asked in asking):
                continue
            kept.append({"ids": ids, "days": int(entry["days"]), "quote": str(entry["quote"])})
    except Exception:
        return []
    return kept[:RETURNING_SHOWN]


# As the noticer writes it (``simple_runtime._EVIDENCE_MARKER``).
_EVIDENCE = re.compile(r"\[evidence:([A-Za-z0-9_,]+)\]")


def _open_evidence(store: "EngramStore", scope: dict[str, str]) -> list[set[str]]:
    """The memory ids each open evidence question names: an unanswered belief
    question with ``[evidence:…]`` that hasn't expired or been put too often,
    on a memory not archived (the noticer's own test for an open ask)."""
    rows = store._get_conn().execute(
        "SELECT q.prompt FROM reflection_queue q JOIN engrams e ON e.id = q.target_id "
        "WHERE q.agent_id = ? AND q.person_id = ? AND q.project_scope = ? "
        "AND q.kind = 'belief' AND q.answered_at IS NULL "
        "AND (q.expires_at IS NULL OR q.expires_at > ?) AND instr(q.prompt, '[evidence:') > 0 "
        "AND e.state != 'archived' AND q.surfaced_count < ?",
        (scope["agent_id"], scope["person_id"], scope["project_scope"],
         datetime.now(timezone.utc).isoformat(), store.MAX_SURFACINGS),
    ).fetchall()
    return [
        set(marker.group(1).split(","))
        for row in rows for marker in _EVIDENCE.finditer(row["prompt"])
    ]


def _latest_hour(
    store: "EngramStore", scope: dict[str, str], owner: str, woke: datetime,
) -> dict[str, Any] | None:
    """The reader's newest quiet hour since the last packet was delivered: a
    done hour on the live store, run by the reader's line, that ended after the
    last delivery (with none recorded, in the last ``HOUR_LIVE``) and after
    the hour a wake last showed (meta ``last_hour_shown``): each hour shows
    once. Its ``first_line`` is the first line of the first journal entry it
    wrote that this scope holds, or ``""``, and ``journal_id`` that entry's id.
    None otherwise, and on any error."""
    # Imported here, not at the top: the packet doesn't load the hours' runner.
    from ..life import hours_dir

    try:
        path = hours_dir(scope["agent_id"]) / "hours.jsonl"
        if not path.exists():
            return None
        prefix = f"simple:{scope['agent_id']}:{scope['person_id']}:{scope['project_scope']}"
        since = _moment(store.get_meta(f"{prefix}:last_context_delivery_at", None))
        last_shown = _moment(store.get_meta(f"{prefix}:last_hour_shown", None))
        latest: tuple[datetime, dict[str, Any]] | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("status") != "done" or record.get("store") != "live":
                continue
            if not same_mind(record.get("model"), owner):
                continue
            ended = _moment(record.get("ended_at"))
            if ended is None:
                continue
            if since is not None and ended <= since:
                continue
            if since is None and woke - ended >= HOUR_LIVE:
                continue
            if last_shown is not None and ended <= last_shown:
                continue
            if latest is None or ended > latest[0]:
                latest = (ended, record)
        if latest is None:
            return None
        record = latest[1]
        entries = {row["id"]: row for row in store.journal_entries(**scope)}
        first_line = journal_id = ""
        for entry_id in record.get("journal_ids") or []:
            if entry_id in entries:
                first_line = _first_line(entries[entry_id].get("text") or "")
                journal_id = entry_id
                break
        return {
            "ended_at": record["ended_at"], "kind": record.get("kind"),
            "first_line": first_line, "journal_id": journal_id,
        }
    except Exception:
        return None


def _graph_recall(
    store: "EngramStore", query: str, scope: dict[str, str], max_engrams: int,
) -> list[RetrievalResult]:
    """Graph recall for ``query``. Finding changes nothing: the caller
    reinforces only what it goes on to show."""
    retriever = ReactiveRetriever(store)
    results = retriever.retrieve(
        cue=query,
        **scope,
        max_results=max_engrams,
        emotional_state=store.get_latest_emotional_state(scope["agent_id"]),
        reconsolidate_results=False,
    )
    # A defensive scope check, although retrieval filters before traversal.
    return [
        result for result in results
        if store.engram_visible_in_scope(result.engram.id, **scope)
    ]


def _date(timestamp: str | None) -> str:
    try:
        return datetime.fromisoformat(timestamp or "").date().isoformat()
    except (TypeError, ValueError):
        return "undated"


def _age_text(timestamp: str | None) -> str:
    try:
        moment = datetime.fromisoformat(timestamp or "")
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - moment).total_seconds()))
    except (TypeError, ValueError):
        return "at an unknown time"
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _serialize_belief(belief: Any) -> dict[str, Any]:
    return {
        "id": belief.id,
        "content": belief.content,
        "confidence": belief.confidence,
        "domain": belief.domain,
    }


def _serialize_retrieval_result(result: RetrievalResult) -> dict[str, Any]:
    engram = result.engram
    display = engram.impact or engram.content
    if len(display) > 240:
        display = display[:237] + "..."
    return {
        "id": engram.id,
        "display": display,
        "content": engram.content,
        "impact": engram.impact,
        "kind": engram.kind,
        "score": result.score,
        "confidence": engram.source.confidence,
        "retrieval_path": result.retrieval_path,
    }
