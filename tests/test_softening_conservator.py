"""Softener as conservator: softening may compress, never inflate or invent.

Softening used to have a model rewrite a fading memory "in the rememberer's
own voice". Since 0.4.0 no model softens: that was another mind's words where
the agent's belong. A memory's words stay the agent's unless an operator opts
into the mechanical rule (soften_without_model). These tests cover what
remains:

1. A model handed to the pass is never called, and no words of its land.
2. The conservation guard: a candidate never grows longer and never
   introduces named entities absent from the original, enforced in code.
3. softening_dry_run logs before/after pairs to consolidation_log without
   touching any engram.
"""

import pytest

from mnemos.consolidation.softening import _conserve, run_softening_pass
from mnemos.core.engram import EncodingContext, Engram
from mnemos.core.types import EngramKind
from mnemos.store.sqlite_store import EngramStore


AGENT_A = "nova"
AGENT_B = "vektor"


class StubLLM:
    """Records prompts; replies with a fixed response."""

    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _engram(agent: str, content: str, *, accessibility: float = 0.5,
            resolution: float = 1.0, impact: str = "set") -> Engram:
    e = Engram(
        content=content,
        content_at_encoding=content,
        kind=EngramKind.SEMANTIC,
        impact=impact,  # pre-set so the pass skips impact extraction LLM calls
        owner_agent_id=agent,
        encoding_context=EncodingContext(session_id=f"{agent}-s1"),
    )
    e.accessibility = accessibility
    e.resolution = resolution
    return e


@pytest.fixture()
def store(tmp_path):
    s = EngramStore(tmp_path / "conservator.db")
    yield s
    s.close()


@pytest.fixture()
def seeded(store):
    """Agent A: two vivid memories + one fading candidate. Agent B: one vivid."""
    vivid_1 = _engram(
        AGENT_A,
        "i kept circling the same connection graph until it finally clicked... the shape was the answer",
        accessibility=0.9,
    )
    vivid_2 = _engram(
        AGENT_A,
        "quiet morning, rewrote the retrieval pass three times and loved every minute of it",
        accessibility=0.9,
    )
    # accessibility 0.45 → target resolution ~0.5: the standard softener
    # path (the deep-impression path engages below 0.4).
    fading = _engram(
        AGENT_A,
        "On June 3rd at 14:02 I debugged the spreading activation threshold with a profiler trace",
        accessibility=0.45,
    )
    other_agent = _engram(
        AGENT_B,
        "VEKTOR-DISTINCTIVE-PHRASE optics and lens calibrations all afternoon",
        accessibility=0.9,
    )
    for e in (vivid_1, vivid_2, fading, other_agent):
        store.save_engram(e)
    return {"vivid_1": vivid_1, "vivid_2": vivid_2, "fading": fading, "other": other_agent}


def test_a_model_is_never_called_and_its_words_never_land(store, seeded):
    stub = StubLLM("a fading sense of chasing the activation threshold")
    run_softening_pass(store, {"softening_min_age_hours": 0}, stub, agent_id=AGENT_A)

    assert stub.prompts == []
    kept = store.get_engram(seeded["fading"].id)
    assert kept.content == seeded["fading"].content_at_encoding
    assert kept.resolution == 1.0


def test_the_guard_never_lets_a_candidate_grow(seeded):
    original = seeded["fading"].content
    inflated = original + " and then so much more happened that evening, truly a saga"

    kept = _conserve(original, inflated, 0.5)

    assert len(kept) <= len(original)
    assert "truly a saga" not in kept


def test_the_guard_never_lets_a_candidate_invent_a_name(seeded):
    original = seeded["fading"].content

    kept = _conserve(original, "a hazy memory of debugging with Voldemort near the threshold", 0.5)

    assert "Voldemort" not in kept


def test_dry_run_writes_nothing_and_logs_pairs(store, seeded):
    before = {
        e.id: (e.content, e.resolution, e.strength, len(e.connections), len(e.versions))
        for e in store.get_active_engrams(agent_id=AGENT_A, limit=100)
    }

    stub = StubLLM("a fading impression of the threshold")
    stats = run_softening_pass(store, {"softening_min_age_hours": 0, "softening_dry_run": True}, stub, agent_id=AGENT_A
    )

    after = {
        e.id: (e.content, e.resolution, e.strength, len(e.connections), len(e.versions))
        for e in store.get_active_engrams(agent_id=AGENT_A, limit=100)
    }
    assert after == before, "dry run mutated engrams"
    assert stats["dry_run"] is True
    assert stats["engrams_softened"] == 0
    assert stats["engrams_would_soften"] >= 1

    runs = store.get_consolidation_runs("softening_dry_run")
    assert runs, "dry run logged nothing"
    pairs = runs[0]["stats"]["pairs"]
    assert runs[0]["stats"]["agent_id"] == AGENT_A
    assert any(p["engram_id"] == seeded["fading"].id for p in pairs)
    pair = next(p for p in pairs if p["engram_id"] == seeded["fading"].id)
    assert pair["before"].startswith("On June 3rd")
    assert pair["after"] and pair["resolution_target"] < pair["resolution_before"]


def test_rule_based_path_also_conserved(store, seeded):
    """No LLM at all: the rule-based fallback obeys the same invariants."""
    run_softening_pass(store, {"softening_min_age_hours": 0}, None, agent_id=AGENT_A)
    softened = store.get_engram(seeded["fading"].id)
    assert len(softened.content) <= len(seeded["fading"].content_at_encoding)


def test_tiny_memory_keeps_original_rather_than_inflating(store):
    tiny = _engram(AGENT_A, "ok then.", accessibility=0.01)
    store.save_engram(tiny)
    run_softening_pass(store, {"softening_min_age_hours": 0}, None, agent_id=AGENT_A)
    softened = store.get_engram(tiny.id)
    # Nothing to shed: conservation keeps the original instead of an
    # "impression" boilerplate that would be longer than the memory itself.
    assert softened.content == "ok then."
