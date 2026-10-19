"""Every save either lands whole or leaves nothing behind.

Python's sqlite3 opens a transaction before a write's first statement. Most
store writes committed at their end and never rolled back, so when a
statement failed (a full disk, a lock, a constraint) the transaction stayed
open on the store's long-lived connection, holding the write lock: no other
process could write, the next write that began its own transaction failed
("cannot start a transaction within a transaction"), so a running server
refused saves until it restarted, and the next write that didn't committed
the failed write's first statements with its own, half a save.

Every EngramStore write now runs inside ``EngramStore.transaction()``, which
commits, or rolls back before it raises, and so do the runtime's own writes
on the store's connection; the store's schema setup and the embedding
index's writes, on a connection of their own, do the same. A test here fails
one statement with a TEMP trigger, which lives on that one connection, never
in the file, or with another process's lock.
"""

from __future__ import annotations

import ast
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import mnemos
from mnemos import cue
from mnemos.core.belief import Belief
from mnemos.core.engram import Connection, Engram
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store.embedding_index import EmbeddingIndex
from mnemos.store.sqlite_store import EngramStore

INJECTED = "IntegrityError: injected"
LOCKED = "OperationalError: database is locked"
SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "mnemos"}


@pytest.fixture
def db(tmp_path):
    return tmp_path / "memory.db"


@pytest.fixture
def store(db):
    store = EngramStore(db)
    # A lock is given up on after a tenth of a second here, not the store's five.
    store._get_conn().execute("PRAGMA busy_timeout=100")
    yield store
    store.close()


class _Embedder:
    model_name = "fake-model"
    dims = 4

    def embed(self, text):
        return [1.0, 0.0, 0.0, 0.0]

    def batch_embed(self, texts):
        return [self.embed(text) for text in texts]


@pytest.fixture
def index(store, db):
    index = EmbeddingIndex(db_path=str(db))
    index._available = True
    index._embedder = _Embedder()
    index._init_table()
    yield index
    index.close()


def _fail(conn, when, table, condition):
    """Make the write on ``conn`` that meets ``condition`` fail, as a full disk
    would fail it: a TEMP trigger, on this connection only."""
    conn.execute(
        f"CREATE TEMP TRIGGER injected_{when.lower()}_{table} BEFORE {when} "
        f"ON main.{table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'injected'); END"
    )


def _outcome(write):
    """'ok', or what the write raised."""
    try:
        write()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return "ok"


def _rows(db, sql, *params):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _others_can_write(db):
    """Whether another process could take the write lock now."""
    conn = sqlite3.connect(db, timeout=0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


# ── The store ──


def test_a_failed_meta_write_leaves_the_connection_ready_for_the_next(store, db):
    conn = store._get_conn()
    _fail(conn, "INSERT", "meta", "NEW.key = 'doomed'")

    seen = {"raised": _outcome(lambda: store.set_meta("doomed", "never kept"))}
    seen["left_in_a_transaction"] = conn.in_transaction
    seen["others_can_write"] = _others_can_write(db)
    # A write that begins its own transaction, as most store writes do.
    seen["next_write"] = _outcome(lambda: store.record_trace(
        tool="test", agent_id="demo", person_id="user", project_scope="global",
    ))

    assert seen == {
        "raised": INJECTED,
        "left_in_a_transaction": False,
        "others_can_write": True,
        "next_write": "ok",
    }
    assert _rows(db, "SELECT value FROM meta WHERE key = 'doomed'") == []
    assert _rows(db, "SELECT COUNT(*) FROM memory_trace WHERE tool = 'test'") == [(1,)]


def test_a_write_whose_second_statement_fails_keeps_nothing_of_its_first(store, db):
    memory = Engram(content="The kiln is fired on Thursdays.")
    store.save_engram(memory)
    conn = store._get_conn()
    # archive_engram writes the archive row, then marks the memory archived.
    _fail(conn, "UPDATE", "engrams", "NEW.state = 'archived'")

    seen = {"raised": _outcome(lambda: store.archive_engram(memory))}
    seen["left_in_a_transaction"] = conn.in_transaction
    # A write that lets Python open its transaction, as set_meta did, and
    # committed whatever the connection held.
    seen["next_write"] = _outcome(lambda: store.set_meta("next", "written"))
    seen["archive_rows"] = _rows(db, "SELECT COUNT(*) FROM archive WHERE id = ?", memory.id)[0][0]
    seen["state"] = _rows(db, "SELECT state FROM engrams WHERE id = ?", memory.id)[0][0]

    assert seen == {
        "raised": INJECTED,
        "left_in_a_transaction": False,
        "next_write": "ok",
        "archive_rows": 0,
        "state": "active",
    }
    assert store.get_meta("next") == "written"


def test_a_failed_link_does_not_stop_the_saves_after_it(store, db):
    ferry = Engram(content="The ferry leaves at seven.")
    harbor = Engram(content="The harbor closes at nine.")
    store.save_engram(ferry)
    store.save_engram(harbor)
    conn = store._get_conn()
    _fail(conn, "INSERT", "connections", f"NEW.target_id = '{harbor.id}'")

    link = Connection(target_id=harbor.id, relation="relates_to", strength=0.5)
    seen = {"raised": _outcome(lambda: store.save_connection(ferry.id, link))}
    seen["left_in_a_transaction"] = conn.in_transaction
    # Two saves after it that each begin their own transaction.
    seen["next_writes"] = [
        _outcome(lambda: store.set_standing(ferry.id, True, by="test")),
        _outcome(lambda: store.claim_return(ferry.id, "session-1")),
    ]

    assert seen == {
        "raised": INJECTED,
        "left_in_a_transaction": False,
        "next_writes": ["ok", "ok"],
    }
    assert _rows(db, "SELECT COUNT(*) FROM connections WHERE source_id = ?", ferry.id) == [(0,)]
    assert _rows(db, "SELECT standing FROM engrams WHERE id = ?", ferry.id) == [(1,)]
    assert _rows(db, "SELECT COUNT(*) FROM session_reinforcements") == [(1,)]


def test_a_note_replaced_in_a_failed_write_stays_the_only_one(store, db):
    march = "The orchard is pruned in March."
    note = store.write_hypomnema_entry(march, agent_id="demo")
    conn = store._get_conn()
    # The replacement is written first, then the old note is retired.
    _fail(conn, "UPDATE", "hypomnema_entries", f"OLD.id = '{note}' AND NEW.active = 0")

    seen = {"raised": _outcome(lambda: store.supersede_hypomnema_entry(
        note, "The orchard is pruned in February.", reason="corrected", agent_id="demo",
    ))}
    seen["left_in_a_transaction"] = conn.in_transaction
    seen["next_write"] = _outcome(lambda: store.set_meta("next", "written"))
    seen["active_notes"] = [row[0] for row in _rows(
        db, "SELECT content FROM hypomnema_entries WHERE active = 1 ORDER BY created_at",
    )]

    assert seen == {
        "raised": INJECTED,
        "left_in_a_transaction": False,
        "next_write": "ok",
        "active_notes": [march],
    }


def test_a_store_that_fails_to_open_leaves_no_transaction_behind(db, monkeypatch):
    EngramStore(db).close()
    seen = {}

    def fail(conn):
        seen["conn"] = conn
        raise sqlite3.OperationalError("injected")

    # The opening's own writes come before this step and after it.
    monkeypatch.setattr(EngramStore, "_backfill_engram_scopes", staticmethod(fail))
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        EngramStore(db)

    assert {
        "left_in_a_transaction": seen["conn"].in_transaction,
        "others_can_write": _others_can_write(db),
    } == {"left_in_a_transaction": False, "others_can_write": True}
    seen["conn"].close()


# ── An interrupted write ──
#
# An interrupt is no Exception. transaction() let one through without
# rolling back or counting itself out: the connection stayed inside the
# transaction, and every later write joined it and was lost with it.

_INTERRUPTS = [KeyboardInterrupt, SystemExit, GeneratorExit]
_READY = {"depth": 0, "left_in_a_transaction": False, "next_write": "ok", "kept": [("next", "written")]}


def _after_the_interrupt(store, db):
    seen = {
        "depth": store._transaction_depth,
        "left_in_a_transaction": store._get_conn().in_transaction,
        "next_write": _outcome(lambda: store.set_meta("next", "written")),
    }
    seen["kept"] = _rows(
        db, "SELECT key, value FROM meta WHERE key IN ('outer', 'inner', 'next') ORDER BY key",
    )
    return seen


@pytest.mark.parametrize("interrupt", _INTERRUPTS)
def test_an_interrupted_write_keeps_nothing_and_the_next_one_lands(store, db, interrupt):
    with pytest.raises(interrupt):
        with store.transaction():
            store.set_meta("outer", "never kept")
            raise interrupt

    assert _after_the_interrupt(store, db) == _READY


@pytest.mark.parametrize("interrupt", _INTERRUPTS)
def test_an_interrupt_in_an_inner_write_rolls_back_the_outermost(store, db, interrupt):
    with pytest.raises(interrupt):
        with store.transaction():
            store.set_meta("outer", "never kept")
            with store.transaction():
                store.set_meta("inner", "never kept")
                raise interrupt

    assert _after_the_interrupt(store, db) == _READY


def test_an_interrupt_while_committing_rolls_back(store, db, monkeypatch):
    commit = store._commit
    interrupted = []

    def commit_interrupted_once():
        if not interrupted:
            interrupted.append(True)
            raise KeyboardInterrupt
        commit()

    monkeypatch.setattr(store, "_commit", commit_interrupted_once)
    with pytest.raises(KeyboardInterrupt):
        store.set_meta("outer", "never kept")

    assert _after_the_interrupt(store, db) == _READY


# ── The embedding index, on a connection of its own ──


@pytest.mark.parametrize("write", ["index_engram", "remove"])
def test_a_failed_vector_write_leaves_no_lock_behind(store, index, db, write):
    conn = index._get_conn()
    if write == "index_engram":
        _fail(conn, "INSERT", "embeddings", "NEW.engram_id = 'doomed'")
        failing = lambda: index.index_engram("doomed", "The violin is tuned weekly.")  # noqa: E731
        kept = [("kept",)]
    else:
        index.index_engram("doomed", "The violin is tuned weekly.")
        _fail(conn, "DELETE", "embeddings", "OLD.engram_id = 'doomed'")
        failing = lambda: index.remove("doomed")  # noqa: E731
        kept = [("doomed",), ("kept",)]

    seen = {"raised": _outcome(failing)}
    seen["left_in_a_transaction"] = conn.in_transaction
    # The store's next save, on its own connection, needs the write lock.
    seen["store_next_write"] = _outcome(lambda: store.set_meta("next", "written"))
    seen["index_next_write"] = _outcome(
        lambda: index.index_engram("kept", "The lantern is lit at dusk.")
    )

    assert seen == {
        "raised": INJECTED,
        "left_in_a_transaction": False,
        "store_next_write": "ok",
        "index_next_write": "ok",
    }
    assert _rows(db, "SELECT engram_id FROM embeddings ORDER BY engram_id") == kept


def test_a_failed_batch_of_vectors_keeps_none_of_it(index, db):
    conn = index._get_conn()
    _fail(conn, "INSERT", "embeddings", "NEW.engram_id = 'second'")

    seen = {"raised": _outcome(lambda: index.batch_index([
        ("first", "The glacier moved an inch."), ("second", "The fern was watered."),
    ]))}
    seen["left_in_a_transaction"] = conn.in_transaction
    seen["next_write"] = _outcome(lambda: index.index_engram("next", "The ferry was late."))
    seen["kept"] = _rows(db, "SELECT engram_id FROM embeddings ORDER BY engram_id")

    assert seen == {
        "raised": INJECTED,
        "left_in_a_transaction": False,
        "next_write": "ok",
        "kept": [("next",)],
    }


def test_a_failed_pass_of_passages_keeps_none_of_it(index, db, monkeypatch):
    first = [("orchard", "The orchard is pruned in March."), ("kiln", "The kiln is fired on Thursdays.")]
    assert index.index_passages(first)["items"] == 2
    before = _rows(db, "SELECT item_id, text_hash FROM passage_vectors ORDER BY item_id")
    conn = index._get_conn()
    packed = []
    real = index._to_bytes

    def to_bytes(values):
        # The second item's vector fails to pack, after the first item's
        # passages were replaced and the second's old ones deleted.
        packed.append(values)
        if len(packed) > 1:
            raise RuntimeError("injected")
        return real(values)

    later = [("orchard", "The orchard is pruned in February."), ("kiln", "The kiln is fired on Fridays.")]
    with monkeypatch.context() as patched:
        patched.setattr(index, "_to_bytes", to_bytes)
        seen = {"raised": _outcome(lambda: index.index_passages(later))}
    seen["left_in_a_transaction"] = conn.in_transaction
    seen["next_write"] = _outcome(lambda: index.index_engram("next", "The ferry was late."))
    seen["passages"] = _rows(db, "SELECT item_id, text_hash FROM passage_vectors ORDER BY item_id")

    assert seen == {
        "raised": "RuntimeError: injected",
        "left_in_a_transaction": False,
        "next_write": "ok",
        "passages": before,
    }


# ── The cue's write, on a connection it opens and closes ──


def test_the_cues_write_keeps_nothing_when_it_fails(store, db, monkeypatch):
    connect = sqlite3.connect

    def failing_connect(*args, **kwargs):
        conn = connect(*args, **kwargs)
        _fail(conn, "INSERT", "meta", f"NEW.key = '{cue.JUDGE_CALLS_KEY}'")
        return conn

    with monkeypatch.context() as patched:
        patched.setattr(sqlite3, "connect", failing_connect)
        kept = cue.keep_judged_calls(db, [("2026-10-19T12:00:00+00:00", "answered")])

    assert kept is False
    assert store.get_meta(cue.JUDGE_CALLS_KEY) is None
    assert _others_can_write(db)


# ── The runtime's own writes, on the store's connection ──


@pytest.fixture
def runtime(db):
    runtime = MnemosRuntime(db_path=str(db), use_dedicated_model=False, **SCOPE)
    runtime._ensure_init()
    runtime._store._get_conn().execute("PRAGMA busy_timeout=100")
    yield runtime
    runtime.close()


@contextmanager
def _another_process_writing(db):
    """The store's write lock, held by another connection."""
    other = sqlite3.connect(db, timeout=0)
    other.execute("BEGIN IMMEDIATE")
    try:
        yield
    finally:
        other.rollback()
        other.close()


def _memory(runtime, words):
    memory = Engram(
        content=words, owner_agent_id=SCOPE["agent_id"], person_id=SCOPE["person_id"],
        project_scope=SCOPE["project_scope"],
    )
    runtime._store.save_engram(memory)
    return memory.id


def _a_plain_question_set_aside(runtime):
    """A fading memory's lesson question takes the place of its plain one."""
    memory = _memory(runtime, "The ferry timetable changed in the spring.")
    return lambda: runtime._enqueue_lesson_reflections({"awaiting_impact": [memory]})


def _a_reaffirmation_asked_again(runtime):
    """A belief's reaffirmation, never answered and now expired, is put again."""
    memory = _memory(runtime, "The rendered page showed the missing alignment.")
    belief = Belief(
        agent_id=SCOPE["agent_id"], content="The render is the honest judge.",
        confidence=0.6, source="agent", supporting_engram_ids=[memory],
    )
    belief.last_challenged = belief.created_at = (
        datetime.now(timezone.utc) - timedelta(days=40)
    ).isoformat()
    runtime._store.save_belief(belief)
    runtime._store.enqueue_reflection(
        "reaffirm", memory, f"Still true? [belief:{belief.id}]", **SCOPE, expires_in_days=-1,
    )
    return lambda: runtime._enqueue_belief_reaffirmation(set())


def _words_kept_on_a_question(runtime):
    return lambda: runtime._keep_on_question({"id": "question-1"}, "Not sure yet.")


@pytest.mark.parametrize(
    "write", [_a_plain_question_set_aside, _a_reaffirmation_asked_again, _words_kept_on_a_question],
)
def test_the_runtimes_own_write_that_meets_a_lock_leaves_the_connection_ready(runtime, db, write):
    failing = write(runtime)
    with _another_process_writing(db):
        seen = {"raised": _outcome(failing)}
    seen["left_in_a_transaction"] = runtime._store._get_conn().in_transaction
    seen["next_writes"] = [
        _outcome(lambda: runtime._store.set_meta("next", "written")),
        _outcome(lambda: runtime._store.record_trace(tool="test", **SCOPE)),
    ]

    assert seen == {
        "raised": LOCKED,
        "left_in_a_transaction": False,
        "next_writes": ["ok", "ok"],
    }


# ── The guard ──

# Schema setup when a store is opened: _init_db, and the one-time migrations
# it runs. Each commits what came before it and takes its own BEGIN IMMEDIATE
# (so a second process opening the store waits and looks again), and rolls
# back if anything in it fails. executescript, which _init_db runs between
# them, commits any open transaction first, so this setup cannot be one
# transaction().
_SCHEMA_SETUP = {
    "_allow_reaffirm_asks",
    "_label_engram_authors",
    "_label_hermes_auto_writes",
    "_link_older_capture_pairs",
}
# Code with a connection of its own, which it commits and rolls back itself:
# the cue's judge row, the meaning index, backups, the quiet hour's copy.
_OWN_CONNECTIONS = {
    "mnemos/cue.py",
    "mnemos/store/embedding_index.py",
    "mnemos/backup.py",
    "mnemos/life.py",
}
_STORE = "mnemos/store/sqlite_store.py"


def _functions(tree):
    """Each function at the top of a module or a class, by its qualified name
    (a function nested in one counts as part of it), and the statements outside
    any function, as ``<body>``."""
    def walk(body, prefix):
        loose = []
        for node in body:
            if isinstance(node, ast.ClassDef):
                yield from walk(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{prefix}{node.name}", node
            else:
                loose.append(node)
        yield f"{prefix}<body>", ast.Module(body=loose, type_ignores=[])

    yield from walk(tree.body, "")


def _calls(function, name):
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
        for node in ast.walk(function)
    )


def test_only_transaction_commits_a_write_on_the_stores_connection():
    package = Path(mnemos.__file__).parent
    commits, connection_commits = set(), set()
    migration_callers = {name: set() for name in _SCHEMA_SETUP}
    for path in sorted(package.rglob("*.py")):
        module = path.relative_to(package.parent).as_posix()
        for name, function in _functions(ast.parse(path.read_text(encoding="utf-8"))):
            where = f"{module}:{name}"
            if _calls(function, "_commit"):
                commits.add(where)
            if _calls(function, "commit") and module not in _OWN_CONNECTIONS:
                connection_commits.add(where)
            for migration in _SCHEMA_SETUP:
                if _calls(function, migration):
                    migration_callers[migration].add(where)

    store = f"{_STORE}:EngramStore"
    assert f"{store}.transaction" in commits
    assert sorted(commits - {f"{store}.transaction", f"{store}._init_db"}) == []
    # _commit is transaction()'s own commit.
    allowed = {f"{store}._commit", *(f"{store}.{name}" for name in _SCHEMA_SETUP)}
    assert sorted(connection_commits - allowed) == []
    # The migrations commit only because opening the store runs them.
    assert {name: sorted(callers) for name, callers in migration_callers.items()} == {
        name: [f"{store}._init_db"] for name in _SCHEMA_SETUP
    }
