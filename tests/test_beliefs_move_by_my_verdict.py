"""A belief changes only by the agent's own verdict, never by a model's reading.

With a provider configured, every memory saved was read by a model against the
agent's beliefs, and its reading moved them: up 0.07 per point of support,
down 0.04 per point of contradiction. The daily belief review did the same
over recent memories. That's the flaw the substrate was retired for: another
mind's judgement inside what the agent believes. The docs already said a
belief changes only by the agent's verdict (mnemos_reflect). Now the code does
too. A model's reading still weighs the moment, raising surprise and linking
the contradiction, but the belief stays as the agent left it.
"""

import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from mnemos.consolidation.daemon import ConsolidationDaemon
from mnemos.core.belief import Belief
from mnemos.core.types import ConnectionRelation
from mnemos.encoding.encoder import Encoder
from mnemos.store.sqlite_store import EngramStore


class ReadsEveryBelief:
    """A provider that reads each new memory as bearing hard on each belief."""

    def __init__(self, relation: str):
        self.relation = relation

    def structured_complete(self, system, user, temperature=0.0, max_tokens=2000):
        if "belief evaluator" not in system:
            return "[]"
        ids = re.findall(r"### Belief (belief_\w+)", user)
        return json.dumps([
            {"belief_id": i, "relation": self.relation, "impact": 0.9, "reasoning": "it bears on it"}
            for i in ids
        ])

    def complete(self, prompt):
        return ""


@pytest.fixture
def store(tmp_path):
    store = EngramStore(str(tmp_path / "memory.db"))
    yield store
    store.close()


def _held_belief(store, *, evidence_id: str = "") -> Belief:
    belief = Belief(agent_id="nova", content="Riley wants the cue to ask, not tell", confidence=0.6)
    # Revised long ago, so no cooldown stands between a reading and the belief.
    belief.last_revised = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    if evidence_id:
        belief.supporting_engram_ids = [evidence_id]
    store.save_belief(belief)
    return belief


def _confidence(store, belief: Belief) -> float:
    (held,) = [b for b in store.get_beliefs("nova", active_only=True) if b.id == belief.id]
    return held.confidence


@pytest.mark.parametrize("relation", ["SUPPORTS", "CONTRADICTS"])
def test_a_models_reading_of_a_new_memory_never_moves_a_belief(store, relation):
    belief = _held_belief(store)
    encoder = Encoder(store, llm_client=ReadsEveryBelief(relation))

    encoder.encode(
        content="Riley said the cue should tell me what to do next.",
        agent_id="nova",
        author_kind="agent",
    )

    assert _confidence(store, belief) == pytest.approx(0.6)


def test_a_contradiction_still_weighs_the_moment(store):
    """The reading isn't thrown away: it raises surprise and links the memory
    to the belief's evidence as contradicting it."""
    evidence = Encoder(store).encode(
        content="Riley wants the cue to ask me a question, never to tell me.",
        agent_id="nova",
        author_kind="agent",
        skip_surprise_detection=True,
    )
    belief = _held_belief(store, evidence_id=evidence.id)
    encoder = Encoder(store, llm_client=ReadsEveryBelief("CONTRADICTS"))

    engram = encoder.encode(
        content="Riley said the cue should tell me what to do next.",
        agent_id="nova",
        author_kind="agent",
    )

    assert engram.encoding_context.surprise_level > 0
    assert any(
        c.relation == ConnectionRelation.CONTRADICTS and c.target_id == evidence.id
        for c in engram.connections
    )
    assert _confidence(store, belief) == pytest.approx(0.6)


def test_the_deep_cycle_has_no_belief_review(store):
    belief = _held_belief(store)
    Encoder(store).encode(
        content="Riley said the cue should tell me what to do next.",
        agent_id="nova",
        author_kind="agent",
        skip_surprise_detection=True,
    )
    daemon = ConsolidationDaemon(store=store, config={}, llm_client=ReadsEveryBelief("CONTRADICTS"))

    stats = daemon.run_cycle(deep=True, agent_id="nova")

    assert "belief_review" not in stats["passes_run"]
    assert _confidence(store, belief) == pytest.approx(0.6)
