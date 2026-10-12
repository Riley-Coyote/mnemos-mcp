"""A link is removed only by a verdict that says so.

Connection discovery's second phase sends a memory's mechanically formed
links (``supports``, ``co_activated``) to the chosen model and retypes them.
It removed every link whose target was missing from the typed verdicts,
reading the gap as NONE. A call that raised, an empty reply, and a usage-limit
message on stdout (the Claude CLI client hands back whatever stdout holds)
each leave that gap for every target, so each removed every link the pass
had sent, and the cycle was logged as a success. Nothing was retyped in such
a cycle, so the batch limit never stopped the pass: it went on through every
memory it had loaded. A fork of this pass removed 6,321 links from one
agent's store that way. A NONE that was meant also removed every other link
between the two memories, typed ones no verdict had been asked about.

And `mnemos consolidate`, the bridge and the advanced tool gave the model to
shallow cycles too, so the scheduled job ran this every four hours.

Now a link goes only on an explicit NONE for its exact id, and only that
link. A reply that can't be read leaves every link as it was and ends the
pass for the cycle, and says why. A shallow cycle gives the model to no pass.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from mnemos import llm
from mnemos.cli import main
from mnemos.code_version import MAINTENANCE_CODE_VERSION
from mnemos.consolidation.connection_discovery import run_connection_discovery
from mnemos.consolidation.daemon import ConsolidationDaemon
from mnemos.core.engram import Connection, Engram
from mnemos.encoding.encoder import Encoder
from mnemos.store import embedding_index as ei
from mnemos.store.sqlite_store import EngramStore

SCOPE = dict(owner_agent_id="default", person_id="user", project_scope="global")
PASS = dict(agent_id="default", person_id="user", project_scope="global")
PASS_ARGS = ("--agent-id", "default", "--person-id", "user", "--project-scope", "global")

# No two share a word, so the pass finds no new candidates and asks the model
# only about the links already there.
KEEPER = "harbour lighthouse keeper polishing brass lenses nightly"
STARTER = "sourdough starter fed with rye flour every morning"
BOW = "violin bow rehaired with horsehair from mongolia"
GLACIER = "glacier meltwater carving turquoise channels through moraine"

USAGE_LIMIT = "Claude AI usage limit reached|1760140800"

NONE = {"relation": "NONE", "direction": "forward", "confidence": 0.9, "reasoning": "unrelated"}
EXTENDS = {"relation": "EXTENDS", "direction": "forward", "confidence": 0.8, "reasoning": "goes further"}
SUPPORTS = {"relation": "SUPPORTS", "direction": "forward", "confidence": 0.8, "reasoning": "agrees"}


class _Model:
    """The chosen provider. Every call gets ``reply``: an exception to raise,
    or a function of the candidate ids in the prompt that returns the reply,
    or the reply itself."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def structured_complete(self, system, user, temperature=0.0, max_tokens=2000):
        self.calls += 1
        if isinstance(self.reply, BaseException):
            raise self.reply
        if callable(self.reply):
            return self.reply(re.findall(r"^### Candidate (\S+)$", user, re.MULTILINE))
        return self.reply

    def complete(self, prompt):
        return self.structured_complete("", prompt)


def _says(verdicts: dict[str, dict]):
    """A reply that gives each candidate in ``verdicts`` its verdict and says
    nothing of the rest."""
    return lambda ids: json.dumps([{"candidate_id": i, **verdicts[i]} for i in ids if i in verdicts])


def _to_each(*verdicts: dict):
    """A reply that gives every candidate each of ``verdicts``."""
    return lambda ids: json.dumps([{"candidate_id": i, **v} for i in ids for v in verdicts])


def _memory(store, content: str) -> Engram:
    engram = Engram(content=content, kind="semantic", **SCOPE)
    store.save_engram(engram)
    return engram


def _link(store, source: Engram, target: Engram, relation: str) -> None:
    store.save_connection(source.id, Connection(
        target_id=target.id, relation=relation, strength=0.5, formed_by="encoding_no_llm",
    ))


def _graph(store) -> tuple[Engram, Engram, Engram, Engram]:
    """Two memories with mechanical links to reclassify, one of them beside a
    typed link between the same two memories, which no verdict is asked
    about."""
    keeper, starter, bow, glacier = (_memory(store, text) for text in (KEEPER, STARTER, BOW, GLACIER))
    _link(store, keeper, starter, "supports")
    _link(store, keeper, starter, "contradicts")
    _link(store, keeper, bow, "co_activated")
    _link(store, glacier, bow, "supports")
    return keeper, starter, bow, glacier


def _rows(store) -> set[tuple[str, str, str]]:
    return {
        (row[0], row[1], row[2]) for row in store._get_conn().execute(
            "SELECT source_id, target_id, relation FROM connections"
        )
    }


def _rows_at(db) -> set[tuple[str, str, str]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {tuple(row) for row in conn.execute(
            "SELECT source_id, target_id, relation FROM connections"
        )}
    finally:
        conn.close()


@pytest.fixture
def graph(store):
    return _graph(store)


# ── 1. A reply that says nothing removes nothing ──

SAYS_NOTHING = {
    "the call raises": RuntimeError("429 Too Many Requests"),
    "an empty reply": "",
    "a usage-limit message": USAGE_LIMIT,
    "prose": "I'm sorry, I can't classify these memories right now.",
    "no reply at all": None,
    "a cut-off reply": '[{"candidate_id": "',
    "a list of no objects": '["SUPPORTS", "NONE"]',
    "an error object": '{"type": "error", "error": {"type": "rate_limit_error"}}',
    "an empty list": "[]",
    "a NONE at low confidence": _to_each({**NONE, "confidence": 0.2}),
    "a NONE with no confidence": _to_each({"relation": "NONE"}),
    "a NONE at NaN confidence": _to_each({**NONE, "confidence": float("nan")}),
    "a NONE above full confidence": _to_each({**NONE, "confidence": 90}),
    "a null relation": _to_each({**NONE, "relation": None}),
    "a NONE for another id": lambda ids: json.dumps([{**NONE, "candidate_id": i + "x"} for i in ids]),
    "a NONE and a type for one id": _to_each(NONE, SUPPORTS),
}


@pytest.mark.parametrize("reply", list(SAYS_NOTHING.values()), ids=list(SAYS_NOTHING))
def test_a_reply_without_a_clear_none_removes_no_link(store, graph, reply):
    before = _rows(store)
    model = _Model(reply)

    stats = run_connection_discovery(store, config={}, llm_client=model, **PASS)

    assert model.calls >= 1, "the model was never asked, so this proves nothing"
    assert before <= _rows(store), f"links removed: {before - _rows(store)}"
    assert stats["connections_removed"] == 0


def test_a_partial_reply_retypes_what_it_judged_and_removes_nothing(store, graph):
    keeper, starter, bow, glacier = graph
    before = _rows(store)

    stats = run_connection_discovery(
        store, config={}, llm_client=_Model(_says({starter.id: EXTENDS})), **PASS,
    )

    after = _rows(store)
    assert before <= after, f"links the reply left out were removed: {before - after}"
    assert stats["connections_removed"] == 0
    assert (keeper.id, starter.id, "extends") in after, "the verdict the reply gave was not applied"
    assert stats["connections_reclassified"] == 1


# ── 2. An explicit NONE removes that link, and only it ──


def test_an_explicit_none_removes_that_link_and_no_other(store, graph):
    keeper, starter, bow, glacier = graph

    stats = run_connection_discovery(
        store, config={}, llm_client=_Model(_says({starter.id: NONE})), **PASS,
    )

    after = _rows(store)
    assert (keeper.id, starter.id, "supports") not in after, "the link called NONE is still there"
    assert (keeper.id, starter.id, "contradicts") in after, (
        "a typed link between the same two memories went with it, and no verdict was asked about it"
    )
    assert (keeper.id, bow.id, "co_activated") in after, "a link the reply left out was removed"
    assert (glacier.id, bow.id, "supports") in after, "a link the reply left out was removed"
    assert stats["connections_removed"] == 1


def test_every_link_called_none_goes(store, graph):
    keeper, starter, bow, glacier = graph

    stats = run_connection_discovery(store, config={}, llm_client=_Model(_to_each(NONE)), **PASS)

    assert _rows(store) == {(keeper.id, starter.id, "contradicts")}
    assert stats["connections_removed"] == 3


# ── 3. A provider that isn't answering is asked once a cycle ──


@pytest.mark.parametrize("reply, why", [
    (RuntimeError("429 Too Many Requests"), "the call failed (RuntimeError: 429 Too Many Requests)"),
    ("", "the reply was empty"),
    (USAGE_LIMIT, f"the reply wasn't a list of verdicts ({USAGE_LIMIT!r})"),
], ids=["raises", "empty", "usage limit"])
def test_a_reply_that_cannot_be_read_ends_the_pass_and_says_why(store, graph, reply, why):
    model = _Model(reply)

    # A batch of one: what stops the pass here is the reply, not the batch.
    stats = run_connection_discovery(
        store, config={"reclassify_batch_size": 1}, llm_client=model, **PASS,
    )

    assert model.calls == 1, "the pass went on asking a provider that wasn't answering"
    assert stats["reclassify_stopped"] == f"reclassifying stopped, links left as they were: {why}"


# ── 4. Only a deep cycle gives the model to a pass ──


def test_a_shallow_cycle_gives_the_model_to_no_pass(store, graph):
    before = _rows(store)
    model = _Model(RuntimeError("429 Too Many Requests"))

    stats = ConsolidationDaemon(store, config={}, llm_client=model).run_cycle(deep=False, **PASS)

    assert "connection_discovery" in stats["passes_run"]
    assert model.calls == 0, "a shallow cycle called the model"
    assert stats["substrate"]["provider"] is None, "the log says a provider assisted"
    assert before <= _rows(store)


def test_a_deep_cycle_still_reclassifies(store, graph):
    keeper, starter, bow, glacier = graph
    model = _Model(_says({starter.id: NONE}))

    stats = ConsolidationDaemon(store, config={}, llm_client=model).run_cycle(deep=True, **PASS)

    assert stats["connection_discovery"]["connections_removed"] == 1
    assert (keeper.id, starter.id, "supports") not in _rows(store)
    assert stats["substrate"]["provider"] == "_Model"


@pytest.fixture
def consolidate(tmp_path, monkeypatch):
    """`mnemos consolidate` on a store holding the graph, with the provider
    chosen and meaning off (nothing loads, nothing reaches the network)."""
    db = tmp_path / "memory.db"
    store = EngramStore(str(db))
    try:
        _graph(store)
    finally:
        store.close()
    monkeypatch.setattr(ei, "_check_local_deps", lambda: False)
    monkeypatch.setattr(ei, "_LOGGED", set(), raising=False)

    def run(model: _Model, *flags: str) -> None:
        monkeypatch.setattr(llm, "create_client", lambda *args, **kwargs: model)
        assert main(["--db-path", str(db), *PASS_ARGS, "consolidate", *flags]) == 0

    run.db = db
    return run


def test_scheduled_consolidate_never_asks_the_model(consolidate):
    before = _rows_at(consolidate.db)
    model = _Model(USAGE_LIMIT)

    consolidate(model)

    assert model.calls == 0, "the four-hourly job called the model"
    assert _rows_at(consolidate.db) == before


def test_consolidate_deep_keeps_every_link_when_the_model_fails(consolidate, capsys):
    before = _rows_at(consolidate.db)
    model = _Model(USAGE_LIMIT)

    consolidate(model, "--deep")

    out = capsys.readouterr().out
    assert model.calls >= 1, "the deep cycle never asked the model, so this proves nothing"
    assert before <= _rows_at(consolidate.db), f"links removed: {before - _rows_at(consolidate.db)}"
    [connections] = [line for line in out.splitlines() if line.startswith("  Connections:")]
    assert (
        "reclassifying stopped, links left as they were: the reply wasn't a list of verdicts"
        in connections
    ), out
    assert not re.search(r"\d+ removed", connections), out


# ── 5. A capture survives a reply with no verdict in it ──


@pytest.mark.parametrize("reply", ['["SUPPORTS"]', None], ids=["a list of no objects", "no reply"])
def test_a_capture_survives_a_reply_with_no_verdict_in_it(store, reply):
    Encoder(store).encode(content=KEEPER, kind="semantic", skip_surprise_detection=True)
    model = _Model(reply)

    engram = Encoder(store, llm_client=model).encode(
        content="the lighthouse keeper polishes brass lenses at dusk",
        kind="semantic", skip_surprise_detection=True,
    )

    assert model.calls == 1, "the classifier was never asked, so this proves nothing"
    assert store.get_engram(engram.id) is not None


def test_the_code_version_was_raised_for_this_change():
    assert MAINTENANCE_CODE_VERSION >= 22, (
        "how maintenance removes links changed, and the code version was not raised"
    )
