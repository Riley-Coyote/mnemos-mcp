"""A session's first save doesn't wait for Mnemos to open.

A server opened its runtime on its first tool call: the store's checks, the
meaning model's libraries (torch, sentence-transformers) and the model. On a
copy of a real store, a fresh server's first capture took 1.7 s twenty
seconds after it started, and 3.2 s at once, while the next took 0.1 s; on a
busy Mac it was 12 s. And the runtime loaded its own copy of the model beside
the cue answerer's, about 50 MB a server.

Now a server warms its runtime in the background as it starts, where the
prompt hook is in use and the store exists, and every index in a process
shares one copy of each local model, encoding one call at a time.
"""

import sqlite3
import threading
import time

import pytest

from mnemos import simple_mcp
from mnemos.simple_runtime import MnemosRuntime
from mnemos.store import embedding_index as ei


class FakeModel:
    """A model that says when two encodes overlap."""

    def __init__(self):
        self.busy = False
        self.overlapped = False

    def encode(self, texts, normalize_embeddings=True, batch_size=32):
        import numpy as np

        if self.busy:
            self.overlapped = True
        self.busy = True
        time.sleep(0.02)
        self.busy = False
        rows = [texts] if isinstance(texts, str) else texts
        vectors = np.ones((len(rows), 384), dtype="float32") / np.sqrt(384)
        return vectors[0] if isinstance(texts, str) else vectors


@pytest.fixture
def model(monkeypatch):
    """The local backend importable, its loader counted, and its model fake."""
    pytest.importorskip("numpy")
    loads = []
    fake = FakeModel()

    def load(name):
        loads.append(name)
        return fake

    monkeypatch.setattr(ei, "_check_local_deps", lambda: True)
    monkeypatch.setattr(ei, "_load_local_model", load)
    monkeypatch.setattr(ei, "_SHARED_MODELS", {}, raising=False)
    monkeypatch.setattr(ei, "_ENCODE_LOCKS", {}, raising=False)
    fake.loads = loads
    return fake


@pytest.fixture
def server(tmp_path, monkeypatch):
    """The server's runtime settings for a store in tmp_path, the hook in use."""
    import mnemos.cue

    monkeypatch.setattr(mnemos.cue, "hook_in_use", lambda *a, **k: True)
    db = tmp_path / "memory.db"
    simple_mcp.configure_runtime(db_path=str(db), agent_id="demo")
    yield db
    simple_mcp.configure_runtime()


def _make_store(db):
    runtime = MnemosRuntime(db_path=db, agent_id="demo", use_dedicated_model=False)
    runtime._ensure_init()
    runtime.close()
    assert db.exists()


def test_the_server_opens_its_runtime_before_the_first_call(server, model):
    _make_store(server)

    thread = simple_mcp.start_warm_up()

    assert thread is not None
    thread.join(timeout=60)
    runtime = simple_mcp._runtime
    assert runtime is not None and runtime._store is not None, "the runtime was not opened"
    assert model.loads == ["all-MiniLM-L6-v2"], "the model was not loaded ahead of the call"


def test_a_call_during_the_warm_up_waits_for_it_and_uses_its_runtime(server, monkeypatch):
    _make_store(server)
    release = threading.Event()
    opened = []
    original = MnemosRuntime.warm

    def slow_warm(self):
        opened.append(self)
        release.wait(timeout=30)
        return original(self)

    monkeypatch.setattr(MnemosRuntime, "warm", slow_warm)
    thread = simple_mcp.start_warm_up()
    assert thread is not None
    deadline = time.monotonic() + 30
    while not opened and time.monotonic() < deadline:
        time.sleep(0.01)
    assert opened, "the warm-up never began"
    got = []
    caller = threading.Thread(target=lambda: got.append(simple_mcp._get_runtime()))
    caller.start()
    caller.join(timeout=0.3)

    assert caller.is_alive(), "the call did not wait for the warm-up"
    release.set()
    caller.join(timeout=30)
    thread.join(timeout=30)
    assert got == opened, "the call opened a second runtime"


def test_no_warm_up_where_the_hook_is_not_in_use(server, monkeypatch):
    import mnemos.cue

    _make_store(server)
    monkeypatch.setattr(mnemos.cue, "hook_in_use", lambda *a, **k: False)

    assert simple_mcp.start_warm_up() is None
    assert simple_mcp._runtime is None


def test_starting_a_server_makes_no_store(server):
    assert simple_mcp.start_warm_up() is None
    assert not server.exists()


def test_the_warm_up_is_not_a_session(server, model):
    _make_store(server)
    conn = sqlite3.connect(server)
    before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("lived_days", "consolidation_log", "memory_trace", "engrams")
    }
    meta = dict(conn.execute("SELECT key, value FROM meta WHERE key LIKE 'simple:%'").fetchall())
    conn.close()

    simple_mcp.start_warm_up().join(timeout=60)

    conn = sqlite3.connect(server)
    after = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in before
    }
    assert after == before
    assert dict(conn.execute("SELECT key, value FROM meta WHERE key LIKE 'simple:%'").fetchall()) == meta
    conn.close()


def test_a_runtime_warmed_in_another_thread_saves_in_this_one(server, model):
    _make_store(server)
    simple_mcp.start_warm_up().join(timeout=60)

    said = simple_mcp._get_runtime().capture(content="Riley keeps the ferry timetable on the fridge.")

    assert "Captured continuity" in said, said
    conn = sqlite3.connect(server)
    assert conn.execute("SELECT COUNT(*) FROM passage_vectors").fetchone()[0] > 0
    conn.close()


def test_an_index_opened_in_one_thread_is_used_in_another(tmp_path, model):
    _make_store(tmp_path / "memory.db")
    made = []
    opener = threading.Thread(target=lambda: made.append(ei.EmbeddingIndex(db_path=str(tmp_path / "memory.db"))))
    opener.start()
    opener.join()

    assert made[0]._get_conn().execute("SELECT COUNT(*) FROM passage_vectors").fetchone()[0] >= 0


def test_every_index_in_a_process_shares_one_model(model):
    first = ei.EmbeddingIndex(read_only=True)
    second = ei.EmbeddingIndex(read_only=True)

    assert first._embed("ferry") is not None and second._embed("fern") is not None
    assert model.loads == ["all-MiniLM-L6-v2"]
    assert first._embedder._get_model() is second._embedder._get_model()


def test_two_threads_encode_one_at_a_time(model):
    indexes = [ei.EmbeddingIndex(read_only=True) for _ in range(2)]
    threads = [
        threading.Thread(target=lambda index=index: [index._embed(f"probe {i}") for i in range(10)])
        for index in indexes
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not model.overlapped, "two encodes ran at once on one tokenizer"


def test_a_model_that_fails_to_load_is_tried_again(monkeypatch):
    monkeypatch.setattr(ei, "_SHARED_MODELS", {}, raising=False)
    monkeypatch.setattr(ei, "_ENCODE_LOCKS", {}, raising=False)
    tries = []

    def load(name):
        tries.append(name)
        if len(tries) == 1:
            raise OSError("not on disk")
        return FakeModel()

    monkeypatch.setattr(ei, "_load_local_model", load)
    with pytest.raises(OSError):
        ei._shared_local_model("all-MiniLM-L6-v2")

    assert ei._shared_local_model("all-MiniLM-L6-v2") is not None
    assert len(tries) == 2


def test_the_server_starts_its_warm_up(server, monkeypatch):
    started = []
    monkeypatch.setattr(simple_mcp, "start_warm_up", lambda: started.append(True), raising=False)
    monkeypatch.setattr(simple_mcp, "start_cue_answerer", lambda: None)
    monkeypatch.setattr(simple_mcp.simple_mcp, "run", lambda *a, **k: None)
    monkeypatch.setattr(simple_mcp.signal, "signal", lambda *a, **k: None)

    simple_mcp.run_simple_server(db_path=str(server), agent_id="demo")

    assert started == [True]
