"""Entry provenance, independent of memory scope and model signatures.

MCP request context belongs to one call, never the process environment. A
local hook may register explicit project membership for a thread; a write
snapshots that membership, so moving the chat cannot relabel older entries.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import closing, contextmanager
from contextvars import ContextVar
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_FIELDS = {
    "thread_id",
    "session_id",
    "project_id",
    "project_name",
    "thread_title",
    "cwd",
}
_origin: ContextVar[dict[str, str]] = ContextVar("mnemos_origin", default={})


def clean_origin(value: Any) -> dict[str, str]:
    """Keep bounded provenance fields; none grants access or names a store."""
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for key in _FIELDS:
        text = value.get(key)
        if not isinstance(text, str):
            continue
        if key in {"thread_id", "session_id"}:
            from .authorship import clean_session_id

            if not text or clean_session_id(text):
                result[key] = text
        elif key.endswith("_id"):
            if not text or _ID.fullmatch(text):
                result[key] = text
        elif key == "cwd":
            if len(text) <= 4096 and "\x00" not in text:
                result[key] = text
        else:
            result[key] = " ".join(
                "".join(c for c in text if c.isprintable() or c.isspace()).split()
            )[:160]
    return result


def current_origin() -> dict[str, str]:
    """The current request's provenance; callers receive a copy."""
    return dict(_origin.get())


@contextmanager
def bind_origin(origin: Mapping[str, Any]) -> Iterator[None]:
    """Bind one call's origin, restoring it on success or failure."""
    token = _origin.set(clean_origin(origin))
    try:
        yield
    finally:
        _origin.reset(token)


def mcp_origin(ctx: Any) -> dict[str, str]:
    """Read SDK request metadata without adding model-facing tool arguments."""
    from .mcp_compat import request_meta

    from .authorship import clean_session_id

    meta = request_meta(ctx)
    thread = clean_session_id(meta.get("threadId"))
    if not thread:
        return {}
    origin = clean_origin(meta.get("mnemos/origin"))
    origin.update(thread_id=thread, session_id=clean_session_id(meta.get("sessionId")))
    return origin


def hook_origin(payload: Any) -> dict[str, str]:
    """Use the hook's actual thread identity, including Codex subagents."""
    if not isinstance(payload, Mapping):
        return {}
    from .authorship import clean_session_id

    origin = clean_origin(payload.get("mnemos_origin"))
    origin.update(
        clean_origin(
            {
                "thread_id": clean_session_id(payload.get("agent_id"))
                or clean_session_id(payload.get("session_id")),
                "session_id": payload.get("session_id"),
                "cwd": payload.get("cwd"),
            }
        )
    )
    return origin if origin.get("thread_id") else {}


def origin_key(thread: str, agent: str, person: str, scope: str) -> str:
    """A lookup key inside the existing store, scoped just like its entries."""
    return "entry_origin:" + json.dumps([agent, person, scope, thread])


def register_hook_origin(store: Any, payload: Any, scope: Any) -> None:
    """Remember explicit hook metadata in an already-open store only."""
    origin = hook_origin(payload)
    if not origin.get("thread_id") or "mnemos_origin" not in payload:
        return
    # Optional provenance must not suppress the existing briefing or cue.
    try:
        key = origin_key(
            origin["thread_id"], scope.agent_id, scope.person_id, scope.project_scope
        )
        encoded = json.dumps(origin, sort_keys=True)
        if store.get_meta(key) != encoded:
            store.set_meta(key, encoded)
    except (OSError, ValueError, sqlite3.Error):
        pass


def register_prompt_origin(db_path: str | Path, payload: Any, scope: Any) -> None:
    """Update optional prompt metadata without creating or migrating a store."""
    origin = hook_origin(payload)
    if not origin.get("thread_id") or "mnemos_origin" not in payload:
        return
    try:
        key = origin_key(
            origin["thread_id"], scope.agent_id, scope.person_id, scope.project_scope
        )
        encoded = json.dumps(origin, sort_keys=True)
        # A writer must not consume the cue's deadline. mode=rw also makes
        # the missing-store rule hold if the file disappears before connect.
        with closing(sqlite3.connect(
            Path(db_path).expanduser().resolve().as_uri() + "?mode=rw",
            uri=True, timeout=0.05,
        )) as conn, conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            if row is None or row[0] != encoded:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (key, encoded),
                )
    except (OSError, ValueError, sqlite3.Error):
        pass


def stored_origin(row: Mapping[str, Any]) -> dict[str, str]:
    """Provenance from a stored row, including rows written before this field."""
    value = row.get("origin", row.get("origin_json", {}))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return clean_origin(value)


def origin_suffix(row: Mapping[str, Any]) -> str:
    """A compact source label for recall and startup context."""
    origin = stored_origin(row)
    parts = []
    for kind, name in (("project", "project_name"), ("task", "thread_title")):
        identifier = origin.get("project_id" if kind == "project" else "thread_id")
        label = origin.get(name)
        if identifier:
            parts.append(
                f"{kind}={label} ({identifier})" if label else f"{kind}={identifier}"
            )
    return "; " + "; ".join(parts) if parts else ""
