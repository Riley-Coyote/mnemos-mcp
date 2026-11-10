"""Hermes MemoryProvider adapter backed by the Mnemos runtime.

The provider reads for the agent (its memory at the start of a session, and
what bears on each message before the turn), keeps the memory's upkeep, and
keeps in Mnemos what the agent itself writes into Hermes's built-in memory.
It writes nothing in the agent's place: the agent writes its memory with its
own tools, in its own words. They are the tools every other agent has, by the
same names, since what it wakes with and is asked names them. Until 0.4.1 it
copied turns, distilled sessions, recorded delegations and copied SOUL.md in as
identity, each in the agent's name (see ``hermes_auto_written`` in the store,
which labels those a tool's).
"""

from __future__ import annotations

import atexit
import contextvars
import functools
import json
import logging
import os
import re
import sqlite3
import threading
import time
import weakref
from dataclasses import replace
from pathlib import Path
from typing import Any

from ... import llm
from ...simple_runtime import RECALL_RESULTS, MnemosRuntime, format_health_card
from ...store.embedding_index import _LOCAL_EXTRA_HINT as _MEANING_BY_PIP
from ...simple_tools import (
    MAX_CAPTURE_CHARS,
    MAX_CONTEXT_CHARS,
    MAX_HANDOFF_CHARS,
    MAX_ID_CHARS,
    MAX_JOURNAL_CHARS,
    MAX_MOOD_CHARS,
    MAX_NOTE_CHARS,
    MAX_QUERY_CHARS,
    MAX_RECALL_RESULTS,
    MAX_REFLECTION_CHARS,
    SERVER_INSTRUCTIONS,
    limit_output,
    text_arg,
)
from .scope import (
    HermesMnemosConfig,
    HermesScope,
    SettingsUnreadable,
    _as_bool,
    conversation_id,
    default_hermes_home,
    derive_hermes_scope,
    memory_file,
    read_settings,
    running_for_home,
    save_hermes_mnemos_config,
    settle_config_home,
)
from .tools import TOOL_SCHEMAS

try:  # POSIX only: Windows has no such limit to raise.
    import resource as _resource
except ImportError:  # pragma: no cover - Windows only
    _resource = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# One tag of the fence Hermes puts around what a memory provider adds to a
# message, opening or closing. Read a little more loosely than Hermes writes it
# (its agent/memory_context.py): any case, and spaces inside the brackets.
_CONTEXT_TAG_RE = re.compile(r"<\s*(/\s*)?memory-context\s*>", re.IGNORECASE)
# The headings the provider opens what it adds with, alone on a line, and those it used
# to. Words about recall, the agent's or the person's, are theirs.
_MNEMOS_CONTEXT_RE = re.compile(
    r"^[ \t]*#[ \t]*Mnemos(?: Recall| Identity Continuity| continuity packet"
    r"|: from memory, maybe bearing on this message)[ \t]*$[\s\S]*",
    re.IGNORECASE | re.MULTILINE,
)
# What comes with each message, in the words every agent's cue has. It isn't a search:
# headed "recall", it read as one, and an agent asked to check its memory took it for the
# answer, and said it had nothing about what was in the machine's shared memory.
_CUE_HEADING = "# Mnemos: from memory, maybe bearing on this message"
_CUE_NOTE = (
    "What came up by itself, from your own memory, not a search. mnemos_recall searches, "
    "and reaches the machine's shared memory too."
)


# The rules every agent's server gives it, with the first as it is here: the
# provider has woken it already, and it has no tool for that.
_RULE_ONE = (
    "1. Before answering the first substantive message, call mnemos_context, unless "
    'you woke with your memory (a session-start hook\'s "## waking up").'
)
_RULES_HERE = SERVER_INSTRUCTIONS.replace(
    _RULE_ONE,
    "1. You woke with your memory: it is below. What may bear on each message comes to "
    "you with that message, but only what came up by itself: to look for something, use "
    "mnemos_recall.",
)
_THIS_AGENT = (
    "Each conversation (a chat, or a topic in one) keeps its own mnemos_handoff note and "
    "wakes to it first. Hermes' own memory (MEMORY.md, USER.md) stays on beside this one, "
    "and what you write there is kept here too."
)
# What a run nobody is in is told, in place of the rules for a conversation:
# Hermes's scheduled jobs (cron), and any other run it says isn't the primary
# one. Hermes asks a memory provider to write nothing by itself there. The
# agent's own tools still work: a job can be the agent's quiet hour, where
# what it keeps is the point.
_RULES_UNATTENDED = (
    "Mnemos is your long-term memory. This is {run}, with nobody in it, so it isn't a "
    "conversation. {read} What may bear on the task comes with it, and mnemos_recall searches "
    "for more. "
    "Leave no handoff or note for this run by habit: a handoff says where a conversation left "
    "off, and this isn't one. Your memory's tools work here as anywhere, for what the task "
    "itself asks you to keep: sign what you write with signed_as, your exact model id.\n\n"
    "Never narrate the machinery: don't mention tools, databases, scopes, engrams or memory "
    "ids in what you report."
)
_READ_NOT_WOKEN = "You woke with a short read of your memory, below, and reading it recorded nothing."
_NOTHING_TO_READ = "Your memory has nothing to wake with yet."
_UNATTENDED_RUNS = {"cron": "a scheduled run", "subagent": "a subagent's run", "flush": "a memory flush"}
# How long the page stays, as it is here. The tool's own words are the MCP
# server's, whose page lasts as long as its session does.
_PAGE_LASTS_A_SESSION = re.compile(r"until\s+this\s+session\s+ends")
_PAGE_LASTS_HERE = (
    "while this conversation goes on and while they're using it, and closes about ten "
    "minutes after both end"
)
# Where a first session tells the agent to offer the page. The page is served on
# 127.0.0.1 of the computer Hermes runs on: right in Hermes's terminal, and no
# use to someone in a chat on their phone. Anywhere but the terminal the agent
# is told where it opens instead, and to offer it only when asked.
_PAGE_OFFERED = re.compile(
    r", and that they can see all of it(?P<notes>, and answer your notes,)? on a page you'll open for "
    r"them whenever they ask\."
)


# What the page shows in Hermes's terminal besides this agent's memory: the
# other agents' kept beside it, only to read. Said there, and only there.
_ONLY_THEY_WRITE = "Only they write there."
_PAGE_READS_OTHERS = (
    "\nIn Hermes's terminal it also shows them the memory of the other\n"
    "agents kept beside yours in ~/.mnemos, only to read."
)
_PAGE_ALSO_THE_OTHERS = (
    " In this terminal the page also lets them read the memory of the other agents Mnemos "
    "keeps on this computer, without changing it."
)


def _page_where_it_opens(found: re.Match[str]) -> str:
    notes = " and answer your notes" if found.group("notes") else ""
    return (
        f". The page where they can see all of it{notes} opens in a browser on the computer Hermes "
        "runs on. Don't offer it unless they ask, and if they ask, tell them it opens there."
    )
# How to turn meaning search on, where pip is the way and where it isn't: a
# Mnemos that Hermes's catalog installed is in an environment Hermes builds
# and rebuilds, with nothing for the person to pip install into.
_MEANING_HERE = "inside Hermes, meaning search is a setting: the plugin's README says which"
_ONE_NOTE_EACH = (
    "\n\nHere each conversation (a chat, or a topic in one) is one session, however many "
    "times it starts over: this replaces only the note this conversation left before, and "
    "it is what this conversation wakes to next time."
)

# Each conversation holds a few open files on the store, more with meaning search,
# and Hermes runs up to 128 at once. A Mac starts a process with room for 256, and
# Hermes before August 2026 didn't ask for more: 30 topics with meaning search ran
# out, and took Hermes' own files down with them. The number is Hermes' own.
_OPEN_FILES_WANTED = 4096
_open_files_seen = False

# The page each memory in this process has open (mnemos_page): every conversation
# on a gateway has its own provider, and they share it. Each conversation that
# opened it holds it until it ends. Once none does, the page closes when nobody
# has asked it for anything for this long (an open page asks every few seconds,
# so one somebody is reading stays). Until 0.6.7 it was served for as long as
# Hermes ran, which for a gateway is days.
_PAGE_LEFT_ALONE_SECONDS = 600.0
_pages: dict[tuple[Any, ...], Any] = {}
_page_holders: dict[tuple[Any, ...], weakref.WeakSet[Any]] = {}
_pages_lock = threading.Lock()


def _watch_page(key: tuple[Any, ...], page: Any) -> None:
    """Watch a page from the moment it opens, in a thread of its own, and close
    it once no conversation holds it and it has gone unasked for
    ``_PAGE_LEFT_ALONE_SECONDS``.

    From the moment it opens, not from the last conversation's goodbye. A
    conversation Hermes dropped without ending it says no goodbye, and its page
    would be served for as long as Hermes ran."""

    def watch() -> None:
        while True:
            time.sleep(min(15.0, max(0.05, _PAGE_LEFT_ALONE_SECONDS / 4)))
            with _pages_lock:
                if _pages.get(key) is not page:
                    return
                if _page_holders.get(key):
                    continue
                if time.monotonic() - page.last_asked < _PAGE_LEFT_ALONE_SECONDS:
                    continue
                del _pages[key]
                _page_holders.pop(key, None)
            try:
                page.shutdown()
                page.server_close()
            except Exception:
                logger.debug("Mnemos couldn't close its page", exc_info=True)
            return

    threading.Thread(target=watch, name="mnemos-page-close", daemon=True).start()


# The read a backup keeps open on each memory it named, by the memory's path,
# and for how long in a process that lives on (Hermes's dashboard). ``hermes
# backup`` ends long before, and takes the read with it.
_BACKUP_HOLD_SECONDS = 3600.0
_backup_holds: dict[str, tuple[sqlite3.Connection, threading.Timer]] = {}
_backup_holds_lock = threading.Lock()
_backup_exit_seen = False


# Tables every Mnemos memory has had since its first release: a file without
# them is some other program's, whatever it is called.
_A_MEMORYS_TABLES = frozenset({"engrams", "connections", "versions", "meta"})


def _not_another_programs(exc: sqlite3.Error) -> bool:
    """Whether SQLite opened the file and found it isn't a database at all."""
    code = getattr(exc, "sqlite_errorcode", None)  # Python 3.11 on
    if code is not None:
        return code == getattr(sqlite3, "SQLITE_NOTADB", 26)
    return "not a database" in str(exc)


def _what_a_backup_finds(store: Path) -> tuple[str, str]:
    """Whether ``store`` is a Mnemos memory: ("memory", ""), ("other", why) for
    a file that opens and isn't one, or ("unchecked", why) for one that
    couldn't be looked into (its permissions, no file left to open it with, a
    lock). It is opened read-only and only its list of tables is read:
    nothing in it changes."""
    try:
        conn = sqlite3.connect(f"{store.as_uri()}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error as exc:
        if _not_another_programs(exc):
            return "other", f"it isn't a database ({exc})"
        return "unchecked", f"it couldn't be checked ({exc})"
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    except sqlite3.Error as exc:
        if _not_another_programs(exc):
            return "other", f"it isn't a database ({exc})"
        return "unchecked", f"it couldn't be checked ({exc})"
    finally:
        conn.close()
    missing = sorted(_A_MEMORYS_TABLES - tables)
    if missing:
        return "other", f"it hasn't Mnemos's own tables ({', '.join(missing)} missing)"
    return "memory", ""


def _hold_still_for_a_backup(store: Path) -> None:
    """Fold a memory's log into its file, and keep the file as it then is while
    a backup copies it.

    Hermes asks what to take, archives its own folder, and copies a provider's
    files last, as they stand: in a big home, minutes after it asked. A read
    left open keeps the memory still for it. In SQLite's write-ahead mode
    nothing is written back into the file under an open read; what a
    conversation saves meanwhile waits in the log, and nobody waits on the
    read. So the file Hermes copies is whole whenever it gets to it, and the
    log beside it, with what was saved since, is still there to copy. Without
    the read, the file changed under the copy whenever SQLite folded its log
    back, and a conversation that ended first took the log, already named,
    with it, which Hermes reports as an incomplete backup.

    A memory that isn't in write-ahead mode is left alone: there a read left
    open would keep every save waiting."""
    global _backup_exit_seen
    key = str(store)
    _let_go_of_backup(key)  # one read for a memory: the last backup's is done with
    conn = sqlite3.connect(key, timeout=2.0, isolation_level=None, check_same_thread=False)
    try:
        if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
            conn.close()
            return
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        conn.execute("BEGIN")
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error:
        conn.close()
        raise
    timer = threading.Timer(_BACKUP_HOLD_SECONDS, _let_go_of_backup, args=(key, conn))
    timer.name = "mnemos-backup-hold"
    timer.daemon = True
    with _backup_holds_lock:
        displaced = _backup_holds.get(key)  # another backup's, asked for at the same moment
        _backup_holds[key] = (conn, timer)
        if displaced is not None:
            displaced[1].cancel()
            try:
                displaced[0].close()
            except sqlite3.Error:
                logger.debug("Mnemos couldn't close the read a backup left open", exc_info=True)
        if not _backup_exit_seen:
            _backup_exit_seen = True
            atexit.register(_let_go_of_backups)
    timer.start()


def _let_go_of_backup(key: str, held: sqlite3.Connection | None = None) -> None:
    """Close the read a backup left open on a memory (``held``: only if it is
    still that one), and end the wait that would have closed it. SQLite then
    folds the log in as it always does."""
    with _backup_holds_lock:
        hold = _backup_holds.get(key)
        if hold is None or (held is not None and hold[0] is not held):
            return
        del _backup_holds[key]
    conn, timer = hold
    timer.cancel()  # asked again, each hold would otherwise leave its wait behind for the hour
    try:
        conn.close()
    except sqlite3.Error:
        logger.debug("Mnemos couldn't close the read a backup left open", exc_info=True)


def _let_go_of_backups() -> None:
    for key in list(_backup_holds):
        _let_go_of_backup(key)


def _hermes_answers_for(home: Path):
    """Hermes's answer for another profile than the one speaking, to a name of
    Mnemos's: Hermes builds that profile's own reader, as it does for a task it
    runs for the profile, and is asked through it. Hermes reads the profile's
    ``.env``; the plugin opens none. A Hermes without such a reader answers
    nothing, and that profile goes by its ``mnemos.json`` alone."""
    try:
        from agent.secret_scope import build_profile_secret_scope, get_secret, reset_secret_scope, set_secret_scope
    except ImportError:
        return lambda name: ""
    try:
        secrets = build_profile_secret_scope(home)
    except Exception:
        # Hermes couldn't build it (a file of an administrator's it can't
        # read, a secret source that failed): the profile goes by its
        # mnemos.json alone, and isn't left out of the backup.
        logger.warning("Hermes couldn't answer for the profile in %s; Mnemos goes by its mnemos.json.", home,
                       exc_info=True)
        return lambda name: ""

    def bound(name: str) -> Any:
        token = set_secret_scope(secrets, profile_home=str(home))
        try:
            return get_secret(name)
        finally:
            reset_secret_scope(token)

    def ask(name: str) -> str:
        try:
            return str(contextvars.copy_context().run(bound, name) or "").strip()
        except Exception:
            logger.warning("Hermes couldn't answer for the profile in %s; Mnemos goes by its mnemos.json.", home,
                           exc_info=True)
            return ""

    return ask


def _memories_of_other_profiles(root: Path, here: Path) -> list[Path]:
    """Where the other profiles of this Hermes keep their memories: the memory
    each one's home opens (``memory_file``), with Hermes's answers for that
    profile. A profile that has had no session names none, and has no memory
    yet, or one inside Hermes's folder, which is in the backup already."""
    homes = [root]
    try:
        homes.extend(sorted(path for path in (root / "profiles").iterdir() if path.is_dir()))
    except OSError:
        pass
    found: list[Path] = []
    for home in homes:
        try:
            if home.resolve() == here:
                continue
            read_settings(home)
            found.append(Path(memory_file(home, HermesMnemosConfig.load(home), _hermes_answers_for(home))).expanduser())
        except SettingsUnreadable as exc:
            logger.warning("Mnemos left a profile out of the backup. %s", exc)
        except Exception:
            logger.debug("Mnemos couldn't read a profile's settings for a backup", exc_info=True)
    return found


def _make_room_for_files() -> None:
    """Ask once per process for room to hold the files many conversations open.
    Never lowers the limit, and never fails a start."""
    global _open_files_seen
    if _open_files_seen or _resource is None:
        return
    _open_files_seen = True
    try:
        soft, hard = _resource.getrlimit(_resource.RLIMIT_NOFILE)
        if soft == _resource.RLIM_INFINITY or soft >= _OPEN_FILES_WANTED:
            return
        wanted = _OPEN_FILES_WANTED if hard == _resource.RLIM_INFINITY else min(_OPEN_FILES_WANTED, hard)
        if wanted > soft:
            _resource.setrlimit(_resource.RLIMIT_NOFILE, (wanted, hard))
    except (ValueError, OSError):
        logger.debug("Mnemos couldn't raise the open-file limit", exc_info=True)


def _take_hermes_secrets() -> None:
    """Every setting and key Mnemos reads inside Hermes comes through Hermes, and
    no file is read for one: no .env, no other tool's config. Hermes's plugin
    rules ask it, and only Hermes knows which profile is speaking when a gateway
    serves several. A Hermes from before secret scopes hands them out through its
    own environment."""
    try:
        from agent.secret_scope import get_secret
    except ImportError:
        get_secret = os.environ.get
    llm.take_secrets_from(get_secret)


# The settings that name a memory. Until 0.6.7 they were read from the
# environment Hermes was started in; now Hermes is asked for them, for the
# profile that is speaking, and a gateway serving profiles answers from the
# profile's own .env only. Someone who set them where Hermes starts got a new
# memory for the profile after the upgrade, and nothing said why.
_NAMES_OF_A_MEMORY = ("MNEMOS_DB_PATH", "MNEMOS_AGENT_ID", "MNEMOS_PERSON_ID", "MNEMOS_PROJECT_SCOPE")
_told_of_names_passed_over: set[str] = set()  # the homes told so, in this process
# The homes whose settings can't be read that Hermes has been told of once, in
# this process: from then on nothing is raised to it where it would say so again
# as a warning (a start, the system prompt, the end of a session).
_told_settings_unreadable: set[str] = set()
_told_lock = threading.Lock()


def _say_names_passed_over(home: Path, db_path: str) -> None:
    """Say once for each home, in Hermes's log, which of those names the
    environment Hermes was started in holds that Hermes didn't give this
    profile: the names only, since a value may be another profile's. Which
    memory is opened doesn't change: taken from there, one profile's settings
    would name another's memory."""
    from ...simple_scope import named_in_the_environment

    if not llm.host_secrets_active():
        return
    passed_over = [
        name for name in _NAMES_OF_A_MEMORY
        if os.environ.get(name, "").strip() and not named_in_the_environment(name)
    ]
    if not passed_over:
        return
    key = str(Path(home).expanduser())
    with _told_lock:
        if key in _told_of_names_passed_over:
            return
        _told_of_names_passed_over.add(key)
    logger.warning(
        "Mnemos: %s %s set where Hermes was started, and Hermes doesn't give %s to this profile, so "
        "Mnemos doesn't use %s. This profile's memory is %s. To go on with the memory %s named, see "
        "\"Upgrading from 0.6.6\" in the Mnemos plugin's README.",
        ", ".join(passed_over), "is" if len(passed_over) == 1 else "are",
        "it" if len(passed_over) == 1 else "them", "it" if len(passed_over) == 1 else "them",
        str(Path(db_path).expanduser()), "it" if len(passed_over) == 1 else "they",
    )


def _configured_model(hermes_home: Path) -> str:
    """The model Hermes starts a session with, as its config.yaml names it
    (``model.default``, ``model.model``, or ``model`` as a plain name), or ``""``.
    Hermes 0.23.0 tells a memory provider no model, so this is the one it has."""
    try:
        import yaml  # type: ignore

        raw = yaml.safe_load((Path(hermes_home) / "config.yaml").read_text(encoding="utf-8"))
    except Exception:
        return ""
    model = raw.get("model") if isinstance(raw, dict) else None
    if isinstance(model, dict):
        model = model.get("default") or model.get("model")
    return model.strip() if isinstance(model, str) else ""


def _whole(text: str) -> str:
    """``text`` with any half of a character pair (a lone surrogate) replaced.
    A model's JSON can carry one, and UTF-8 has no way to write it: SQLite
    refused the memory with a codec error, and an answer holding one can't be
    sent on."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return text


def _answer(payload: dict[str, Any]) -> str:
    """A tool's answer, in the words that were kept. Until 0.6.7 everything
    outside ASCII was written as an escape (\\uXXXX): a memory in Chinese or
    Japanese came back five times its size, past the limit its text was cut to,
    for a model to read letter by letter."""
    return _whole(json.dumps(payload, ensure_ascii=False, default=str))


def _json_ok(**payload: Any) -> str:
    payload.setdefault("ok", True)
    return _answer(payload)


def _json_error(message: str, **payload: Any) -> str:
    payload.update({"ok": False, "error": message})
    return _answer(payload)


def _words(args: dict[str, Any], name: str) -> str:
    """An argument as the agent wrote it."""
    return _whole(str(args.get(name) or ""))


def _cleaned(args: dict[str, Any], name: str) -> str:
    """An argument the agent wrote, without any span Hermes fenced into it."""
    return _own_words(args.get(name))


def _without_fenced_context(value: str) -> str:
    """``value`` without each ``<memory-context>…</memory-context>`` span: from
    an opening tag to the next closing one, in one pass over the tags.

    Until 0.6.7 one pattern did this, ``<[^>]*memory-context[^>]*>`` to a
    closing tag, and it tried every ``<`` in the text against all that
    followed: a pasted page of markup, 51,000 characters with many ``<``, took
    seconds, on every message, while Hermes waited for its recall (Nous's
    review of the catalog entry, 2026-11-09)."""
    kept: list[str] = []
    at, opened = 0, -1
    for tag in _CONTEXT_TAG_RE.finditer(value):
        closing = tag.group(1) is not None
        if opened < 0 and not closing:
            opened = tag.start()
        elif opened >= 0 and closing:
            kept.append(value[at:opened])
            at, opened = tag.end(), -1
    if not kept:
        return value
    kept.append(value[at:])
    return "".join(kept)


def _no_fence_tags(rows: str) -> str:
    """What recall brought, with every fence tag taken out of every row: the
    tags, never the words. Hermes strips from an opening tag to the next
    closing one before it fences the recall, so a tag left in one memory could
    pair with one in another and cut out every memory between them. A tag is
    whatever Hermes's own patterns take for one (``</?\\s*memory-context\\s*>``,
    agent/memory_context.py), and a space before the slash too. Taken out until
    none is left: once, ``<memory-<memory-context>context>`` was a whole tag again."""
    while True:
        rest = _CONTEXT_TAG_RE.sub("", rows)
        if rest == rows:
            return rows
        rows = rest


def _own_words(text: Any) -> str:
    """What the agent wrote, whole, but for any span Hermes fenced into it.

    The provider's headings stay: a note about its own memory can be headed
    the way recall once was. Until 0.6.7 they came off here as they come off a
    message (``_clean_text``), with all that followed: a capture, a correction
    or a line of MEMORY.md was kept up to the heading and no further, and the
    save said ok."""
    return _without_fenced_context(_whole(str(text or ""))).strip()


def _clean_text(text: Any) -> str:
    """A message Hermes hands over, without what was added to it: any fenced
    span, and from one of the provider's own headings to the end. Only what is
    searched for is shorter for it; nothing is kept from here."""
    return _MNEMOS_CONTEXT_RE.sub("", _own_words(text)).strip()


def _looked_up_by(text: str) -> str:
    """What a message is looked up by: itself, or its start and its end when
    it is longer than the recall tool takes. A long message is mostly what was
    pasted into it, with the person's own words before it or after. Every word
    of it used to be searched before the turn began (on 1,500 memories, 2.4
    seconds for 100,000 characters), and with a provider chosen for meaning
    search all of it went there."""
    if len(text) <= MAX_QUERY_CHARS:
        return text
    half = MAX_QUERY_CHARS // 2 - 1
    # Whole words, where there are words: a word cut in two is another word.
    start = text[:half].rsplit(None, 1)[0]
    end = text[-half:].split(None, 1)[-1]
    return f"{start}\n{end}"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n\n[Mnemos context truncated to fit configured budget]\n\n"
    keep = max(0, limit - len(marker))
    head = int(keep * 0.72)
    tail = keep - head
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def _importance_value(value: Any, fallback: str | float = "auto") -> str | float:
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value or "").strip().lower()
    if raw in {"low", "minor", "auto", "high", "important", "critical"}:
        return raw
    return fallback


# How a memory mirrored from Hermes's built-in memory begins its context.
_MIRROR_MARK = "Mirrored from Hermes built-in"

def _one_at_a_time(method):
    """One provider, one SQLite connection, and Hermes calls from several threads:
    a message's prefetch on one, a tool call or the turn's end on another. On one
    connection two at once can stop the whole process, every topic with it, with
    no error: one waits for SQLite holding Python's lock, the other inside SQLite
    for Python's lock, to run the connection's trace callback."""

    @functools.wraps(method)
    def locked(self, *args, **kwargs):
        home = self._scope.hermes_home if self._scope else self._started_with.get("hermes_home")
        with self._lock, running_for_home(home):
            return method(self, *args, **kwargs)

    return locked


class MnemosMemoryProviderCore:
    """Hermes-compatible provider implementation without importing Hermes."""

    # Whether Hermes's plugin catalog installed this Mnemos, in an environment
    # Hermes rebuilds and removes (hermes-plugin/__init__.py says so).
    _from_catalog = False

    def __init__(self, config: HermesMnemosConfig | None = None):
        self._config = config
        self._scope: HermesScope | None = None
        self._runtime: MnemosRuntime | None = None
        self._session_id = ""
        # What Hermes said when it started this conversation (initialize's
        # keywords): whose home, which chat, what kind of run. A call that
        # comes after shutdown starts it again as the same one.
        self._started_with: dict[str, Any] = {}
        self._conversation_follows_session = True
        # The session this provider is at and the conversation it has there. On
        # the command line a compression goes on as the same conversation under
        # a new session id, which the id alone can't say when it starts again.
        self._conversation_under: tuple[str, str] = ("", "")
        # What prefetch last recalled for each session: the query, the store's
        # revision then (_store_revision), the context, and how many rows it
        # holds. Any write, here or by another process, changes the revision.
        self._prefetch_cache: dict[str, tuple[str, tuple[int, int] | None, str, int]] = {}
        # How many rows the last prefetch brought (recall_status); 0 for none.
        self._last_recalled = 0
        self._writes_enabled = True
        self._turn_count = 0
        self._host_model = ""  # the model this runtime was told signs
        self._named_model = ""  # the one Hermes itself last named, at a start or a turn
        self._page_key: tuple[Any, ...] | None = None  # the page this conversation holds open
        self._lock = threading.RLock()
        self._stopped: SettingsUnreadable | None = None  # why this home doesn't start, if it doesn't

    @property
    def name(self) -> str:
        return "mnemos"

    @property
    def scope(self) -> HermesScope:
        self._ensure_runtime()
        assert self._scope is not None
        return self._scope

    def is_available(self) -> bool:
        return True

    @_one_at_a_time
    def initialize(self, session_id: str, **kwargs: Any) -> None:
        _make_room_for_files()
        _take_hermes_secrets()
        self._started_with = dict(kwargs)
        # Started again (twice, or by a call after shutdown), on a new
        # connection: it counts the store's revision from the start, so what
        # was recalled before isn't served by it, and it has been told no model.
        self._prefetch_cache.clear()
        self._host_model = ""
        if self._runtime is not None:
            # Started twice: the first one's store and index aren't left open.
            self._runtime.close()
            self._runtime = None
        hermes_home = kwargs.get("hermes_home")
        if self._config is None:
            # Settings the person edited and that can't be read stop it here,
            # before anything is settled or written: never a new memory.
            told = str(Path(hermes_home or default_hermes_home()).expanduser().resolve())
            try:
                read_settings(hermes_home or default_hermes_home())
            except SettingsUnreadable as exc:
                self._stopped = exc
                with _told_lock:
                    first = told not in _told_settings_unreadable
                    _told_settings_unreadable.add(told)
                if first:
                    raise  # Hermes says it, once, as a warning
                logger.debug("Mnemos isn't starting in %s: its settings can't be read (said at the first start).", told)
                return
            self._stopped = None
            with _told_lock:
                _told_settings_unreadable.discard(told)  # mended: if it breaks again, it is said again
            settle_config_home(hermes_home)
            from .installer import settle_one_memory

            settle_one_memory(hermes_home)
        config = self._config or HermesMnemosConfig.load(hermes_home)
        self._scope = derive_hermes_scope(
            session_id=session_id,
            hermes_home=hermes_home,
            config=config,
            runtime_context=kwargs,
        )
        self._config = config
        _say_names_passed_over(self._scope.hermes_home, self._scope.db_path)
        self._session_id = self._scope.session_id
        self._conversation_follows_session = not str(kwargs.get("gateway_session_key") or "").strip()
        at_session, conversation = self._conversation_under
        if self._conversation_follows_session and conversation and at_session == self._session_id:
            # Started again at the session it was at: the conversation it was.
            self._scope = replace(self._scope, conversation=conversation)
        self._conversation_under = (self._session_id, self._scope.conversation)
        self._writes_enabled = self._scope.agent_context in {"", "primary"}
        self._runtime = MnemosRuntime(
            db_path=self._scope.db_path,
            agent_id=self._scope.agent_id,
            person_id=self._scope.person_id,
            project_scope=self._scope.project_scope,
            use_dedicated_model=config.deep_maintenance,
            harness="hermes",
            conversation=self._scope.conversation,
            host_manages_install=self._from_catalog,
            # The folder the person works in, as Hermes names it; "" for a chat
            # with none. Never this process's own: Hermes's gateway runs every
            # chat in Hermes's install folder.
            workdir=str(kwargs.get("cwd") or ""),
            # In a run nobody is in, a save is followed by no upkeep either.
            upkeep_waits=not self._writes_enabled,
        )
        # A Hermes that names each turn's model (on_turn_start) signs with it from
        # the first turn; one that names none (0.23.0) starts the session with
        # the model in its config.yaml, so that one signs until a turn says.
        # Started again, the model Hermes last named still signs. Told before
        # the store is opened: a start the store was too busy for goes on at
        # the next call, and what that keeps is signed too.
        self._hear_model(kwargs.get("model"))
        self._signs_with(self._named_model or _configured_model(self._scope.hermes_home))
        Path(self._scope.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # Opened, not read: a wake counts what it shows as shown, so one built
        # here would spend what shows once on a read no model sees.
        self._runtime._ensure_init()

    @_one_at_a_time
    def system_prompt_block(self) -> str:
        try:
            self._ensure_runtime()
        except SettingsUnreadable:
            logger.debug("No Mnemos in this system prompt: its settings can't be read.")
            return ""
        assert self._runtime is not None
        assert self._config is not None
        if self._writes_enabled:
            try:
                packet = self._runtime.context(max_results=min(4, self._config.max_recall_results))
            except sqlite3.OperationalError:
                packet = self._read_without_waking()
            assert self._scope is not None
            if self._scope.platform != "cli":
                packet = _PAGE_OFFERED.sub(_page_where_it_opens, packet)
            else:
                packet = _PAGE_OFFERED.sub(lambda found: found.group(0) + _PAGE_ALSO_THE_OTHERS, packet)
            body = f"# Mnemos Identity Continuity\n{_RULES_HERE}\n\n{_THIS_AGENT}\n\n{packet}"
        else:
            # Read, not woken: a wake counts a session and spends what shows
            # once (a question, the person's note) on a run nobody is in.
            assert self._scope is not None
            run = _UNATTENDED_RUNS.get(self._scope.agent_context, "a background run")
            try:
                packet = self._runtime.glance()
            except sqlite3.OperationalError:
                packet = self._read_without_waking()
            rules = _RULES_UNATTENDED.format(run=run, read=_READ_NOT_WOKEN if packet else _NOTHING_TO_READ)
            body = f"# Mnemos Identity Continuity\n{rules}" + (f"\n\n{packet}" if packet else "")
        wake_limit = self._config.max_wake_chars
        return _truncate(body, wake_limit) if wake_limit else body

    def _read_without_waking(self) -> str:
        """What a session starts on when its wake couldn't write: where things
        stand, read and not counted (``glance``, as a run nobody is in reads).

        A wake counts a session and spends what shows once. With another
        process deep in one long write, past the wait the store gives, it
        raised, and Hermes builds its prompt once: the whole session ran with
        no Mnemos in it, though every read would have answered. A store that
        couldn't even be opened to write (that records this code's version) is
        opened to read."""
        assert self._runtime is not None and self._scope is not None
        logger.debug("Mnemos's store was busy past its wait: this session starts on a read", exc_info=True)
        if self._runtime._store is not None:
            return self._runtime.glance()
        reader = MnemosRuntime(
            db_path=self._scope.db_path,
            agent_id=self._scope.agent_id,
            person_id=self._scope.person_id,
            project_scope=self._scope.project_scope,
            read_only=True,
            harness="hermes",
            conversation=self._scope.conversation,
            workdir=str(self._started_with.get("cwd") or ""),
        )
        try:
            return reader.glance()
        finally:
            reader.close()

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        # Before the lock: while this waits its turn, the last message's count
        # is no longer the last prefetch's.
        self._last_recalled = 0
        return self._prefetch(query, session_id=session_id)

    @_one_at_a_time
    def _prefetch(self, query: str, *, session_id: str = "") -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        assert self._config is not None
        if not self._config.auto_recall:
            return ""
        clean = _looked_up_by(_clean_text(query))
        if not clean:
            return ""
        cache_key = session_id or self._session_id or self.scope.session_id
        cached = self._prefetch_cache.get(cache_key)
        revision = self._store_revision()
        if cached and cached[0] == clean and revision is not None and cached[1] == revision:
            self._last_recalled = cached[3]
            return cached[2]
        # What comes up by itself is a use of it, in a conversation. In a run
        # nobody is in it is only read: nothing strengthened, linked or woken.
        recalled = self._runtime._recall_own(
            clean, max_results=self._config.max_recall_results, reinforce=self._writes_enabled,
        )
        if recalled.startswith("No relevant continuity found"):
            return ""
        # Recall heads its answer with the query it was asked. Here that is the
        # person's message, which the model has: what was found goes on, and
        # none of the message. Cut at the heading's first line, a message of
        # several lines came back from its second line on, as if remembered,
        # and a long one left no room for what was.
        heading = f"Mnemos recall for: {clean}"
        rows = recalled[len(heading):].lstrip("\n") if recalled.startswith(heading) else recalled
        context = _truncate(
            f"{_CUE_HEADING}\n{_CUE_NOTE}\n\n{self._said_here(_no_fence_tags(rows))}", self._config.max_context_chars,
        )
        brought = self._last_recalled = max(1, self._runtime.last_recall_rows)
        after = self._store_revision()
        # Cached only when no other connection committed during the recall:
        # what it read may be older than that commit (a forget, a correction),
        # and would be served again under the newer revision. This connection's
        # own writes, the recall's bookkeeping, are read after it, so they
        # count as no change.
        if revision is not None and after is not None and after[0] == revision[0]:
            self._prefetch_cache[cache_key] = (clean, after, context, brought)
        else:
            self._prefetch_cache.pop(cache_key, None)
        return context

    def recall_status(self) -> Any:
        """What the last prefetch brought, for the line Hermes shows the person
        when memory came with their message ("🧠 Mnemos — recalled 3
        memories"). None when it brought nothing, and on a Hermes from before
        it had the line."""
        brought = self._last_recalled
        if brought <= 0:
            return None
        try:
            from agent.memory_provider import RecallStatus
        except ImportError:
            return None
        return RecallStatus(provider_label="Mnemos", count=brought)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Nothing to warm. Recall here is on this machine and quick, so each
        message gets its own when it arrives (``prefetch``).

        Until 0.6.7 this recalled the finished turn's text again. The next
        message is another query, so it warmed nothing, and it held this
        conversation's lock while it ran: the next turn's start waited behind
        it, and with Gemini chosen for meaning search the turn's words went
        there a second time."""

    def _store_revision(self) -> tuple[int, int] | None:
        """The store's revision as this provider's connection sees it: SQLite's
        data_version, which moves when another connection commits, and the
        connection's own total_changes, which moves with every write made
        through it (a review note, upkeep, a correction), so no write path
        has to remember to clear the cache. A cached recall from an older
        revision may hold what was since forgotten or corrected. None when it
        can't be read: then nothing cached is trusted."""
        try:
            self._runtime._ensure_init()
            conn = self._runtime._store._get_conn()
            return int(conn.execute("PRAGMA data_version").fetchone()[0]), conn.total_changes
        except Exception:
            return None

    @_one_at_a_time
    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        """A finished turn writes nothing: what it held worth keeping, the
        agent keeps itself, in its own words."""

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        def here(tool: dict[str, Any]) -> dict[str, Any]:
            if tool["name"] == "mnemos_handoff":
                return {**tool, "description": tool["description"] + _ONE_NOTE_EACH}
            if tool["name"] == "mnemos_page":
                said = _PAGE_LASTS_A_SESSION.sub(_PAGE_LASTS_HERE, tool["description"])
                if self._scope is not None and self._scope.platform == "cli":
                    said = said.replace(_ONLY_THEY_WRITE, _ONLY_THEY_WRITE + _PAGE_READS_OTHERS)
                return {**tool, "description": said}
            return tool

        return [
            here(tool) for tool in TOOL_SCHEMAS
            # A run nobody is in isn't offered the page: there is no one to open it for.
            if self._writes_enabled or tool["name"] != "mnemos_page"
        ]

    def _said_here(self, text: str) -> str:
        """What a tool says, where it names a command that isn't one here."""
        return text.replace(_MEANING_BY_PIP, _MEANING_HERE) if self._from_catalog else text

    @_one_at_a_time
    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        tool = _TOOLS.get(tool_name)
        if tool is None:
            return _json_error(f"Unknown Mnemos tool: {tool_name}")
        try:
            self._ensure_runtime()
            if tool_name == "mnemos_page" and not self._writes_enabled:
                return _json_error(
                    "The page is for the person to read while you talk, and nobody is in this run: "
                    "by the time they looked, it would be closed. Open it in a conversation.",
                    tool=tool_name,
                )
            return _json_ok(result=limit_output(self._said_here(tool(self, args or {}))))
        except Exception as exc:
            logger.debug("Mnemos tool %s failed", tool_name, exc_info=True)
            return _json_error(str(exc), tool=tool_name)

    @_one_at_a_time
    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        self._turn_count = int(turn_number or self._turn_count + 1)
        self._ensure_runtime()
        self._hear_model(kwargs.get("model"))
        if not self._writes_enabled:
            return
        assert self._config is not None
        assert self._runtime is not None
        interval = self._config.maintenance_interval
        if interval and self._turn_count > 0 and self._turn_count % interval == 0:
            self._runtime.maintain(auto=True)
            self._prefetch_cache.clear()  # upkeep can archive what was recalled

    @_one_at_a_time
    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        """The memory's upkeep, and nothing written from the session."""
        if not self._writes_enabled:
            return
        try:
            self._ensure_runtime()
        except SettingsUnreadable:
            logger.debug("No upkeep at the end of this session: its settings can't be read.")
            return
        assert self._runtime is not None
        self._runtime.maintain(auto=True)
        self._prefetch_cache.clear()  # upkeep can archive what was recalled

    @_one_at_a_time
    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs: Any,
    ) -> None:
        self._session_id = str(new_session_id or "")
        if reset:
            self._prefetch_cache.clear()
        # A gateway conversation is its key, which a switch doesn't move. On
        # the command line it is the session, except that a compression
        # continues the same conversation under a new id.
        conversation = self._conversation_under[1]
        if self._conversation_follows_session and kwargs.get("reason") != "compression":
            conversation = conversation_id(session_id=self._session_id)
            if self._scope is not None and self._runtime is not None:
                self._scope = replace(self._scope, conversation=conversation)
                self._runtime.conversation = conversation
        self._conversation_under = (self._session_id, conversation)

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        """Compression writes nothing, and adds nothing to the summary."""
        return ""

    @_one_at_a_time
    def on_delegation(self, task: str, result: str, *, child_session_id: str = "", **kwargs: Any) -> None:
        """A delegation writes nothing: its result is in the conversation,
        for the agent to keep if it matters."""

    @_one_at_a_time
    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """What the agent itself writes into Hermes's built-in memory, kept in
        Mnemos too: its own words, by its own act."""
        self._ensure_runtime()
        assert self._config is not None
        assert self._runtime is not None
        if not self._writes_enabled or not self._config.mirror_builtin_memory:
            return
        action = (action or "").lower()
        clean = _own_words(content)
        meta = metadata or {}
        context = (
            f"{_MIRROR_MARK} {target} memory. "
            f"Metadata: {json.dumps(meta, sort_keys=True, default=str)}"
        )
        if action in {"replace", "remove", "delete", "forget"}:
            # The entry replaced or removed, as Hermes names it: the whole of
            # it (previous_content, newer Hermes) or a piece of it (old_text,
            # which Hermes requires to match one entry). A remove may carry
            # no content at all, only these.
            predecessors = self._mirrored_entries(
                target,
                whole=_own_words(meta.get("previous_content")),
                piece=_own_words(meta.get("old_text")) or (clean if action != "replace" else ""),
            )
            if action != "replace":
                # Forgotten only when the mirrored entries that match are one
                # entry; otherwise nothing here is retired on a guess.
                if predecessors:
                    self._prefetch_cache.clear()
                for predecessor in predecessors:
                    self._runtime.correct("", target_id=predecessor, action="forget")
                return
            if predecessors and clean:
                # Corrected to the new words, written as a mirrored capture is,
                # so a later replace or remove finds it; the same line kept
                # twice before 0.6.7 is let go of with it.
                self._prefetch_cache.clear()
                first, *again = predecessors
                for predecessor in again:
                    self._runtime.correct("", target_id=predecessor, action="forget")
                self._runtime.correct(f"{clean}\n\nContext: {context}", target_id=first, action="update")
                return
        if action == "add" and clean and self._mirrored_entries(target, whole=clean, exact=True):
            # Hermes answers an add of a line it already holds, word for word,
            # with success, and keeps the line once: so does Mnemos.
            return
        if action in {"add", "replace"} and clean:
            self._capture(clean, context=context, importance="high" if target == "user" else "auto")

    def get_config_schema(self) -> list[dict[str, Any]]:
        """The settings Hermes's dashboard shows for Mnemos. None is needed:
        left empty, each is what the first session settles (``settle_one_memory``).
        No default is given for where the memory is kept: the dashboard fills an
        empty field with its default and saves it, and the one given until 0.6.7
        was the place the memory was kept before it moved to ~/.mnemos."""
        on_or_off = ["true", "false"]
        return [
            {"key": "db_path", "description": (
                "Where this agent's memory is kept, a file on this machine. Left empty: "
                "~/.mnemos/hermes.db, or ~/.mnemos/hermes-<profile>.db for another profile. A home that "
                "already had a memory with this empty goes on with it where it is: mnemos/mnemos.db "
                "in the profile's own folder.")},
            {"key": "agent_id", "description": (
                "The agent's name in its memory. Left empty: hermes, or hermes-<profile>. A home that "
                "already had a memory with this empty goes on as before: the profile's name as Hermes "
                "gives it (default, for the default profile), or hermes.")},
            {"key": "person_id", "description": (
                "Who the agent is with, as its memory names them. Left empty: user, or the person "
                "~/.mnemos/config.json names, written in at the first session. A home that already had a "
                "memory with this empty goes on as before: the person each chat names, or user.")},
            {"key": "project_scope", "description": (
                "Which part of its memory this is. Left empty: global, one memory for everything, or the "
                "project ~/.mnemos/config.json names, written in at the first session. A home that already "
                "had a memory with this empty goes on as before: the chat's name, or the folder Hermes was "
                "started in.")},
            {"key": "auto_recall", "default": "true", "choices": on_or_off, "description": (
                "Bring the few memories that may bear on each message, with the message.")},
            {"key": "deep_maintenance", "default": "false", "choices": on_or_off, "description": (
                "Let Mnemos use a model of its own on the memory. Only with a provider chosen for it "
                "(MNEMOS_LLM_PROVIDER: openrouter, openai or anthropic) and that provider's key. Memory "
                "text then goes to that provider whenever the agent saves or corrects a memory, and "
                "during upkeep. Off: Mnemos uses no model.")},
        ]

    def backup_paths(self) -> list[str]:
        """The memories Mnemos keeps for this Hermes, for ``hermes backup``:
        this profile's, and each other profile's. They are kept outside
        Hermes's own folder (``~/.mnemos``), and a backup takes only that folder
        unless the provider names more. Until 0.6.7 Mnemos named nothing: a
        backup of Hermes left the agent's memory behind, without a word.

        Every profile's, because the backup is of every profile: Hermes
        archives its whole folder, each profile's settings with it, and asks
        the provider of the one profile it was run from what else to take.

        Hermes copies the files as they stand, some while after it asks, and
        puts them back the same way. So what SQLite still holds in a memory's
        write-ahead log is folded into the file first, and the file is then kept
        as it is until the backup is done (``_hold_still_for_a_backup``). The
        log is named too, always: it holds what a conversation saved since, and
        where the backup is restored it replaces whatever log is lying there,
        which the restored file would otherwise be read through. Works on a
        provider that was never started, and writes nothing in any memory. A
        memory kept inside Hermes's folder is in the backup already. The
        machine's shared memory is not named: it is every Mnemos agent's, and a
        restore would put it back over what the others have shared since."""
        # A read is held on every profile's memory, each three files, in a
        # process (`hermes backup`) with the shell's limit: 256 on a Mac.
        _make_room_for_files()
        try:
            _take_hermes_secrets()
            scope = self._scope
            stores: list[Path] = []
            if scope is not None:
                here = Path(scope.hermes_home).expanduser().resolve()
                stores.append(Path(scope.db_path).expanduser())
            else:
                home = default_hermes_home()
                here = home.expanduser().resolve()
                try:
                    if self._config is None:
                        read_settings(home)
                    scope = derive_hermes_scope(
                        hermes_home=home, config=self._config or HermesMnemosConfig.load(home),
                    )
                    stores.append(Path(scope.db_path).expanduser())
                except SettingsUnreadable as exc:
                    # Only this profile's own memory is left out: every other
                    # profile's is still named.
                    logger.warning("Mnemos left this profile's memory out of the backup. %s", exc)
            root = here.parent.parent if here.parent.name == "profiles" else here
            stores.extend(_memories_of_other_profiles(root, here))
        except Exception:
            logger.debug("Mnemos couldn't name its memory for a backup", exc_info=True)
            return []
        named: list[str] = []
        seen: set[Path] = set()
        for store in stores:
            try:
                store = store.resolve()
                if store in seen or not store.is_file() or store.is_relative_to(root):
                    continue
                seen.add(store)
                found, why = _what_a_backup_finds(store)
                if found == "other":
                    # Never named, held or folded in: another program's file.
                    logger.warning("Mnemos left %s out of the backup: %s.", store, why)
                    continue
                if found == "unchecked":
                    # Maybe a memory: named as it is, neither held nor folded
                    # in. Leaving a memory out would be the worse mistake.
                    logger.warning("Mnemos named %s for the backup as it is: %s.", store, why)
                else:
                    try:
                        _hold_still_for_a_backup(store)
                    except sqlite3.Error:
                        logger.debug("Mnemos couldn't hold a memory still for a backup", exc_info=True)
                log = store.with_name(store.name + "-wal")
                named.extend([str(store), *([str(log)] if log.is_file() else [])])
            except Exception:
                logger.debug("Mnemos couldn't name a memory for a backup", exc_info=True)
        return named

    def post_setup(self, hermes_home: str, config: dict[str, Any]) -> None:
        """``hermes memory setup`` with Mnemos chosen: the memory ``mnemos connect
        hermes`` would set up, Mnemos made the provider, and where its memory is.
        Without this, setup would ask six questions and leave the memory named
        after each chat and person (``settle_one_memory``)."""
        from hermes_cli.config import save_config  # the route Hermes's provider guide names

        from .installer import settle_one_memory

        try:
            read_settings(hermes_home)
        except SettingsUnreadable as exc:
            print(f"\n  {exc}\n")
            return
        settle_one_memory(hermes_home)
        memory = config.get("memory")
        if not isinstance(memory, dict):
            memory = config["memory"] = {}
        memory["provider"] = self.name
        save_config(config, merge_existing=True)
        settled = HermesMnemosConfig.load(hermes_home)
        scope = derive_hermes_scope(hermes_home=hermes_home, config=settled)
        store = Path(scope.db_path).expanduser()
        state = "it's new" if not store.exists() else "it's there already"
        print(f"\n  Mnemos is this agent's memory now. The agent is {scope.agent_id!r}, and its memory")
        print(f"  is {store} ({state}). It stays when Mnemos is removed: it's the agent's.")
        print("  Start a new session to wake with it.\n")

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        save_hermes_mnemos_config(hermes_home, values)

    @_one_at_a_time
    def shutdown(self) -> None:
        self._let_go_of_page()
        if self._runtime is not None:
            self._runtime.close()
        self._runtime = None
        self._scope = None
        self._prefetch_cache.clear()

    def _let_go_of_page(self) -> None:
        """This conversation has ended: it no longer holds the page it opened.
        Once none does, the page's watch closes it when it's left alone."""
        key, self._page_key = self._page_key, None
        if key is None:
            return
        with _pages_lock:
            holders = _page_holders.get(key)
            if holders is not None:
                holders.discard(self)

    def _hear_model(self, model: Any) -> None:
        """The model Hermes says it is running signs this conversation's writes,
        unless a write carries its own ``signed_as``. A later Hermes tells at
        every turn, so a switch of model mid-conversation signs from then on.
        Older ones don't tell: the agent signs for itself, as it is asked to."""
        model = str(model or "").strip()
        if model:
            self._named_model = model
            self._signs_with(model)

    def _signs_with(self, model: str) -> None:
        if model and model != self._host_model and self._runtime is not None:
            self._host_model = model
            self._runtime.signs_for_host(model)

    def _tool_capture(self, args: dict[str, Any]) -> str:
        return self._capture(
            text_arg("content", _cleaned(args, "content"), MAX_CAPTURE_CHARS, required=True),
            text_arg("context", _cleaned(args, "context"), MAX_CONTEXT_CHARS),
            _importance_value(args.get("importance")),
            impact=text_arg("impact", _words(args, "impact"), MAX_REFLECTION_CHARS),
            signed_as=text_arg("signed_as", _words(args, "signed_as"), MAX_ID_CHARS),
            standing=_as_bool(args.get("standing"), False),
            shared=_as_bool(args.get("shared"), False),
        )

    def _tool_recall(self, args: dict[str, Any]) -> str:
        standing = _as_bool(args.get("standing"), False)
        options: dict[str, Any] = {}
        if args.get("max_results") is not None:
            options["max_results"] = self._bounded_int(args.get("max_results"))
        return self._runtime.recall(
            text_arg("query", _cleaned(args, "query"), MAX_QUERY_CHARS, required=not standing),
            include_archived=_as_bool(args.get("include_archived"), False),
            standing=standing,
            **options,
        )

    def _tool_correct(self, args: dict[str, Any]) -> str:
        # What prefetch recalled may be what this corrects or forgets.
        self._prefetch_cache.clear()
        return self._runtime.correct(
            correction=text_arg("correction", _cleaned(args, "correction"), MAX_CAPTURE_CHARS),
            target_id=text_arg("target_id", _cleaned(args, "target_id"), MAX_ID_CHARS),
            query=text_arg("query", _cleaned(args, "query"), MAX_QUERY_CHARS),
            action=text_arg("action", _words(args, "action") or "update", 32),
            impact=text_arg("impact", _words(args, "impact"), MAX_REFLECTION_CHARS),
            signed_as=text_arg("signed_as", _words(args, "signed_as"), MAX_ID_CHARS),
        )

    def _tool_handoff(self, args: dict[str, Any]) -> str:
        # Stored exactly as written: no cleaning, unlike a capture.
        return self._runtime.handoff(
            text_arg("text", _words(args, "text"), MAX_HANDOFF_CHARS, required=True),
            signed_as=text_arg("signed_as", _words(args, "signed_as"), MAX_ID_CHARS),
        )

    def _tool_journal(self, args: dict[str, Any]) -> str:
        return self._runtime.journal(
            text_arg("text", _words(args, "text"), MAX_JOURNAL_CHARS),
            signed_as=text_arg("signed_as", _words(args, "signed_as"), MAX_ID_CHARS),
            mood=text_arg("mood", _words(args, "mood"), MAX_MOOD_CHARS),
        )

    def _tool_note(self, args: dict[str, Any]) -> str:
        return self._runtime.note(
            text_arg("text", _words(args, "text"), MAX_NOTE_CHARS, required=True),
            text_arg("kind", _words(args, "kind"), MAX_ID_CHARS),
            signed_as=text_arg("signed_as", _words(args, "signed_as"), MAX_ID_CHARS),
            in_reply_to=text_arg("in_reply_to", _words(args, "in_reply_to"), MAX_ID_CHARS),
        )

    def _tool_reflect(self, args: dict[str, Any]) -> str:
        return self._runtime.reflect(
            target_id=text_arg("target_id", _words(args, "target_id"), MAX_ID_CHARS, required=True),
            text=text_arg("text", _words(args, "text"), MAX_REFLECTION_CHARS, required=True),
            verdict=text_arg("verdict", _words(args, "verdict"), 32),
            signed_as=text_arg("signed_as", _words(args, "signed_as"), MAX_ID_CHARS),
        )

    def _tool_introduce(self, args: dict[str, Any]) -> str:
        return self._runtime.introduce(
            agent_model=text_arg("agent_model", _words(args, "agent_model"), 256, required=True),
            agent_name=text_arg("agent_name", _words(args, "agent_name"), 256),
        )

    def _tool_maintain(self, args: dict[str, Any]) -> str:
        result = self._runtime.maintain(deep=_as_bool(args.get("deep"), False))
        self._prefetch_cache.clear()  # upkeep can archive what was recalled
        return result

    def _tool_health(self, args: dict[str, Any]) -> str:
        return format_health_card(self._runtime.health())

    def _tool_page(self, args: dict[str, Any]) -> str:
        from ...companion.server import open_page

        scope = self.scope
        kwargs = {
            "db_path": scope.db_path,
            "agent_id": scope.agent_id,
            "person_id": scope.person_id,
            "project_scope": scope.project_scope,
        }
        # In Hermes's terminal the page also shows the other agents, only to read.
        # Anywhere else the agent may be a bot handed the link: one page of its own.
        in_terminal = scope.platform == "cli"
        key = (*kwargs.values(), in_terminal)
        with _pages_lock:
            open_already = _pages.get(key)
            said, page = open_page(kwargs, open_already, reads_others=in_terminal)
            if page is not None:
                _pages[key] = page
                _page_holders.setdefault(key, weakref.WeakSet()).add(self)
                self._page_key = key
        if page is not None and page is not open_already:
            _watch_page(key, page)
        return _PAGE_LASTS_A_SESSION.sub(_PAGE_LASTS_HERE, said)

    def _ensure_runtime(self) -> None:
        """A call after shutdown starts the conversation again, as Hermes
        started it. Until 0.6.7 it started with nothing Hermes had said: the
        default home in place of the profile's, a new conversation, and a
        scheduled run taken for a conversation, its automatic writes back on."""
        if self._runtime is not None:
            return
        started = dict(self._started_with)
        if self._named_model:
            started["model"] = self._named_model  # the one a turn named since, if one did
        self.initialize(self._session_id or "mnemos-hermes", **started)
        if self._runtime is None and self._stopped is not None:
            raise SettingsUnreadable(str(self._stopped))

    def _mirrored_entries(self, target: str, *, whole: str = "", piece: str = "", exact: bool = False) -> list[str]:
        """The memories in use here mirrored from this Hermes ``target``
        ("memory" or "user") that are the entry Hermes names: their own words
        (before the mirror's context) equal to ``whole``, or else containing
        ``piece``. Found ignoring case and spacing, as Hermes's own words for
        an entry can differ from what was kept; but several are one entry kept
        more than once only when their words are the same exactly, ends
        trimmed, as Hermes holds them apart otherwise. Among several entries
        the one whose words match exactly is it; failing one, none is: a
        replace or remove then retires nothing on a guess. ``exact``: only
        words the same exactly count at all. A memory mirrored from the other
        target, or one the agent wrote itself, is never it."""
        if not whole and not piece:
            return []
        self._runtime._ensure_init()
        scope = self._runtime.scope
        marker = f"\n\nContext: {_MIRROR_MARK} {target} memory."
        rows = self._runtime._store._get_conn().execute(
            "SELECT id, content FROM engrams WHERE owner_agent_id = ? AND person_id = ? "
            "AND project_scope = ? AND state != 'archived' AND instr(content, ?) > 0",
            (scope.agent_id, scope.person_id, scope.project_scope, marker),
        ).fetchall()

        def words(content: str) -> str:
            return content.split(marker)[0].strip()

        def blind(text: str) -> str:
            return " ".join(text.split()).casefold()

        # Spacing and case are read the same way on both sides: Hermes keeps
        # the entry's own spacing in old_text, and a double space or a line
        # break in it still finds the entry.
        if whole:
            exactly = [r for r in rows if words(r[1]) == whole.strip()]
            found = exactly if exact else [r for r in rows if blind(words(r[1])) == blind(whole)]
        else:
            exactly = [r for r in rows if piece.strip() in words(r[1])]
            found = exactly if exact else [r for r in rows if blind(piece) in blind(words(r[1]))]
        entries = {words(r[1]) for r in found}
        if len(entries) > 1:
            found = exactly
            entries = {words(r[1]) for r in found}
        if len(entries) != 1:
            return []
        return [r[0] for r in found]

    def _capture(self, content: str, context: str = "", importance: str | float = "auto", **options: Any) -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        self._prefetch_cache.clear()
        return self._runtime.capture(content, context=context, importance=importance, **options)

    @staticmethod
    def _bounded_int(value: Any) -> int:
        """Recall's rows as asked, within what the MCP server allows; a number
        that can't be read gets recall's default, not its most, which is three
        times the reading."""
        try:
            return max(1, min(MAX_RECALL_RESULTS, int(value)))
        except (TypeError, ValueError):
            return RECALL_RESULTS


_TOOLS = {
    "mnemos_capture": MnemosMemoryProviderCore._tool_capture,
    "mnemos_recall": MnemosMemoryProviderCore._tool_recall,
    "mnemos_correct": MnemosMemoryProviderCore._tool_correct,
    "mnemos_handoff": MnemosMemoryProviderCore._tool_handoff,
    "mnemos_journal": MnemosMemoryProviderCore._tool_journal,
    "mnemos_note": MnemosMemoryProviderCore._tool_note,
    "mnemos_reflect": MnemosMemoryProviderCore._tool_reflect,
    "mnemos_introduce": MnemosMemoryProviderCore._tool_introduce,
    "mnemos_maintain": MnemosMemoryProviderCore._tool_maintain,
    "mnemos_health": MnemosMemoryProviderCore._tool_health,
    "mnemos_page": MnemosMemoryProviderCore._tool_page,
}


@functools.lru_cache(maxsize=None)
def build_memory_provider_class(memory_provider_base: type, *, from_catalog: bool = False) -> type:
    """Build a Hermes ``MemoryProvider`` subclass without hard-importing Hermes.
    One class per base: Hermes asks again for every agent it builds.
    ``from_catalog``: Hermes's plugin catalog installed this Mnemos."""

    class MnemosMemoryProvider(MnemosMemoryProviderCore, memory_provider_base):  # type: ignore[misc, valid-type]
        _from_catalog = from_catalog

    MnemosMemoryProvider.__name__ = "MnemosMemoryProvider"
    MnemosMemoryProvider.__qualname__ = "MnemosMemoryProvider"
    MnemosMemoryProvider.__module__ = __name__
    return MnemosMemoryProvider
