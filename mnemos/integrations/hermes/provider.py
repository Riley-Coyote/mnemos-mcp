"""Hermes MemoryProvider adapter backed by the Mnemos runtime.

The provider reads for the agent (its memory at the start of a session, and
what bears on each message before the turn), keeps the memory's upkeep, and
keeps in Mnemos what the agent itself writes into Hermes's built-in memory.
It writes nothing in the agent's place: the agent writes its memory with its
own tools, in its own words. Until 0.4.1 it copied turns, distilled sessions,
recorded delegations and copied SOUL.md in as identity, each in the agent's
name (see ``hermes_auto_written`` in the store, which labels those a tool's).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from ...simple_runtime import MnemosRuntime
from .scope import (
    HermesMnemosConfig,
    HermesScope,
    conversation_id,
    derive_hermes_scope,
    save_hermes_mnemos_config,
)

logger = logging.getLogger(__name__)

_CONTEXT_TAG_RE = re.compile(r"<[^>]*memory-context[^>]*>[\s\S]*?</[^>]*memory-context>", re.IGNORECASE)
_MNEMOS_CONTEXT_RE = re.compile(r"#?\s*Mnemos (Recall|Identity Continuity|continuity packet)[\s\S]*", re.IGNORECASE)


IDENTITY_CAPTURE_SCHEMA = {
    "name": "mnemos_identity_capture",
    "description": (
        "Persist scoped identity-continuity notes in Mnemos. Use for stable preferences, "
        "self-model facts, corrections, session handoffs, and project decisions that should "
        "survive future Hermes sessions. Set review=true for uncertain claims."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The durable memory or continuity note to persist."},
            "context": {"type": "string", "description": "Optional provenance or session context."},
            "importance": {
                "description": "Importance as low, auto, high, critical, or a 0-1 numeric score.",
                "anyOf": [{"type": "string"}, {"type": "number"}],
            },
            "review": {
                "type": "boolean",
                "description": "Queue as uncertain instead of promoting as high-confidence continuity.",
            },
        },
        "required": ["content"],
    },
}

IDENTITY_RECALL_SCHEMA = {
    "name": "mnemos_identity_recall",
    "description": (
        "Recall scoped Mnemos identity continuity for the active Hermes agent, person, and project. "
        "Use when an answer depends on prior preferences, corrections, self-model, project decisions, "
        "or handoff context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Recall query."},
            "max_results": {"type": "integer", "description": "Maximum results to return."},
            "include_graph": {"type": "boolean", "description": "Include structured identity graph summary data."},
        },
        "required": ["query"],
    },
}

IDENTITY_CORRECT_SCHEMA = {
    "name": "mnemos_identity_correct",
    "description": (
        "Correct, supersede, archive, or forget stale Mnemos identity continuity. Use when the user "
        "updates a remembered preference, self-model fact, decision, or correction."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "correction": {"type": "string", "description": "Replacement continuity text."},
            "target_id": {"type": "string", "description": "Known Mnemos memory or continuity note ID."},
            "query": {"type": "string", "description": "Search phrase for the stale memory if no ID is known."},
            "action": {
                "type": "string",
                "enum": ["update", "revise", "supersede", "replace", "archive", "forget", "remove"],
            },
        },
    },
}

IDENTITY_REPORT_SCHEMA = {
    "name": "mnemos_identity_report",
    "description": (
        "Inspect scoped Mnemos identity continuity. Produces a compact context packet, identity graph, "
        "review inbox, status, or maintenance report for the active scope."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["context", "graph", "inbox", "status", "maintain"],
                "description": "Report kind.",
            },
            "query": {"type": "string", "description": "Optional query for context reports."},
            "max_results": {"type": "integer", "description": "Maximum results or graph nodes."},
            "deep": {"type": "boolean", "description": "Request optional model-assisted maintenance if configured."},
        },
        "required": ["kind"],
    },
}

IDENTITY_HANDOFF_SCHEMA = {
    "name": "mnemos_identity_handoff",
    "description": (
        "Leave your own note on where this conversation stands, in first person. Use after "
        "meaningful progress or a changed plan, while work remains, and before pausing or "
        "changing direction; not after every turn. Each conversation (a chat, or a topic in "
        "one) keeps its own note: this replaces only the one this conversation left before, "
        "and it is what this conversation wakes to next time, so write about this "
        "conversation's work, not the others'. It is stored exactly as written."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The note, in your own words."},
            "signed_as": {"type": "string", "description": "Your exact model id, when you know it."},
        },
        "required": ["text"],
    },
}


def _json_ok(**payload: Any) -> str:
    payload.setdefault("ok", True)
    return json.dumps(payload, ensure_ascii=True, default=str)


def _json_error(message: str, **payload: Any) -> str:
    payload.update({"ok": False, "error": message})
    return json.dumps(payload, ensure_ascii=True, default=str)


def _clean_text(text: Any) -> str:
    value = str(text or "")
    value = _CONTEXT_TAG_RE.sub("", value)
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


def _domain_for(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ("identity", "who i am", "who you are", "selfhood", "soul.md")):
        return "identity"
    if any(marker in lowered for marker in ("always", "preference", "prefers", "principle", "boundary")):
        return "foundational"
    if any(marker in lowered for marker in ("again", "recurring", "usually", "often")):
        return "recurring"
    if any(marker in lowered for marker in ("roadmap", "long term", "long-term", "future", "arc")):
        return "long-arc"
    if any(marker in lowered for marker in ("current", "today", "temporary", "session")):
        return "situational"
    return "topical"


def _tags_for(text: str, *extra: str) -> list[str]:
    lowered = text.lower()
    tags = {"hermes", "continuity", *[tag for tag in extra if tag]}
    markers = {
        "preference": ("prefer", "preference", "likes", "wants"),
        "decision": ("decided", "decision", "going with", "will use"),
        "project": ("project", "repo", "workspace", "build"),
        "identity": ("identity", "agent", "self", "soul.md", "who i am"),
        "correction": ("correction", "wrong", "forget", "stale"),
        "handoff": ("handoff", "delegated", "subagent"),
    }
    for label, terms in markers.items():
        if any(term in lowered for term in terms):
            tags.add(label)
    return sorted(tags)



# How a memory mirrored from Hermes's built-in memory begins its context.
_MIRROR_MARK = "Mirrored from Hermes built-in"

class MnemosMemoryProviderCore:
    """Hermes-compatible provider implementation without importing Hermes."""

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

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        hermes_home = kwargs.get("hermes_home")
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
        )
        Path(self._scope.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # Opened, not read: a wake counts what it shows as shown, so one built
        # here would spend what shows once on a read no model sees.
        self._runtime._ensure_init()

    def system_prompt_block(self) -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        assert self._config is not None
        packet = self._runtime.context(max_results=min(4, self._config.max_recall_results))
        body = (
            "# Mnemos Identity Continuity\n"
            "Mnemos is active in Provider Mode as Hermes' external memory provider for "
            "identity continuity. Hermes built-in memory remains active. Mnemos is local-first, "
            "scoped by agent, person, and project, and never overwrites SOUL.md, AGENTS.md, "
            "MEMORY.md, or USER.md.\n\n"
            f"Scope: agent={self.scope.agent_id} person={self.scope.person_id} "
            f"project={self.scope.project_scope}\n\n"
            "Your memory is yours to write, and nothing writes it for you. When something "
            "durable appears (a preference, a decision, a correction, project state, how the "
            "person likes to work), keep it with mnemos_identity_capture as it happens, in "
            "your own words: sessions end without warning. Put right what turns out wrong "
            "with mnemos_identity_correct. Leave your note on where this conversation stands "
            "with mnemos_identity_handoff: each conversation (a chat, or a topic in one) keeps "
            "its own, and wakes to it first.\n\n"
            f"{packet}"
        )
        wake_limit = self._config.max_wake_chars
        return _truncate(body, wake_limit) if wake_limit else body

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
        recalled = self._runtime._recall_own(clean, max_results=self._config.max_recall_results)
        if "No relevant continuity found" in recalled:
            return ""
        context = _truncate("# Mnemos Recall\n" + recalled, self._config.max_context_chars)
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
            IDENTITY_CAPTURE_SCHEMA,
            IDENTITY_RECALL_SCHEMA,
            IDENTITY_CORRECT_SCHEMA,
            IDENTITY_REPORT_SCHEMA,
            IDENTITY_HANDOFF_SCHEMA,
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        try:
            if tool_name == "mnemos_identity_capture":
                return self._tool_capture(args)
            if tool_name == "mnemos_identity_recall":
                return self._tool_recall(args)
            if tool_name == "mnemos_identity_correct":
                return self._tool_correct(args)
            if tool_name == "mnemos_identity_report":
                return self._tool_report(args)
            if tool_name == "mnemos_identity_handoff":
                return self._tool_handoff(args)
            return _json_error(f"Unknown Mnemos tool: {tool_name}")
        except Exception as exc:
            logger.debug("Mnemos tool %s failed", tool_name, exc_info=True)
            return _json_error(str(exc), tool=tool_name)

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        self._turn_count = int(turn_number or self._turn_count + 1)
        if not self._writes_enabled:
            return
        self._ensure_runtime()
        assert self._config is not None
        assert self._runtime is not None
        interval = self._config.maintenance_interval
        if interval and self._turn_count > 0 and self._turn_count % interval == 0:
            self._runtime.maintain(auto=True)
            self._prefetch_cache.clear()  # upkeep can archive what was recalled

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        """The memory's upkeep, and nothing written from the session."""
        if not self._writes_enabled:
            return
        self._ensure_runtime()
        assert self._runtime is not None
        self._runtime.maintain(auto=True)
        self._prefetch_cache.clear()  # upkeep can archive what was recalled

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

    def on_delegation(self, task: str, result: str, *, child_session_id: str = "", **kwargs: Any) -> None:
        """A delegation writes nothing: its result is in the conversation,
        for the agent to keep if it matters."""

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

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        save_hermes_mnemos_config(hermes_home, values)

    def shutdown(self) -> None:
        if self._runtime is not None:
            self._runtime.close()
        self._runtime = None
        self._scope = None
        self._prefetch_cache.clear()

    def _tool_capture(self, args: dict[str, Any]) -> str:
        content = _clean_text(args.get("content"))
        if not content:
            return _json_error("content is required")
        context = _clean_text(args.get("context"))
        importance = _importance_value(args.get("importance"), "auto")
        if bool(args.get("review")):
            note_id = self._queue_review_item(content, reason="tool review=true", context=context)
            return _json_ok(status="queued_for_review", continuity_note_id=note_id, scope=asdict(self.scope))
        result = self._capture(content, context, importance)
        return _json_ok(status="captured", result=result, scope=asdict(self.scope))

    def _tool_handoff(self, args: dict[str, Any]) -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        # Stored exactly as written: no cleaning, unlike a capture.
        text = str(args.get("text") or "")
        if not text.strip():
            return _json_error("text is required")
        result = self._runtime.handoff(text, signed_as=str(args.get("signed_as") or ""))
        return _json_ok(status="saved", result=result, scope=asdict(self.scope))

    def _tool_recall(self, args: dict[str, Any]) -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        query = _clean_text(args.get("query"))
        if not query:
            return _json_error("query is required")
        max_results = self._bounded_int(args.get("max_results"), default=self._config.max_recall_results if self._config else 6)
        recall = self._runtime.recall(query, max_results=max_results)
        payload: dict[str, Any] = {"query": query, "result": recall, "scope": asdict(self.scope)}
        if bool(args.get("include_graph")):
            graph = self._runtime.identity_graph(max_nodes=max_results)
            payload["graph"] = {
                "summary": graph["summary"],
                "stats": graph["stats"],
                "nodes": graph["nodes"],
                "edges": graph["edges"],
            }
        return _json_ok(**payload)

    def _tool_correct(self, args: dict[str, Any]) -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        # What prefetch recalled may be what this corrects or forgets.
        self._prefetch_cache.clear()
        result = self._runtime.correct(
            correction=_clean_text(args.get("correction")),
            target_id=_clean_text(args.get("target_id")),
            query=_clean_text(args.get("query")),
            action=str(args.get("action") or "update"),
        )
        return _json_ok(status="corrected", result=result, scope=asdict(self.scope))

    def _tool_report(self, args: dict[str, Any]) -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        kind = str(args.get("kind") or "status").strip().lower()
        max_results = self._bounded_int(args.get("max_results"), default=self._config.max_recall_results if self._config else 6)
        if kind == "context":
            return _json_ok(kind=kind, result=self._runtime.context(_clean_text(args.get("query")), max_results=max_results), scope=asdict(self.scope))
        if kind == "graph":
            return _json_ok(kind=kind, graph=self._runtime.identity_graph(max_nodes=max_results), scope=asdict(self.scope))
        if kind == "inbox":
            return _json_ok(kind=kind, inbox=self._review_inbox(limit=max_results), scope=asdict(self.scope))
        if kind == "maintain":
            result = self._runtime.maintain(deep=bool(args.get("deep")), auto=False)
            self._prefetch_cache.clear()  # upkeep can archive what was recalled
            return _json_ok(kind=kind, result=result, scope=asdict(self.scope))
        if kind == "status":
            return _json_ok(kind=kind, scope=asdict(self.scope), config=asdict(self._config) if self._config else {})
        return _json_error(f"Unsupported report kind: {kind}")

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

    def _capture(self, content: str, context: str = "", importance: str | float = "auto") -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        self._prefetch_cache.clear()
        return self._runtime.capture(content, context=context, importance=importance)

    def _queue_review_item(self, content: str, *, reason: str, context: str = "") -> str:
        self._ensure_runtime()
        assert self._runtime is not None
        self._runtime._ensure_init()
        assert self._runtime._store is not None
        note = content.strip()
        if context.strip():
            note = f"{note}\n\nContext: {context.strip()}"
        return self._runtime._store.write_hypomnema_entry(
            note,
            agent_id=self.scope.agent_id,
            person_id=self.scope.person_id,
            project_scope=self.scope.project_scope,
            source="observed",
            authored_by="agent",
            author_id=self.scope.agent_id,
            author_model=self._runtime.author_model(),
            domain=_domain_for(note),
            tags=_tags_for(note, "review", "inbox", "uncertain"),
            confidence=0.46,
            salience=0.42,
            foundational=False,
            related_session_id=self._session_id,
        )

    def _review_inbox(self, limit: int = 10) -> list[dict[str, Any]]:
        self._ensure_runtime()
        assert self._runtime is not None
        self._runtime._ensure_init()
        assert self._runtime._store is not None
        entries = self._runtime._store.search_hypomnema(
            "",
            agent_id=self.scope.agent_id,
            person_id=self.scope.person_id,
            project_scope=self.scope.project_scope,
            limit=max(1, min(50, limit * 3)),
        )
        review = [
            entry for entry in entries
            if float(entry.get("confidence", 1.0)) < 0.62
            or {"review", "inbox", "uncertain"} & set(entry.get("tags", []))
        ]
        return review[:limit]

    @staticmethod
    def _bounded_int(value: Any, *, default: int) -> int:
        try:
            return max(1, min(48, int(value)))
        except Exception:
            return default


def build_memory_provider_class(memory_provider_base: type) -> type:
    """Build a Hermes ``MemoryProvider`` subclass without hard-importing Hermes."""

    class MnemosMemoryProvider(MnemosMemoryProviderCore, memory_provider_base):  # type: ignore[misc, valid-type]
        pass

    MnemosMemoryProvider.__name__ = "MnemosMemoryProvider"
    MnemosMemoryProvider.__qualname__ = "MnemosMemoryProvider"
    MnemosMemoryProvider.__module__ = __name__
    return MnemosMemoryProvider
