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

import functools
import json
import logging
import os
import re
import threading
import time
import weakref
from dataclasses import replace
from pathlib import Path
from typing import Any

from ... import llm
from ...simple_runtime import RECALL_RESULTS, MnemosRuntime, format_health_card
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
    _as_bool,
    conversation_id,
    derive_hermes_scope,
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
# message, opening or closing, in Hermes's own bounded shape (its
# agent/memory_context.py).
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
_pages_closing: set[tuple[Any, ...]] = set()
_pages_lock = threading.Lock()


def _close_page_when_left_alone(key: tuple[Any, ...], page: Any) -> None:
    """Watch a page no conversation holds any more, in a thread of its own, and
    close it once it has gone unasked for ``_PAGE_LEFT_ALONE_SECONDS``. A
    conversation that asks for the page again takes it back, and the watch ends."""

    def watch() -> None:
        while True:
            time.sleep(min(15.0, max(0.05, _PAGE_LEFT_ALONE_SECONDS / 4)))
            with _pages_lock:
                held = bool(_page_holders.get(key))
                gone = _pages.get(key) is not page
                left_alone = time.monotonic() - page.last_asked >= _PAGE_LEFT_ALONE_SECONDS
                if held or gone or left_alone:
                    _pages_closing.discard(key)
                if held or gone:
                    return
                if left_alone:
                    del _pages[key]
                    _page_holders.pop(key, None)
            if left_alone:
                try:
                    page.shutdown()
                    page.server_close()
                except Exception:
                    logger.debug("Mnemos couldn't close its page", exc_info=True)
                return

    with _pages_lock:
        if key in _pages_closing:
            return
        _pages_closing.add(key)
    threading.Thread(target=watch, name="mnemos-page-close", daemon=True).start()


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


def _json_ok(**payload: Any) -> str:
    payload.setdefault("ok", True)
    return json.dumps(payload, ensure_ascii=True, default=str)


def _json_error(message: str, **payload: Any) -> str:
    payload.update({"ok": False, "error": message})
    return json.dumps(payload, ensure_ascii=True, default=str)


def _words(args: dict[str, Any], name: str) -> str:
    """An argument as the agent wrote it."""
    return str(args.get(name) or "")


def _cleaned(args: dict[str, Any], name: str) -> str:
    """An argument without any of the memory context Hermes wraps around a message."""
    return _clean_text(args.get(name))


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


def _clean_text(text: Any) -> str:
    value = _without_fenced_context(str(text or ""))
    value = _MNEMOS_CONTEXT_RE.sub("", value)
    return value.strip()


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
    a turn's queued prefetch on one, the next message on another. On one
    connection two at once can stop the whole process, every topic with it, with
    no error: one waits for SQLite holding Python's lock, the other inside SQLite
    for Python's lock, to run the connection's trace callback."""

    @functools.wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock, running_for_home(self._scope.hermes_home if self._scope else None):
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
        self._conversation_follows_session = True
        # What prefetch last recalled for each session: the query, the store's
        # revision then (_store_revision), and the context. Any write, here
        # or by another process, changes the revision.
        self._prefetch_cache: dict[str, tuple[str, tuple[int, int] | None, str]] = {}
        self._writes_enabled = True
        self._turn_count = 0
        self._host_model = ""
        self._page_key: tuple[Any, ...] | None = None  # the page this conversation holds open
        self._lock = threading.RLock()

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
        hermes_home = kwargs.get("hermes_home")
        if self._config is None:
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
        self._session_id = self._scope.session_id
        self._conversation_follows_session = not str(kwargs.get("gateway_session_key") or "").strip()
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
        )
        Path(self._scope.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # Opened, not read: a wake counts what it shows as shown, so one built
        # here would spend what shows once on a read no model sees.
        self._runtime._ensure_init()
        # A Hermes that names each turn's model (on_turn_start) signs with it from
        # the first turn; one that names none (0.23.0) starts the session with
        # the model in its config.yaml, so that one signs until a turn says.
        self._hear_model(kwargs.get("model") or _configured_model(self._scope.hermes_home))

    @_one_at_a_time
    def system_prompt_block(self) -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        assert self._config is not None
        if self._writes_enabled:
            packet = self._runtime.context(max_results=min(4, self._config.max_recall_results))
            body = f"# Mnemos Identity Continuity\n{_RULES_HERE}\n\n{_THIS_AGENT}\n\n{packet}"
        else:
            # Read, not woken: a wake counts a session and spends what shows
            # once (a question, the person's note) on a run nobody is in.
            assert self._scope is not None
            run = _UNATTENDED_RUNS.get(self._scope.agent_context, "a background run")
            packet = self._runtime.glance()
            rules = _RULES_UNATTENDED.format(run=run, read=_READ_NOT_WOKEN if packet else _NOTHING_TO_READ)
            body = f"# Mnemos Identity Continuity\n{rules}" + (f"\n\n{packet}" if packet else "")
        wake_limit = self._config.max_wake_chars
        return _truncate(body, wake_limit) if wake_limit else body

    @_one_at_a_time
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        assert self._config is not None
        if not self._config.auto_recall:
            return ""
        clean = _clean_text(query)
        if not clean:
            return ""
        cache_key = session_id or self._session_id or self.scope.session_id
        cached = self._prefetch_cache.get(cache_key)
        revision = self._store_revision()
        if cached and cached[0] == clean and revision is not None and cached[1] == revision:
            return cached[2]
        # What comes up by itself is a use of it, in a conversation. In a run
        # nobody is in it is only read: nothing strengthened, linked or woken.
        recalled = self._runtime._recall_own(
            clean, max_results=self._config.max_recall_results, reinforce=self._writes_enabled,
        )
        if "No relevant continuity found" in recalled:
            return ""
        rows = recalled.split("\n", 1)[1].lstrip("\n") if recalled.startswith("Mnemos recall for:") else recalled
        context = _truncate(f"{_CUE_HEADING}\n{_CUE_NOTE}\n\n{rows}", self._config.max_context_chars)
        after = self._store_revision()
        # Cached only when no other connection committed during the recall:
        # what it read may be older than that commit (a forget, a correction),
        # and would be served again under the newer revision. This connection's
        # own writes, the recall's bookkeeping, are read after it, so they
        # count as no change.
        if revision is not None and after is not None and after[0] == revision[0]:
            self._prefetch_cache[cache_key] = (clean, after, context)
        else:
            self._prefetch_cache.pop(cache_key, None)
        return context

    @_one_at_a_time
    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        self.prefetch(query, session_id=session_id)

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
        return [
            {**tool, "description": tool["description"] + _ONE_NOTE_EACH}
            if tool["name"] == "mnemos_handoff" else tool
            for tool in TOOL_SCHEMAS
            # A run nobody is in isn't offered the page: there is no one to open it for.
            if self._writes_enabled or tool["name"] != "mnemos_page"
        ]

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
            return _json_ok(result=limit_output(tool(self, args or {})))
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
        self._ensure_runtime()
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
        if (
            self._conversation_follows_session
            and kwargs.get("reason") != "compression"
            and self._scope is not None
            and self._runtime is not None
        ):
            conversation = conversation_id(session_id=self._session_id)
            self._scope = replace(self._scope, conversation=conversation)
            self._runtime.conversation = conversation

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
        clean = _clean_text(content)
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
            predecessor = self._mirrored_entry(
                target,
                whole=_clean_text(meta.get("previous_content")),
                piece=_clean_text(meta.get("old_text")) or (clean if action != "replace" else ""),
            )
            if action != "replace":
                # Forgotten only when exactly one mirrored entry is it;
                # otherwise nothing here is retired on a guess.
                if predecessor:
                    self._prefetch_cache.clear()
                    self._runtime.correct("", target_id=predecessor, action="forget")
                return
            if predecessor and clean:
                # Corrected to the new words, written as a mirrored capture is,
                # so a later replace or remove finds it.
                self._prefetch_cache.clear()
                self._runtime.correct(f"{clean}\n\nContext: {context}", target_id=predecessor, action="update")
                return
        if action in {"add", "replace"} and clean:
            self._capture(clean, context=context, importance="high" if target == "user" else "auto")

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [
            {"key": "db_path", "description": "Mnemos identity-continuity SQLite path", "default": "$HERMES_HOME/mnemos/mnemos.db"},
            {"key": "agent_id", "description": "Optional fixed Mnemos agent identity scope"},
            {"key": "person_id", "description": "Optional fixed person/user identity scope"},
            {"key": "project_scope", "description": "Optional fixed project continuity scope"},
            {"key": "auto_recall", "description": "Auto-inject scoped identity continuity", "default": "true", "choices": ["true", "false"]},
            {"key": "deep_maintenance", "description": "Enable optional model-assisted Mnemos maintenance when model keys exist", "default": "false", "choices": ["true", "false"]},
        ]

    def post_setup(self, hermes_home: str, config: dict[str, Any]) -> None:
        """``hermes memory setup`` with Mnemos chosen: the memory ``mnemos connect
        hermes`` would set up, Mnemos made the provider, and where its memory is.
        Without this, setup would ask six questions and leave the memory named
        after each chat and person (``settle_one_memory``)."""
        from hermes_cli.config import save_config  # the route Hermes's provider guide names

        from .installer import settle_one_memory

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
        The last one to let go leaves the page to close when it's left alone."""
        key, self._page_key = self._page_key, None
        if key is None:
            return
        with _pages_lock:
            holders = _page_holders.get(key)
            if holders is not None:
                holders.discard(self)
            page = _pages.get(key)
            if page is None or holders:
                return
        _close_page_when_left_alone(key, page)

    def _hear_model(self, model: Any) -> None:
        """The model Hermes says it is running signs this conversation's writes,
        unless a write carries its own ``signed_as``. A later Hermes tells at
        every turn, so a switch of model mid-conversation signs from then on.
        Older ones don't tell: the agent signs for itself, as it is asked to."""
        model = str(model or "").strip()
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
        key = tuple(kwargs.values())
        with _pages_lock:
            said, page = open_page(kwargs, _pages.get(key))
            if page is not None:
                _pages[key] = page
                _page_holders.setdefault(key, weakref.WeakSet()).add(self)
                self._page_key = key
        return said

    def _ensure_runtime(self) -> None:
        if self._runtime is not None:
            return
        self.initialize(self._session_id or "mnemos-hermes")

    def _mirrored_entry(self, target: str, *, whole: str = "", piece: str = "") -> str | None:
        """The one memory in use here mirrored from this Hermes ``target``
        ("memory" or "user") that is the entry Hermes names, or None: its own
        words (before the mirror's context) equal to ``whole``, or else
        containing ``piece``, ignoring case. None too when more than one
        matches: a replace or remove then retires nothing on a guess. A
        memory mirrored from the other target, or one the agent wrote
        itself, is never it."""
        if not whole and not piece:
            return None
        self._runtime._ensure_init()
        scope = self._runtime.scope
        marker = f"\n\nContext: {_MIRROR_MARK} {target} memory."
        rows = self._runtime._store._get_conn().execute(
            "SELECT id, content FROM engrams WHERE owner_agent_id = ? AND person_id = ? "
            "AND project_scope = ? AND state != 'archived' AND instr(content, ?) > 0",
            (scope.agent_id, scope.person_id, scope.project_scope, marker),
        ).fetchall()

        def own(content: str) -> str:
            return " ".join(content.split(marker)[0].split()).casefold()

        # Spacing and case are read the same way on both sides: Hermes keeps
        # the entry's own spacing in old_text, and a double space or a line
        # break in it is still the same entry.
        if whole:
            matches = [r[0] for r in rows if own(r[1]) == " ".join(whole.split()).casefold()]
        else:
            matches = [r[0] for r in rows if " ".join(piece.split()).casefold() in own(r[1])]
        return matches[0] if len(matches) == 1 else None

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
