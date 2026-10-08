"""Maintenance links by what recall reads, by every path that runs it.

Two ways a store's links depended on which code path ran:

  * `mnemos consolidate` (what the scheduled jobs run, every four hours and at
    night) handed the discovery pass no embedding index, so it linked by words
    alone and never read ``similarity_threshold``. A session's maintenance
    passed its index and linked by meaning too. On a copy of a real store
    grown to twelve times its size (6,654 live memories), one pass made
    18,771 links through the command, all by words, and 19,896 through a
    session (4,239 by meaning).
  * The pass's lookup by meaning read only the whole-text vectors capture
    writes (``embeddings``), while recall reads the passages
    (``passage_vectors``). A memory indexed only as passages could never be
    linked by meaning: 2,890 of 6,654 live memories on that copy.

Now every path hands the cycle the same index (``maintenance_index``), and the
pass asks it as recall does (``search_candidates``: each memory by its best
passage, over only the memories it may be linked to), by passages alone.
Without the model the pass links by words, as before, and says why.
"""

from __future__ import annotations

import json
import math
import re
import socket
import sqlite3
import sys
import types

import pytest

from mnemos import life, simple_mcp, simple_runtime
from mnemos.cli import main
from mnemos.code_version import MAINTENANCE_CODE_VERSION
from mnemos.consolidation.connection_discovery import run_connection_discovery
from mnemos.core.engram import Engram
from mnemos.setup import scheduler
from mnemos.store import embedding_index as ei
from mnemos.store.embedding_index import EmbeddingIndex
from mnemos.store.fts import distinctive_terms
from mnemos.store.sqlite_store import EngramStore

SCOPE = {"agent_id": "nova", "person_id": "riley", "project_scope": "demo"}
SCOPE_ARGS = ("--agent-id", "nova", "--person-id", "riley", "--project-scope", "demo")

# Two memories about one thing in different words: only meaning can link them.
KEEPER = "The lighthouse keeper kept the logbook every night."
BEACON = "A beacon lamp shone over the north rocks."
# About something else entirely.
GARDEN = "Marigolds bloom early in the greenhouse."


# ── A model whose meaning is controlled ──

_CONCEPTS = (
    {"lighthouse", "beacon", "lamp", "keeper"},
    {"harbour", "ferry", "pier", "boat", "timetable"},
    {"garden", "marigolds", "greenhouse", "bloom"},
)


def _concept_vector(text: str) -> list[float]:
    """Similar meaning without shared words: "beacon" is near "lighthouse"."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    raw = [float(len(words & group)) for group in _CONCEPTS] + [0.05]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


class _Vector(list):
    def tolist(self):
        return list(self)


class _ConceptModel:
    def encode(self, texts, normalize_embeddings=True, batch_size=32):
        if isinstance(texts, str):
            return _Vector(_concept_vector(texts))
        return [_Vector(_concept_vector(text)) for text in texts]


class _ConceptEmbedder(ei._LocalEmbedder):
    def _get_model(self):
        if self._model is None:
            self._model = _ConceptModel()
        return self._model


@pytest.fixture
def meaning(monkeypatch):
    """A working local backend, for every index made while the test runs."""
    monkeypatch.setattr(ei, "_check_local_deps", lambda: True)
    monkeypatch.setattr(ei, "_LocalEmbedder", _ConceptEmbedder)
    monkeypatch.setattr(ei, "_LOGGED", set(), raising=False)


@pytest.fixture
def no_network(monkeypatch):
    """Every attempt to reach the network, kept and refused."""
    attempts: list[object] = []

    def refused(*args, **kwargs):
        attempts.append(args[1:] if args else kwargs)
        raise OSError("this test has no network")

    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket.socket, "connect_ex", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(socket, "getaddrinfo", refused)
    return attempts


# ── A store ──


def _memory(content: str) -> Engram:
    return Engram(content=content, kind="semantic", owner_agent_id="nova",
                  person_id="riley", project_scope="demo")


def _seed(db, *, passages=(), whole_text=()) -> list[Engram]:
    """KEEPER, BEACON and GARDEN, with passages for the texts in ``passages``
    and capture's whole-text vector for those in ``whole_text``."""
    store = EngramStore(str(db))
    try:
        memories = [_memory(text) for text in (KEEPER, BEACON, GARDEN)]
        for memory in memories:
            store.save_engram(memory)
    finally:
        store.close()
    index = EmbeddingIndex(db_path=str(db))
    try:
        index.index_passages([(m.id, m.content) for m in memories if m.content in passages])
        for memory in memories:
            if memory.content in whole_text:
                assert index.index_engram(memory.id, memory.content)
    finally:
        index.close()
    return memories


def _read(db, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _links(db, engram: Engram) -> set[str]:
    return {row[0] for row in _read(db, "SELECT target_id FROM connections WHERE source_id = ?",
                                    (engram.id,))}


def _vectors(db, engram: Engram) -> tuple[int, int]:
    """How many whole-text vectors and passages ``engram`` has."""
    whole = _read(db, "SELECT COUNT(*) FROM embeddings WHERE engram_id = ?", (engram.id,))[0][0]
    cut = _read(db, "SELECT COUNT(*) FROM passage_vectors WHERE item_id = ?", (engram.id,))[0][0]
    return whole, cut


def _last_cycle(db) -> dict:
    rows = _read(db, "SELECT stats FROM consolidation_log WHERE pass_name = 'cycle' "
                     "ORDER BY completed_at DESC LIMIT 1")
    return json.loads(rows[0][0])


def _words_alone_cannot_link(*texts: str) -> None:
    first, second = (distinctive_terms(text) for text in texts)
    assert not first & second, "premise: the two memories share a word"


# ── 1. The command links by meaning when it can ──


@pytest.mark.parametrize("deep", [False, True], ids=["consolidate", "consolidate --deep"])
def test_consolidate_links_by_meaning_when_the_index_is_on(tmp_path, meaning, capsys, deep):
    db = tmp_path / "memory.db"
    keeper, beacon, garden = _seed(db, passages=(BEACON, GARDEN))
    _words_alone_cannot_link(KEEPER, BEACON)

    assert main(["--db-path", str(db), *SCOPE_ARGS, "consolidate", *(["--deep"] if deep else [])]) == 0
    out = capsys.readouterr().out

    assert beacon.id in _links(db, keeper), out
    assert garden.id not in _links(db, keeper), "linked under the similarity"
    assert "links by words only" not in out, out
    assert "words_only" not in _last_cycle(db)["connection_discovery"]


# ── 2. Without meaning it links by words, and says why ──

# Two memories about one thing in the same words: the words path links them.
LOGBOOK = ("The keeper kept a storm logbook.", "A storm logbook the keeper kept.")


def _seed_words(db) -> list[Engram]:
    store = EngramStore(str(db))
    try:
        memories = [_memory(text) for text in LOGBOOK]
        for memory in memories:
            store.save_engram(memory)
        return memories
    finally:
        store.close()


def _no_backend(monkeypatch) -> None:
    monkeypatch.setattr(ei, "_check_local_deps", lambda: False)
    monkeypatch.setattr(ei, "_LOGGED", set(), raising=False)


def _no_model_on_disk(monkeypatch) -> list[dict]:
    """sentence-transformers installed, the model never downloaded: a load
    from local files fails at once. Returns the keyword arguments of every
    load, which must all ask for local files only."""
    module = types.ModuleType("sentence_transformers")

    class SentenceTransformer:
        calls: list[dict] = []

        def __init__(self, name, **kwargs):
            SentenceTransformer.calls.append(kwargs)
            if not kwargs.get("local_files_only"):
                raise AssertionError("the model load asked the network")
            raise OSError("the model is not in the local cache")

    module.SentenceTransformer = SentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setattr(ei, "_check_local_deps", lambda: True)
    monkeypatch.setattr(ei, "_LOGGED", set(), raising=False)
    return SentenceTransformer.calls


@pytest.mark.parametrize("off", ["no backend", "no model on disk"])
def test_consolidate_links_by_words_and_says_why_when_meaning_is_off(
    tmp_path, monkeypatch, capsys, no_network, off,
):
    db = tmp_path / "memory.db"
    first, second = _seed_words(db)
    loads = _no_backend(monkeypatch) if off == "no backend" else _no_model_on_disk(monkeypatch)
    if off == "no backend":
        reason = EmbeddingIndex(db_path=str(db)).unavailable_reason
        said = f"links by words only: meaning search is off ({reason})"
    else:
        said = (
            "links by words only: meaning search is off (the local model all-MiniLM-L6-v2 "
            "failed to load from this machine"
        )

    assert main(["--db-path", str(db), *SCOPE_ARGS, "consolidate"]) == 0
    out = capsys.readouterr().out

    assert second.id in _links(db, first), "the words did not link what belongs together"
    [connections] = [line for line in out.splitlines() if line.startswith("  Connections:")]
    assert said in connections, out
    assert _last_cycle(db)["connection_discovery"]["words_only"].startswith(said)
    assert no_network == [], f"meaning tried the network: {no_network}"
    if loads is not None:
        assert loads and all(call.get("local_files_only") for call in loads), loads


def test_consolidate_runs_by_words_when_the_index_cannot_be_opened(tmp_path, monkeypatch, capsys):
    """The index is built before the cycle now: one that can't be opened
    stops nothing. The cycle links by words and says why."""
    db = tmp_path / "memory.db"
    first, second = _seed_words(db)

    def locked(db_path):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(simple_runtime, "maintenance_index", locked)

    assert main(["--db-path", str(db), *SCOPE_ARGS, "consolidate"]) == 0
    out = capsys.readouterr().out

    assert "Meaning search: off, the index could not be opened (OperationalError: database is locked)" in out
    assert "links by words only: meaning search is off (no embedding index)" in out, out
    assert "Passes: connection_discovery, decay" in out, "the cycle did not run"
    assert second.id in _links(db, first), "the words did not link what belongs together"


# ── 3. The pass finds what recall finds: a memory with passages only ──


def test_the_pass_links_a_memory_whose_only_vector_is_a_passage(tmp_path, meaning):
    db = tmp_path / "memory.db"
    keeper, beacon, garden = _seed(db, passages=(BEACON, GARDEN))
    assert _vectors(db, beacon)[0] == 0 and _vectors(db, beacon)[1] > 0, "premise: passages only"
    _words_alone_cannot_link(KEEPER, BEACON)

    store, index = EngramStore(str(db)), EmbeddingIndex(db_path=str(db))
    try:
        stats = run_connection_discovery(store, embedding_index=index, config={}, **SCOPE)
    finally:
        index.close()
        store.close()

    assert beacon.id in _links(db, keeper)
    assert garden.id not in _links(db, keeper)
    assert stats["embedding_candidates"] >= 1, stats
    assert "words_only" not in stats, stats


def test_a_pass_with_no_scope_links_by_passages_too(tmp_path, meaning):
    """The advanced server and the bridge run the cycle with an agent and no
    person or project: the pass may then link any active memory, as before,
    and finds it by its passages."""
    db = tmp_path / "memory.db"
    keeper, beacon, garden = _seed(db, passages=(BEACON, GARDEN))
    store = EngramStore(str(db))
    try:
        retired = _memory("A beacon lamp guards the north rocks.")  # the lighthouse, but retired
        store.save_engram(retired)
        store.archive_engram(retired, reason="simple_correction_update")
    finally:
        store.close()
    index = EmbeddingIndex(db_path=str(db))
    try:
        index.index_passages([(retired.id, retired.content)])
    finally:
        index.close()

    store, index = EngramStore(str(db)), EmbeddingIndex(db_path=str(db))
    try:
        run_connection_discovery(store, embedding_index=index, config={}, agent_id="nova")
    finally:
        index.close()
        store.close()

    assert beacon.id in _links(db, keeper)
    assert garden.id not in _links(db, keeper)
    assert retired.id not in _links(db, keeper), "a retired memory was given a new link"


# ── 4. The pass reads no whole-text vector ──


def test_the_pass_reads_no_whole_text_vector(tmp_path, meaning):
    """The pass reads the passages alone. A memory with capture's whole-text
    vector and no passage yet waits for its passages to be linked by
    meaning (recall still finds it by that vector meanwhile)."""
    db = tmp_path / "memory.db"
    keeper, beacon, garden = _seed(db, passages=(BEACON,), whole_text=(BEACON, GARDEN))
    store = EngramStore(str(db))
    try:
        # One more memory about the lighthouse, with no passage yet.
        waiting = _memory("Beacon lamps turn at dusk.")
        store.save_engram(waiting)
    finally:
        store.close()
    index = EmbeddingIndex(db_path=str(db))
    try:
        assert index.index_engram(waiting.id, waiting.content)
    finally:
        index.close()
    assert _vectors(db, waiting) == (1, 0), "premise: a whole-text vector, no passage"
    _words_alone_cannot_link(KEEPER, waiting.content)

    statements: list[str] = []
    store, index = EngramStore(str(db)), EmbeddingIndex(db_path=str(db))
    store._get_conn().set_trace_callback(statements.append)
    index._get_conn().set_trace_callback(statements.append)
    try:
        run_connection_discovery(store, embedding_index=index, config={}, **SCOPE)
    finally:
        store._get_conn().set_trace_callback(None)
        index._get_conn().set_trace_callback(None)
        index.close()
        store.close()

    read = [sql for sql in statements if re.search(r"\bembeddings\b", sql)]
    assert read == [], read
    assert any("passage_vectors" in sql for sql in statements), "premise: the pass read passages"
    assert beacon.id in _links(db, keeper), "found by its passages"
    assert waiting.id not in _links(db, keeper), "linked by a whole-text vector"


# ── 5. Every path that runs the cycle links by meaning ──


def _scheduled(job: scheduler.SchedulerJob, db) -> list[str]:
    """The argv a scheduled job runs, as `mnemos daemon install` writes it."""
    argv = scheduler.command_for(
        job, mnemos_command="mnemos", scope_args=(*SCOPE_ARGS, "--db-path", str(db)),
    )
    assert argv[0] == "mnemos"
    return argv[1:]


def _a_quiet_hour_maintains(tmp_path, monkeypatch, db) -> None:
    """What a quiet hour runs: its Mnemos server, started from the MCP config
    the hour writes (`mnemos ... serve`, the simple server), maintaining as
    its `mnemos_maintain` tool does."""
    mcp, _settings, _cmd = life._files_and_command(
        "ours", "hour-test", tmp_path / "hour", db, SCOPE, "claude", "mnemos",
    )
    args = mcp["mcpServers"]["mnemos"]["args"]
    assert args[-1] == "serve", args
    flags = dict(zip(args[:-1:2], args[1:-1:2]))
    monkeypatch.setattr(simple_mcp, "_runtime", None)
    monkeypatch.setattr(simple_mcp, "_runtime_kwargs", {})
    simple_mcp.configure_runtime(
        db_path=flags["--db-path"], agent_id=flags["--agent-id"],
        person_id=flags["--person-id"], project_scope=flags["--project-scope"],
    )
    try:
        simple_mcp._get_runtime().maintain()
    finally:
        simple_mcp._get_runtime().close()


def test_the_scheduled_jobs_and_a_quiet_hour_link_by_meaning(tmp_path, meaning, monkeypatch, capsys):
    ran = []
    for job in scheduler.JOBS:
        db = tmp_path / f"{job.name}.db"
        keeper, beacon, _garden = _seed(db, passages=(BEACON, GARDEN))
        assert main(_scheduled(job, db)) == 0
        ran.append((job.name, beacon.id in _links(db, keeper)))
    capsys.readouterr()

    db = tmp_path / "hour.db"
    keeper, beacon, _garden = _seed(db, passages=(BEACON, GARDEN))
    _a_quiet_hour_maintains(tmp_path, monkeypatch, db)
    ran.append(("quiet hour", beacon.id in _links(db, keeper)))

    assert [name for name, _ in ran] == ["maintain", "maintain-deep", "quiet hour"]
    assert all(linked for _, linked in ran), ran


# ── 6. Code from before this change stands down ──


def test_the_code_version_is_raised_so_older_upkeep_stands_down(tmp_path, monkeypatch, capsys):
    """How maintenance links changed, so a session or scheduled job still
    running the code before this change stops maintaining a store this code
    has opened, rather than linking it by the old rules beside the new."""
    assert MAINTENANCE_CODE_VERSION >= 21, "how maintenance links changed, and the code version was not raised"
    db = tmp_path / "memory.db"
    first, _second = _seed_words(db)
    assert _read(db, "SELECT value FROM meta WHERE key = 'min_code_version'") == [
        (str(MAINTENANCE_CODE_VERSION),)
    ]

    for module in ("mnemos.code_version", "mnemos.simple_runtime", "mnemos.store.sqlite_store"):
        monkeypatch.setattr(f"{module}.MAINTENANCE_CODE_VERSION", MAINTENANCE_CODE_VERSION - 1,
                            raising=False)
    assert main(["--db-path", str(db), *SCOPE_ARGS, "consolidate"]) == 0
    out = capsys.readouterr().out

    assert "Consolidation skipped: no passes ran." in out, out
    assert _links(db, first) == set(), "older code linked a store this code opened"
