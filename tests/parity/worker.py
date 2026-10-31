"""The child process that drives the engine: ``python -m tests.parity.worker``.

It reads one JSON job from stdin's first line:
``{"db", "driver", "deliveries": [op json...], "crash_at_write": int|null, "hash_each": bool}``
and prints protocol lines prefixed ``PARITY `` on stdout:

- ``{"ack": i, "index": k, "replayed": bool, "hash": str|null, "queue": {...}}`` after each delivery;
- ``{"write_point": n}`` when it reaches its n-th write statement (INSERT, UPDATE,
  DELETE, REPLACE, CREATE, ALTER, DROP or COMMIT, seen by sqlite's trace hook before
  it runs). It then blocks on stdin, and the parent kills it with SIGKILL there,
  mid-transaction;
- ``{"done": true, "writes": n}`` at the end.
"""

from __future__ import annotations

from . import determinism

determinism.install()

import json  # noqa: E402
import re  # noqa: E402
import sqlite3  # noqa: E402
import sys  # noqa: E402

_WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|COMMIT)\b", re.I)


class _Writes:
    count = 0
    crash_at: int | None = None


def _say(message: dict) -> None:
    sys.stdout.write("PARITY " + json.dumps(message, sort_keys=True) + "\n")
    sys.stdout.flush()


def _trace(statement: str) -> None:
    if not _WRITE.match(statement or ""):
        return
    _Writes.count += 1
    if _Writes.crash_at is not None and _Writes.count == _Writes.crash_at:
        _say({"write_point": _Writes.count, "sql": statement.strip()[:80]})
        sys.stdin.readline()  # the parent's SIGKILL arrives while this waits
        raise SystemExit("parity worker: parent did not kill at the write point")


_real_connect = sqlite3.connect


class _TracedConnection(sqlite3.Connection):
    """Counts writes whatever trace callback the engine sets on top (it sets its own)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        super().set_trace_callback(_trace)

    def set_trace_callback(self, callback):
        if callback is None:
            return super().set_trace_callback(_trace)

        def both(statement):
            _trace(statement)
            callback(statement)

        return super().set_trace_callback(both)


def _connect(*args, **kwargs):
    kwargs.setdefault("factory", _TracedConnection)
    return _real_connect(*args, **kwargs)


sqlite3.connect = _connect


def _resolve(value, db: str):
    if isinstance(value, dict) and len(value) == 1 and next(iter(value)) in ("$memory", "$note"):
        kind, key = next(iter(value.items()))
        conn = _real_connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT result_json FROM host_mutations WHERE idempotency_key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise LookupError(f"{key} has no ledger row: lost, or delivered out of causal order")
        text = json.loads(row[0])
        if kind == "$memory":
            found = re.search(r"captured correction (engram_\w+)", text) or re.search(r"Memory ID: (engram_\w+)", text)
        else:
            found = re.search(r"Continuity note ID: (\S+)", text)
        if not found:
            raise LookupError(f"{key}'s result names no {kind[1:]}: {text[:120]!r}")
        return found.group(1)
    if isinstance(value, dict):
        return {k: _resolve(v, db) for k, v in value.items()}
    return value


def _queue(db: str) -> dict:
    try:
        conn = _real_connect(f"file:{db}?mode=ro", uri=True)
        try:
            return {"rows": conn.execute("SELECT COUNT(*) FROM reflection_queue").fetchone()[0]}
        finally:
            conn.close()
    except sqlite3.Error:
        return {"rows": 0}


def main() -> None:
    job = json.loads(sys.stdin.readline())
    from .canon import store_hash
    from .drivers import DRIVERS
    from .life import Op

    import mnemos.store.sqlite_store as sqlite_store

    collisions = {"enqueue_attempts": 0, "enqueue_refused": 0}
    original_enqueue = sqlite_store.EngramStore.enqueue_reflection

    def counted_enqueue(self, *args, **kwargs):
        collisions["enqueue_attempts"] += 1
        made = original_enqueue(self, *args, **kwargs)
        if made is None:
            collisions["enqueue_refused"] += 1
        return made

    sqlite_store.EngramStore.enqueue_reflection = counted_enqueue

    db = job["db"]
    driver = DRIVERS[job["driver"]]()
    _Writes.crash_at = job.get("crash_at_write")
    for position, raw in enumerate(job["deliveries"]):
        op = Op.from_json(raw)
        determinism.at(op.index, op.moment())
        arguments = _resolve(op.arguments, db)
        before = _queue(db)["rows"]
        answer = driver.deliver(db, op, arguments)
        _say({
            "ack": position, "index": op.index, "replayed": answer["replayed"],
            "result": answer["result"] if isinstance(answer["result"], str) else json.dumps(answer["result"]),
            "queue_before": before, "queue_after": _queue(db)["rows"],
            "hash": store_hash(db) if job.get("hash_each") else None,
        })
    _say({"done": True, "writes": _Writes.count, "collisions": collisions})


if __name__ == "__main__":
    main()
