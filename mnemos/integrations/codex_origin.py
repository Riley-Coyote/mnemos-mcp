"""Read explicit Codex project membership on the hook's machine.

Standard hooks use ``--codex-origin``. For a custom hook command:
  python -m mnemos.integrations.codex_origin -- HOOK_COMMAND

No project is inferred from cwd. These desktop state files are not a public
API; a missing field or a lookup failure leaves attribution unknown and the
original hook still runs. Only metadata for the current thread is forwarded.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from mnemos.attribution import clean_origin, hook_origin


logger = logging.getLogger(__name__)


def enrich_payload(payload: dict[str, Any], home: Path) -> dict[str, Any]:
    """Return hook data with an origin snapshot from explicit assignments."""
    origin = hook_origin(payload)
    thread = origin.get("thread_id")
    if not thread:
        return payload
    try:
        with closing(
            sqlite3.connect(
                (home / "state_5.sqlite").as_uri() + "?mode=ro", uri=True, timeout=0.1
            )
        ) as conn:
            row = conn.execute(
                "SELECT project_id, name, title FROM threads WHERE id = ?", (thread,)
            ).fetchone()
            if row:
                origin["thread_title"] = row[1] or row[2] or ""
                if row[0]:
                    project = conn.execute(
                        "SELECT name FROM projects WHERE id = ?", (row[0],)
                    ).fetchone()
                    origin.update(
                        project_id=row[0], project_name=project[0] if project else ""
                    )
    except (OSError, sqlite3.Error, ValueError):
        pass
    # Some desktop versions have not migrated thread assignments to app-server.
    # Read the exact assignment, never match a project's rootPaths against cwd.
    if not origin.get("project_id"):
        try:
            state = json.loads((home / ".codex-global-state.json").read_text())
            assignment = state.get("thread-project-assignments", {}).get(thread)
            if isinstance(assignment, dict) and assignment.get("projectKind") == "local":
                project_id = assignment.get("projectId")
                project = state.get("local-projects", {}).get(project_id, {})
                if isinstance(project_id, str):
                    migrated = state.get(
                        "app-server-project-id-by-legacy-project-id-by-host", {}
                    ).get(f"local:{home}", {})
                    origin.update(
                        project_id=migrated.get(project_id, project_id),
                        project_name=project.get("name", ""),
                    )
            elif thread in state.get("projectless-thread-ids", []):
                origin.update(project_id="", project_name="")
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    result = dict(payload)
    result["mnemos_origin"] = clean_origin(origin)
    return result


def enrich_local_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Read local assignments, leaving the hook usable if state is unavailable."""
    from mnemos.setup.connect import codex_home

    try:
        return enrich_payload(payload, codex_home().resolve())
    except (OSError, ValueError, RuntimeError):
        return payload


def main() -> int:
    """Forward bounded hook stdin and preserve the existing command's output."""
    from mnemos.cue import read_payload

    command = sys.argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        return 2
    raw = read_payload(sys.stdin, deadline=time.monotonic() + 0.25)
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            raw = json.dumps(enrich_local_payload(payload)).encode()
    except (ValueError, OSError):
        pass
    # No shell interpolation, and no new transport or service.
    return subprocess.run(command, input=raw, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
